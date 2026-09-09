"""
Balance_Hook.py
─────────────────────────────────────────────
기존 RPG 게임 ↔ AI 엔진 연결 브릿지.

변경사항:
  - 몬스터 생성 백그라운드 스레드 실행 (게임 멈춤 없음)
  - 모니터 통신을 stdin 파이프 → 파일 기반 IPC로 변경 (macOS 호환)
  - 로그 저장 경로 루트 기준으로 수정
"""

import os
import queue
import threading
import subprocess
import platform

from ai.battle  import BattleEngine, EntitySnapshot, BattleResult
from ai.Auto_AI        import PlayerAI, EnemyAI
from ai.Simulator      import MonsterFactory
from ai.LOG_Manager    import LogManager
from ai.FeedBack       import FeedbackEngine
from ai.Visualizer     import Visualizer
from game.Enemy_Class  import (
    Make_Goblin, Make_Bat,
    Make_Slime, Make_Golem, Make_Ghost, Make_Assassin, Make_Priest,
    Make_FireSlime, Make_IceSlime, Make_LightningSlime,
)

# 루트 디렉토리 (Main.py가 있는 곳)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 파일 기반 IPC 경로
PIPE_FILE = "/tmp/ai_monitor_pipe.txt"

class _BoundedDaemonPool:
    """워커 스레드를 고정 개수(daemon=True)만 미리 띄워두고 큐로 작업을
    나눠주는 아주 작은 스레드 풀 — stdlib concurrent.futures.ThreadPoolExecutor
    대신 직접 구현한다.
    ★ ThreadPoolExecutor는 워커 스레드를 non-daemon으로 만든다 — 그 결과
      프로세스가 끝날 때(gunicorn이 워커에 SIGTERM을 보내는 배포 재시작 등)
      concurrent.futures가 등록해 둔 atexit 훅이 큐에 남아있던 작업이 전부
      끝날 때까지 인터프리터 종료 자체를 붙잡는다(라이브러리가 "제출된 작업을
      조용히 버리지 않는다"는 의도로 설계한 동작이지만, 여기선 원치 않는
      부작용이다). 이 모듈은 원래부터 명시적으로 daemon=True 스레드를 써서
      "밸런스 시뮬레이션 때문에 게임 서버 종료가 늦어지는 일은 없다"를
      전제로 하고 있었다(_start_background_sim() 참고) — 그 성질을 그대로
      유지하기 위해 직접 만든다."""

    def __init__(self, max_workers: int):
        self._queue: "queue.Queue" = queue.Queue()
        for i in range(max_workers):
            t = threading.Thread(
                target=self._worker_loop, daemon=True,
                name=f"balance-sim-{i}",
            )
            t.start()

    def _worker_loop(self):
        while True:
            fn = self._queue.get()
            try:
                fn()
            except Exception:
                pass   # 제출되는 콜러블(_run) 자신이 이미 예외를 처리한다

    def submit(self, fn) -> None:
        self._queue.put(fn)


