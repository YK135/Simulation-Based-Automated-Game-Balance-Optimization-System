"""
Balance_Hook.py
─────────────────────────────────────────────
기존 RPG 게임 ↔ AI 엔진 연결 브릿지.

변경사항:
  - 몬스터 생성 백그라운드 스레드 실행 (게임 멈춤 없음)
  - 로그 저장 경로 루트 기준으로 수정
"""

import copy
import sys
import os
import threading

from ai.Battle_Engine import BattleEngine, EntitySnapshot, BattleResult, TurnLog
from ai.Auto_AI       import PlayerAI, EnemyAI
from ai.Simulator     import MonsterFactory, BattleSimulator, BASE_ENEMIES
from ai.LOG_Manager   import LogManager
from ai.FeedBack      import FeedbackEngine
from ai.Visualizer    import Visualizer

# 루트 디렉토리 (Main.py가 있는 곳)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        learned_skills=skills,
        items=list(item_list),
    )


class BalanceHook:
    """
    게임 ↔ AI 엔진 브릿지.
    몬스터 시뮬레이션은 백그라운드 스레드에서 실행된다.
    """

    DIFFICULTY_RATIO = {"hard": 2, "normal": 5, "easy": 3}

    # 기본 몬스터 (시뮬레이션 완료 전 폴백용)
    FALLBACK_ENEMIES = {
        "고블린": EntitySnapshot(
            name="고블린", hp=75, maxhp=75, mp=0, maxmp=0,
            stg=2, arm=6, sparm=0, sp=0, luc=5, lv=1,
        ),
        "박쥐": EntitySnapshot(
            name="박쥐", hp=15, maxhp=15, mp=0, maxmp=0,
            stg=5, arm=5, sparm=0, sp=0, luc=0, lv=1,
        ),
    }

    def __init__(self, player, item_list, show_graph=False, verbose=True):
        self.player     = player
        self.item_list  = item_list
        self.show_graph = show_graph
        self.verbose    = verbose

        self._lm  = LogManager()
        self._fb  = FeedbackEngine(use_llm=False)
        self._viz = Visualizer(save_dir=os.path.join(ROOT_DIR, "graphs")) if show_graph else None

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

    # ── 백그라운드 시뮬레이션 ────────────────

    def _start_background_sim(self, enemy_type: str):
        """백그라운드 스레드에서 시뮬레이션 시작"""
        if enemy_type in self._sim_threads:
            return  # 이미 실행 중

        event = threading.Event()
        self._sim_ready[enemy_type] = event

        def _run():
            try:
                if self.verbose:
                    print(f"  [AI] {enemy_type} 밸런스 분석 시작 (백그라운드)...")
                p_snap   = _player_to_snap(self.player, self.item_list)
                factory  = MonsterFactory(p_snap, enemy_type)
                monsters = factory.generate_all(verbose=self.verbose)

                with self._cache_lock:
                    self._monster_cache[enemy_type] = monsters
                    self._last_lv = self.player.lv

                if self.verbose:
                    print(f"  [AI] {enemy_type} 밸런스 분석 완료!")

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
            finally:
                event.set()  # 완료 신호

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
            # 폴백: 기본 스탯 몬스터
            fallback = self.FALLBACK_ENEMIES.get(
                enemy_type,
                self.FALLBACK_ENEMIES["고블린"]
            )
            if self.verbose:
                print(f"  [AI] 분석 중... 기본 {enemy_type} 등장")
            return fallback

        # 가중치 기반 난이도 선택
        difficulty = self._pick_difficulty()
        self._last_difficulty = difficulty
        enemy_snap, sim_result = monsters[difficulty]

        # AI 시뮬 로그 저장
        self._cache_sim_log(enemy_snap, sim_result, difficulty)

        label = {"hard": "강한", "normal": "보통", "easy": "약한"}
        if self.verbose:
            print(f"\n  [AI 밸런싱] {label[difficulty]} {enemy_snap.name} 등장")
            print(f"  예상 승률: {sim_result.win_rate*100:.1f}% "
                  f"| HP {enemy_snap.hp:.0f} | STG {enemy_snap.stg:.1f}\n")

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
                if self.verbose:
                    print(f"  [LOG] 시뮬레이션 로그 저장 완료")
            except Exception as e:
                if self.verbose:
                    print(f"  [LOG] 시뮬 로그 저장 실패: {e}")

    # ── 2. 전투 후: 로그 저장 + 복기 ────────

    def after_battle(self, result: BattleResult):
        """전투 결과 저장 + 패배 시 복기"""
        try:
            self._lm.save_player_log(
                result=result,
                player_lv=self.player.lv,
            )
            if self.verbose:
                print(f"  [LOG] 플레이어 전투 로그 저장 완료")
        except Exception as e:
            if self.verbose:
                print(f"  [LOG] 플레이어 로그 저장 실패: {e}")

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
            print(f"\n  [AI] 레벨 {self.player.lv} 달성 — 밸런스 재조정 시작\n")

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
        self.name=snap.name; self.lv=snap.lv
        self.hp=snap.hp;     self.maxhp=snap.maxhp
        self.mp=snap.mp;     self.stg=snap.stg
        self.arm=snap.arm;   self.sparm=snap.sparm
        self.sp=snap.sp;     self.spd=5
        self.luc=snap.luc