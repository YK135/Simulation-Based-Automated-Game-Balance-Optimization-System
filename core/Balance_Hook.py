"""
Balance_Hook.py
─────────────────────────────────────────────
기존 RPG 게임 ↔ AI 엔진 연결 브릿지.

변경사항:
  - 몬스터 생성 백그라운드 스레드 실행 (게임 멈춤 없음)
  - 모니터 통신을 stdin 파이프 → 파일 기반 IPC로 변경 (macOS 호환)
  - 로그 저장 경로 루트 기준으로 수정
"""

import copy
import sys
import os
import threading
import subprocess
import platform

from ai.Battle_Engine  import BattleEngine, EntitySnapshot, BattleResult, TurnLog
from ai.Auto_AI        import PlayerAI, EnemyAI
from ai.Simulator      import MonsterFactory, BattleSimulator, BASE_ENEMIES
from ai.LOG_Manager    import LogManager
from ai.FeedBack       import FeedbackEngine
from ai.Visualizer     import Visualizer
from game.Enemy_Class  import Make_Goblin, Make_Bat

# 루트 디렉토리 (Main.py가 있는 곳)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 파일 기반 IPC 경로
PIPE_FILE = "/tmp/ai_monitor_pipe.txt"


def _player_to_snap(player, item_list: list) -> EntitySnapshot:
    skills = []
    if hasattr(player, 'skill') and player.skill:
        skills = list(player.skill.learned_skills)
    return EntitySnapshot(
        name=player.name,
        hp=player.hp,       maxhp=player.maxhp,
        mp=player.mp,       maxmp=player.maxmp,
        stg=player.stg,     arm=player.arm,
        sparm=player.sparm, sp=player.sp,
        luc=player.luc,     lv=player.lv,
        spd=getattr(player, "spd", 10.0),  # SPD 반영 (도적 등 고SPD 직업 대응)
        learned_skills=skills,
        items=list(item_list),
    )