# ★ 프로세스 전체에서 몬스터 밸런스 시뮬레이션에 쓰는 스레드 풀.
#   BalanceHook 인스턴스별이 아니라 워커 프로세스 전체 기준 — 여러 유저가
#   동시에 새 몬스터를 처음 만나거나, 같은 유저가 "새 게임"을 빠르게 반복해도
#   실제로 생성되는 OS 스레드 수 자체가 4를 넘지 않는다.
#   ★ 예전엔 threading.Semaphore(4)로 "동시 실행" 개수만 제한하고 스레드
#     "생성"은 매번 threading.Thread(...).start()로 무제한 허용했다 — 세마포어
#     슬롯이 다 찬 동안에도 요청이 들어올 때마다 새 스레드 객체가 만들어져
#     세마포어 획득 대기 상태로 쌓였다(각 스레드가 실제 OS 스택 메모리를 문
#     상태로). 이 풀은 작업을 "생성"이 아니라 "제출(submit)"하므로, 초과분은
#     스레드가 아니라 큐에 쌓인 가벼운 콜러블로 대기한다.
_SIM_EXECUTOR = _BoundedDaemonPool(max_workers=4)


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
        "고블린":   Make_Goblin,
        "박쥐":     Make_Bat,
        "슬라임":   Make_Slime,
        "화염 슬라임": Make_FireSlime,
        "빙결 슬라임": Make_IceSlime,
        "번개 슬라임": Make_LightningSlime,
        "골렘":     Make_Golem,
        "유령":     Make_Ghost,
        "암살자":   Make_Assassin,
        "사제":     Make_Priest,
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
        # Unit → EntitySnapshot 변환 (Phase 1 신규 필드 보존)
        _snap = EntitySnapshot(
            name=unit.name,
            hp=unit.hp,     maxhp=unit.hp,
            mp=unit.mp,     maxmp=unit.mp,
            stg=unit.stg,   arm=unit.arm,
            sparm=unit.sparm, sp=unit.sp,
            luc=unit.luc,   lv=unit.lv,
            spd=getattr(unit, "spd", 10),
            difficulty="normal",
            # 역할 기반 메커니즘
            physical_resist=getattr(unit, "physical_resist", 1.0),
            magical_resist=getattr(unit, "magical_resist", 1.0),
            dodge_bonus=getattr(unit, "dodge_bonus", 0.0),
            dodge_penalty_per_extra_hit=getattr(unit, "dodge_penalty_per_extra_hit", 0.10),
            first_strike=getattr(unit, "first_strike", False),
            first_attack_bonus=getattr(unit, "first_attack_bonus", 1.0),
            enemy_type=getattr(unit, "enemy_type", unit.name),
            attack_element=getattr(unit, "attack_element", ""),
        )
        # 원소 슬라임: 전투 시작 초기 원소 큐 설정
        _init_q = getattr(unit, "init_element_queue", [])
        if _init_q:
            _snap.element_queue = list(_init_q)
        return _snap

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

        # 백그라운드 시뮬 작업 추적
        self._sim_threads = {}   # {enemy_type: True} — _SIM_EXECUTOR에 제출됐음을 표시(멤버십 전용)
        self._sim_ready   = {}   # {enemy_type: threading.Event}

        # ★ 레벨업(on_level_up)은 _sim_threads/_sim_ready를 비우고 새로 시작만
        #   할 뿐, 이미 돌고 있던 이전 스레드는 취소/join하지 않는다(파이썬
        #   스레드는 강제 종료가 안 됨) — 그 스레드가 나중에 끝나면 이미 지난
        #   레벨 기준으로 생성한 몬스터를 새 캐시에 그대로 덮어쓸 수 있었다.
        #   세대 번호로 막는다: 스레드가 시작될 때 자기 세대를 기억해두고,
        #   완료 시점에 현재 세대와 다르면(그 사이 레벨업이 있었으면) 결과를
        #   버린다.
        self._sim_generation = 0

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
        gen = self._sim_generation   # 이 스레드가 속한 "세대" — 완료 시점에 비교

        def _run():
            try:
                # ★ 프로세스 전체 공유 풀(_SIM_EXECUTOR, max_workers=4)이 동시
                #   실행 개수뿐 아니라 실제 OS 스레드 생성 자체를 제한한다 —
                #   새 게임을 빠르게 반복해도(각자 자기 작업 2개를 제출하는)
                #   초과분은 스레드가 아니라 풀의 내부 큐에 가벼운 콜러블로
                #   쌓인다.
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
                    # ★ 이 스레드가 시작된 뒤 레벨업으로 세대가 바뀌었으면
                    #   (on_level_up이 캐시를 비우고 새 스레드를 이미 띄운
                    #   뒤일 수 있음) 지금 와서 옛 레벨 기준 결과로 캐시를
                    #   덮어쓰지 않는다 — 조용히 버림.
                    if gen == self._sim_generation:
                        self._monster_cache[enemy_type] = monsters
                        self._last_lv = self.player.lv

                # 그래프 저장 (옵션)
                if self._viz and gen == self._sim_generation:
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

        # _sim_threads는 "이 enemy_type 작업이 이미 제출/진행 중인지"만
        # 표시하는 멤버십 집합으로 쓰인다(Thread/Future 객체 자체를 다시
        # join/취소하는 곳이 코드 어디에도 없다) — 그래서 값은 True만으로 충분.
        _SIM_EXECUTOR.submit(_run)
        self._sim_threads[enemy_type] = True

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

    def get_enemy(self, enemy_type: str = "고블린", difficulty: str = None) -> EntitySnapshot:
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
        if difficulty is None:
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
        """전투 결과 저장 + 패배 시 복기.

        ★ 실제 게임 흐름(app/Battle.py의 _finish_battle)에서 패배 시 이 메서드를
          호출하고, 반환된 FeedbackReport를 API 응답에 실어 게임오버 화면에
          보여준다. sim_result(self._last_sim_result)는 get_enemy() 안의
          _cache_sim_log()가 매번 갱신해두므로, 방금 그 전투와 같은 몬스터를
          상대로 한 "AI 최적 플레이" 시뮬레이션과 비교된다.
        """
        # ★ 로컬 파일(JSON+TXT) 저장은 self.verbose(로컬/CLI 사용)일 때만 —
        #   실제 서비스(verbose=False)에서는 이미 app/Shared.py의
        #   _save_rl_log()가 같은 요청 안에서 BattleLog DB 테이블에 이 전투를
        #   저장하고 있어서, 여기서 또 로컬 디스크에 쓰는 건 (1) DB에 이미
        #   있는 걸 중복으로 쓰는 것이고 (2) Render 같은 ephemeral 디스크에서는
        #   다음 재배포 때 사라져서 애초에 아무도 못 읽는 낭비. 굳이 매 패배마다
        #   요청 스레드를 블로킹할 이유가 없다.
        if self.verbose:
            try:
                self._lm.save_player_log(
                    result=result,
                    player_lv=self.player.lv,
                )
            except Exception as e:
                print(f"  [AI] save_player_log 실패: {e}")

        if result.winner != "enemy":
            return None

        return self._fb.run(
            player_result=result,
            sim_result=self._last_sim_result,
            print_report=self.verbose,
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
            # ★ 세대를 올려서 이 시점에 이미 돌고 있던(취소 불가능한) 이전
            #   스레드들이 나중에 끝나도 옛 레벨 결과로 캐시를 못 덮어쓰게 한다.
            self._sim_generation += 1
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
        self.difficulty    = getattr(snap, 'difficulty', '')
        # Phase 1: 역할 기반 메커니즘 — 왕복 변환 시 보존
        self.physical_resist = getattr(snap, 'physical_resist', 1.0)
        self.magical_resist  = getattr(snap, 'magical_resist', 1.0)
        self.dodge_bonus     = getattr(snap, 'dodge_bonus', 0.0)
        self.dodge_penalty_per_extra_hit = getattr(snap, 'dodge_penalty_per_extra_hit', 0.10)
        self.first_strike    = getattr(snap, 'first_strike', False)
        self.first_attack_bonus = getattr(snap, 'first_attack_bonus', 1.0)
        self.has_attacked    = getattr(snap, 'has_attacked', False)
        self.enemy_type      = getattr(snap, 'enemy_type', snap.name)
        # 원소 슬라임 보존 — 왕복 변환(_SnapUnit → from_enemy) 시 큐/공격원소 유지.
        #   이게 없으면 init_element_queue가 유실되어 from_enemy의 이름 fallback에만
        #   의존하게 됨 (근본 보존은 여기서).
        self.attack_element      = getattr(snap, 'attack_element', '')
        self.init_element_queue  = list(getattr(snap, 'element_queue', None)
                                        or getattr(snap, 'init_element_queue', []) or [])

    def exp_reward(self, player_maxexp: int) -> int:
        ratio = {"상": 0.45, "중": 0.34, "하": 0.28}.get(self.grade, 0.34)
        return int(player_maxexp * ratio)