def _write_to_monitor(msg: str):
    """파일 IPC를 통해 모니터 창에 메시지 전송"""
    try:
        with open(PIPE_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
            f.flush()
    except Exception:
        pass


def _open_monitor():
    """
    AI 밸런싱 모니터 창을 별도 Terminal로 열기.
    파일 기반 IPC 사용 → macOS stdin 파이프 문제 해결.
    """
    import time as _time

    # 기존 파이프 파일 초기화
    try:
        os.remove(PIPE_FILE)
    except FileNotFoundError:
        pass

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monitor_py = None
    for name in ["Ai_monitor.py", "ai_monitor.py"]:
        mp = os.path.join(script_dir, name)
        if os.path.exists(mp):
            monitor_py = mp
            break

    if monitor_py is None:
        return False  # 모니터 파일 없음

    try:
        if platform.system() == "Darwin":
            apple_script = (
                'tell application "Terminal"\n'
                '    activate\n'
                '    do script "python3 \\"' + monitor_py + '\\""\n'
                'end tell'
            )
            subprocess.Popen(
                ["osascript", "-e", apple_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            _time.sleep(0.8)  # 터미널 창 열릴 때까지 대기
        elif platform.system() == "Windows":
            subprocess.Popen(
                ["python", monitor_py],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            _time.sleep(0.5)
        else:
            subprocess.Popen(
                ["python3", monitor_py],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            _time.sleep(0.3)
        return True
    except Exception:
        return False


class BalanceHook:
    """
    게임 ↔ AI 엔진 브릿지.
    몬스터 시뮬레이션은 백그라운드 스레드에서 실행된다.
    """

    DIFFICULTY_RATIO = {"hard": 2, "normal": 5, "easy": 3}

    # 폴백 몬스터 팩토리 (하드코딩 제거 — Enemy_Class 기준으로 통일)
    _FALLBACK_MAKERS = {
        "고블린": Make_Goblin,
        "박쥐":   Make_Bat,
    }

    def _make_fallback(self, enemy_type: str) -> EntitySnapshot:
        """
        시뮬 완료 전 폴백용 몬스터.
        Enemy_Class의 Make_Goblin / Make_Bat 중급 기준으로 생성 → 수치 출처 단일화.
        폴백 사용 여부는 로그로 기록한다.
        """
        maker = self._FALLBACK_MAKERS.get(enemy_type, Make_Goblin)
        unit  = maker(self.player.lv, "중")
        if self.verbose:
            print(f"  [AI] 시뮬 대기 중 — {enemy_type} 폴백 사용 (Lv{self.player.lv} 중급 기준)")
        # Unit → EntitySnapshot 변환
        return EntitySnapshot(
            name=unit.name,
            hp=unit.hp,     maxhp=unit.hp,
            mp=unit.mp,     maxmp=unit.mp,
            stg=unit.stg,   arm=unit.arm,
            sparm=unit.sparm, sp=unit.sp,
            luc=unit.luc,   lv=unit.lv,
            spd=getattr(unit, "spd", 10),
        )

    def __init__(self, player, item_list, show_graph=False, verbose=True):
        self.player     = player
        self.item_list  = item_list
        self.show_graph = show_graph
        self.verbose    = verbose

        self._lm  = LogManager()
        self._fb  = FeedbackEngine(use_llm=False)
        self._viz = Visualizer(save_dir=os.path.join(ROOT_DIR, "graphs")) if show_graph else None
        self._monitor_opened = False  # 모니터 창 열렸는지 여부

        # 캐시: {enemy_type: {"hard": (snap, sim), ...}}
        self._monster_cache = {}
        self._cache_lock    = threading.Lock()

        # 백그라운드 시뮬 스레드 추적
        self._sim_threads = {}   # {enemy_type: Thread}
        self._sim_ready   = {}   # {enemy_type: threading.Event}

        self._last_sim_result = None
        self._last_difficulty = "normal"
        self._last_lv         = player.lv

        # 게임 시작 시 기본 몬스터 2종 미리 백그라운드 시뮬 시작
        self._start_background_sim("고블린")
        self._start_background_sim("박쥐")

    # ── 모니터 출력 헬퍼 ─────────────────────

    def _monitor_write(self, msg: str):
        """모니터 창에 메시지 전송 (파일 IPC)"""
        _write_to_monitor(msg)

    def _monitor_done(self):
        """모니터 창에 종료 신호 전송"""
        _write_to_monitor("__DONE__")

    # ── 백그라운드 시뮬레이션 ────────────────

    def _start_background_sim(self, enemy_type: str):
        """백그라운드 스레드에서 시뮬레이션 시작"""
        if enemy_type in self._sim_threads:
            return  # 이미 실행 중

        event = threading.Event()
        self._sim_ready[enemy_type] = event

        def _run():
            try:
                p_snap  = _player_to_snap(self.player, self.item_list)
                factory = MonsterFactory(p_snap, enemy_type)

                # 모니터 창: 딱 한 번만 열기
                with self._cache_lock:
                    if self.verbose and not self._monitor_opened:
                        self._monitor_opened = _open_monitor()

                # generate_all에 모니터 콜백 전달
                monsters = factory.generate_all(
                    verbose=False,
                    monitor=self,   # self를 넘겨서 _monitor_write 사용
                )

                with self._cache_lock:
                    self._monster_cache[enemy_type] = monsters
                    self._last_lv = self.player.lv

                # 그래프 저장 (옵션)
                if self._viz:
                    try:
                        self._viz.win_rate_bar(monsters, self.player.name)
                        self._viz.stat_radar(
                            p_snap, monsters["hard"][0],
                            title=f"스탯 비교 — {self.player.name} vs 강한 {enemy_type}"
                        )
                    except Exception:
                        pass

            except Exception as e:
                if self.verbose:
                    print(f"  [AI] {enemy_type} 시뮬 오류: {e}")
                self._monitor_write(f"  [오류] {enemy_type}: {e}")
            finally:
                event.set()  # 완료 신호
                # 마지막 스레드가 완료되면 모니터에 DONE 신호
                all_done = all(
                    self._sim_ready.get(et, threading.Event()).is_set()
                    for et in self._sim_threads
                )
                if all_done:
                    self._monitor_done()

        t = threading.Thread(target=_run, daemon=True)
        self._sim_threads[enemy_type] = t
        t.start()

    def _get_cached_monsters(self, enemy_type: str):
        """
        캐시에서 몬스터 데이터 반환.
        시뮬 완료 전이면 잠깐 기다리거나 폴백 사용.
        """
        with self._cache_lock:
            if enemy_type in self._monster_cache:
                return self._monster_cache[enemy_type]

        # 시뮬레이션이 실행 중이면 최대 2초 대기
        event = self._sim_ready.get(enemy_type)
        if event:
            ready = event.wait(timeout=2.0)
            if ready:
                with self._cache_lock:
                    if enemy_type in self._monster_cache:
                        return self._monster_cache[enemy_type]

        # 여전히 없으면 폴백 (기본 스탯)
        return None

    # ── 1. 전투 전: 몬스터 생성 ──────────────

    def get_enemy(self, enemy_type: str = "고블린") -> EntitySnapshot:
        """AI 밸런싱된 몬스터 반환. 시뮬 미완료 시 기본 스탯 사용."""

        # 레벨업 감지 → 캐시 무효화 + 재시뮬
        if self.player.lv != self._last_lv:
            self.on_level_up()

        # 시뮬이 아직 안 시작됐으면 시작
        if enemy_type not in self._sim_threads:
            self._start_background_sim(enemy_type)

        monsters = self._get_cached_monsters(enemy_type)

        if monsters is None:
            # 폴백: Enemy_Class 기준 동적 생성 (수치 출처 단일화)
            return self._make_fallback(enemy_type)

        # 가중치 기반 난이도 선택
        difficulty = self._pick_difficulty()
        self._last_difficulty = difficulty
        enemy_snap, sim_result = monsters[difficulty]

        # AI 시뮬 로그 저장
        self._cache_sim_log(enemy_snap, sim_result, difficulty)

        return enemy_snap

    def _pick_difficulty(self) -> str:
        import random
        pool = []
        for diff, weight in self.DIFFICULTY_RATIO.items():
            pool.extend([diff] * weight)
        return random.choice(pool)

    def _cache_sim_log(self, enemy_snap, sim_result, difficulty):
        """AI 최적 전투 시뮬 1회 → 로그 저장 (복기 비교용)"""
        p_snap = _player_to_snap(self.player, self.item_list)
        engine = BattleEngine(p_snap, enemy_snap)
        result = engine.run(PlayerAI("balanced"), EnemyAI())
        self._last_sim_result = result

        if result.winner == "player":
            try:
                self._lm.save_sim_log(
                    result=result,
                    player_lv=self.player.lv,
                    difficulty=difficulty,
                    win_rate=sim_result.win_rate,
                    monster_stats={
                        "hp": enemy_snap.hp,
                        "stg": enemy_snap.stg,
                        "arm": enemy_snap.arm,
                    },
                )
            except Exception as e:
                if self.verbose:
                    print(f"  [AI] {e}")

    # ── 2. 전투 후: 로그 저장 + 복기 ────────

    def after_battle(self, result: BattleResult):
        """전투 결과 저장 + 패배 시 복기"""
        try:
            self._lm.save_player_log(
                result=result,
                player_lv=self.player.lv,
            )
        except Exception as e:
            pass

        if result.winner == "enemy":
            print("\n" + "─"*40)
            print("  AI 복기 분석을 시작합니다...")
            print("─"*40)
            self._fb.run(
                player_result=result,
                sim_result=self._last_sim_result,
                print_report=True,
            )

    # ── 3. 레벨업 시: 재시뮬레이션 ──────────

    def on_level_up(self):
        """레벨업 → 캐시 초기화 → 백그라운드 재시뮬"""
        if self.verbose:
            print(f"  [AI] 레벨 {self.player.lv} 달성 — 밸런스 재조정 시작")

        # 모니터 재사용을 위해 파이프 파일 초기화
        try:
            os.remove(PIPE_FILE)
        except FileNotFoundError:
            pass
        self._monitor_opened = False  # 다음 시뮬 때 다시 열기

        with self._cache_lock:
            self._monster_cache.clear()
        self._sim_threads.clear()
        self._sim_ready.clear()
        self._last_lv = self.player.lv

        # 즉시 백그라운드 재시뮬 시작
        self._start_background_sim("고블린")
        self._start_background_sim("박쥐")

    def check_level_up(self):
        if self.player.lv != self._last_lv:
            self.on_level_up()

    # ── 4. 자동 전투 ─────────────────────────

    def make_battle_unit(self, snap: EntitySnapshot):
        return _SnapUnit(snap)

    def run_auto_battle(self, enemy_snap, ai_mode="balanced", show_log=True) -> BattleResult:
        p_snap = _player_to_snap(self.player, self.item_list)
        engine = BattleEngine(p_snap, enemy_snap)
        result = engine.run(PlayerAI(ai_mode), EnemyAI())
        if show_log:
            self._print_auto_battle_log(result)
        return result

    def _print_auto_battle_log(self, result: BattleResult):
        print("\n" + "="*45)
        print("  ◆ 자동 전투 로그")
        print("="*45)
        for log in result.logs:
            actor = result.player_name if log.actor == "player" else result.enemy_name
            tag   = (" ★크리!" if log.is_crit else "") + (" (회피)" if log.is_dodge else "")
            if log.action == "attack":
                print(f"  턴{log.turn:>2} [{actor}] 공격 → {log.damage_dealt}의 데미지{tag}")
            elif log.action == "skill":
                print(f"  턴{log.turn:>2} [{actor}] {log.action_detail} 사용 → {log.damage_dealt}의 데미지{tag}")
            elif log.action == "item":
                print(f"  턴{log.turn:>2} [{actor}] {log.action_detail} 사용")
        winner = result.player_name if result.winner == "player" else result.enemy_name
        print(f"\n  결과: {winner} 승리 | 총 {result.total_turns}턴 | 잔여 HP {result.final_player_hp:.0f}")
        print("="*45 + "\n")


class _SnapUnit:
    def __init__(self, snap: EntitySnapshot):
        self.name          = snap.name
        self.lv            = snap.lv
        self.hp            = snap.hp
        self.maxhp         = snap.maxhp
        self.mp            = snap.mp
        self.maxmp         = snap.maxmp
        self.stg           = snap.stg
        self.arm           = snap.arm
        self.sparm         = snap.sparm
        self.sp            = snap.sp
        self.spd           = getattr(snap, 'spd', 10)
        self.luc           = snap.luc
        self.grade         = getattr(snap, 'grade', '중')
        self.is_boss       = getattr(snap, 'is_boss', False)
        self.debuff_resist = getattr(snap, 'debuff_resist', 0.0)

    def exp_reward(self, player_maxexp: int) -> int:
        ratio = {"상": 0.45, "중": 0.34, "하": 0.28}.get(self.grade, 0.34)
        return int(player_maxexp * ratio)