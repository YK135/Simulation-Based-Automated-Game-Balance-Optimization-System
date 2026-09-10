# -*- coding: utf-8 -*-
"""
test_codex_review3.py — 세 번째 Codex 리뷰(보안/진행우회/자원고갈/동시성/
데이터 정합성) 수정 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_codex_review3.py

검증 대상 (Codex가 찾고, 실제 코드 대조 후 수정한 항목들):
  1. DB._masked_db_url()이 DATABASE_URL의 계정/비밀번호를 로그에서
     가리는지 (DB/__init__.py).
  2. /api/map/generate가 전투 중/기존 맵 존재/챕터 2 직접 요청을
     거부하고 최초 챕터 1 시작만 허용하는지 (app/Map.py).
  3. BalanceHook의 백그라운드 시뮬 작업이 무제한 Thread 생성이 아니라
     고정 크기(4) daemon 워커 풀(_SIM_EXECUTOR — _BoundedDaemonPool)에
     제출되는지 — stdlib ThreadPoolExecutor는 non-daemon 스레드라
     프로세스 종료를 붙잡아서 직접 구현했다. 그리고 폐기된 구 탐험 전용
     메서드(_ENEMY_POOL 등)가 제거됐는지 (core/Balance_Hook.py).
  4. _session_last_seen 갱신/정리가 락 없이 서로 다른 스레드에서 dict
     크기를 바꾸지 않는지(_last_seen_guard), _prune_idle_sessions()가
     정리 대상 uid의 _user_locks도 락 안에서 pop하는지 (app/Shared.py).
  5. 패배 시 Run이 "dead"로, 이전 세션을 두고 "새 게임"을 시작하면
     아직 안 끝난 Run이 "abandon"으로 종료 처리되는지 — 단, 이미
     clear/dead로 끝난 Run은 abandon으로 덮어쓰지 않는지
     (app/Battle.py, app/Game.py, app/Map.py).
  6. NodeChoice.battle_result/battle_turns가 전투 시작 시점의 기본값
     None에서, 전투가 실제로 끝난 뒤 채워지는지 (app/Map.py + app/Battle.py).
  7. request.get_json() or {} 패턴을 대체한 _get_json_body()가 dict가
     아닌 JSON(배열/숫자/문자열)도 500 대신 빈 dict로 안전하게 처리하는지
     (app/Shared.py) — 그리고 실제 라우트가 그런 바디를 받아도 500이
     아닌지.
  8. 미사용/중복 코드 제거 확인: game/Lv.py의 GROWTH_RATIO 중복 선언,
     game/Inventory.py의 starting_set/total_count/is_potion_full/
     is_special_full (swap_item은 테스트 커버리지가 있어 유지).

※ 아래 판단은 이번 라운드에서 변경하지 않기로 확정한 항목(참고용, 코드
  변경 없음):
  - 여러 워커로 수평 확장(Codex 발견 #9): Procfile이 --workers 1로
    고정돼 있고 CLAUDE.md/README에 "BattleSession은 메모리 전용이라
    멀티 워커 전에 세션 설계를 다시 봐야 한다"고 이미 명시돼 있다 —
    실제 코드를 --workers>1로 바꾸는 배포 설정 변경이 아닌 한 지금
    당장 고칠 코드가 없다.
  - pending_swaps가 DB 복구(Redis까지 완전히 사라진 뒤 DB로만 복구하는
    극단적 상황)에서 유실되는 문제(Codex 발견 #10): app/Shared.py의
    _snapshot_dict() 주석에 이미 "DB PlayerState엔 전용 컬럼이 없어
    이 필드를 쓰지 않는다"고 트레이드오프로 명시돼 있다 — battle과
    같은 급의 기존 트레이드오프이지 이번에 새로 생긴 문제가 아니다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import threading
from _helpers import make_session_dict, inject_test_session

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


# ─────────────────────────────────────────────
# 1) DB URL 마스킹
# ─────────────────────────────────────────────

def test_db_url_masking():
    print("\n[DB._masked_db_url() — 접속 비밀번호를 로그에 노출하지 않는지]")
    import DB as db_module

    original = db_module.DATABASE_URL
    try:
        db_module.DATABASE_URL = "postgresql://myuser:s3cr3t@host:5432/dbname"
        masked = db_module._masked_db_url()
        check("비밀번호가 마스킹됨", "s3cr3t" not in masked and "***" in masked, f"masked={masked}")
        check("사용자명/호스트/DB명은 유지됨(운영 로그로서 여전히 유용)",
              "myuser" in masked and "host:5432" in masked and "dbname" in masked,
              f"masked={masked}")

        db_module.DATABASE_URL = "sqlite:///ai_rpg.db"
        masked2 = db_module._masked_db_url()
        check("자격증명이 없는 URL은 그대로", masked2 == "sqlite:///ai_rpg.db", f"masked={masked2}")
    finally:
        db_module.DATABASE_URL = original


# ─────────────────────────────────────────────
# 2) /api/map/generate 우회 방지
# ─────────────────────────────────────────────

def test_map_generate_rejects_when_battle_active():
    print("\n[/api/map/generate — 전투 중에는 거부]")
    gs = make_session_dict(gold=100)
    gs["battle"] = object()   # gs.get("battle") 진위만 확인하므로 실제 BattleSession 불필요
    client, uid, store = inject_test_session(gs, uid="test-uid-mapgen-battle")

    r = client.post("/api/map/generate", json={"chapter": 1})
    body = r.get_json()
    check("전투 중엔 400", r.status_code == 400 and body.get("ok") is False, f"body={body}")
    check("맵은 생성되지 않음", store[uid]["map"] is None)
    store.pop(uid, None)


def test_map_generate_rejects_when_map_already_exists():
    print("\n[/api/map/generate — 이미 맵이 있으면 재호출로 덮어쓰기 거부(진행 상황 보호)]")
    gs = make_session_dict(gold=100)
    gs["map"] = {"chapter": 1, "completed": False}   # 진행 중인 맵이 있다고 가정
    client, uid, store = inject_test_session(gs, uid="test-uid-mapgen-existing")

    r = client.post("/api/map/generate", json={"chapter": 1})
    body = r.get_json()
    check("기존 맵이 있으면 400", r.status_code == 400 and body.get("ok") is False, f"body={body}")
    check("기존 맵이 그대로 유지됨(덮어쓰지 않음)",
          store[uid]["map"] == {"chapter": 1, "completed": False})
    store.pop(uid, None)


def test_map_generate_rejects_chapter_2_directly():
    print("\n[/api/map/generate — chapter=2를 직접 요청해도 거부(next_chapter 전용 경로 우회 방지)]")
    gs = make_session_dict(gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-mapgen-ch2")

    r = client.post("/api/map/generate", json={"chapter": 2})
    body = r.get_json()
    check("챕터 2 직접 요청은 400", r.status_code == 400 and body.get("ok") is False, f"body={body}")
    check("맵이 생성되지 않음", store[uid]["map"] is None)
    store.pop(uid, None)


def test_map_generate_first_time_chapter1_still_works():
    print("\n[/api/map/generate — 정상적인 최초 챕터 1 시작은 여전히 동작(회귀 방지)]")
    gs = make_session_dict(gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-mapgen-ok")

    r = client.post("/api/map/generate", json={"chapter": 1})
    body = r.get_json()
    check("최초 챕터 1 생성은 200/ok", r.status_code == 200 and body.get("ok") is True, f"body={body}")
    check("세션에 맵이 저장됨", store[uid]["map"] is not None)
    store.pop(uid, None)


# ─────────────────────────────────────────────
# 3) BalanceHook — 스레드 풀 + 죽은 코드 제거
# ─────────────────────────────────────────────

def test_balance_hook_uses_bounded_thread_pool():
    print("\n[BalanceHook 백그라운드 시뮬 — 무제한 Thread 대신 고정 크기(4) daemon 워커 풀에 제출]")
    from core import Balance_Hook
    from core.Balance_Hook import BalanceHook, _BoundedDaemonPool
    from game.Player_Class import create_player_by_job

    check("_SIM_EXECUTOR가 _BoundedDaemonPool 인스턴스",
          isinstance(Balance_Hook._SIM_EXECUTOR, _BoundedDaemonPool))

    workers = [t for t in threading.enumerate() if t.name.startswith("balance-sim-")]
    check("워커 스레드가 정확히 4개만 떠 있음(프로세스 전체 상한)",
          len(workers) == 4, f"workers={[t.name for t in workers]}")
    check("워커 스레드는 전부 daemon(예전 threading.Thread(daemon=True)와 동일한 종료 성질 유지)",
          all(t.daemon for t in workers), f"daemon flags={[t.daemon for t in workers]}")

    player = create_player_by_job("실행기테스터", "전사")
    hook = BalanceHook(player, [], show_graph=False, verbose=False)
    check("백그라운드 시뮬 작업이 제출되면 멤버십으로 추적됨(고블린/박쥐 2종)",
          set(hook._sim_threads.keys()) == {"고블린", "박쥐"},
          f"keys={list(hook._sim_threads.keys())}")

    # 여러 BalanceHook을 새로 만들어도(= 여러 유저의 "새 게임") 워커 스레드
    # 개수 자체는 4개로 고정되어야 한다 — 예전 세마포어 방식이면 매번 새
    # Thread가 생성돼(daemon=True라 종료는 안 막지만) 개수가 계속 늘어났다.
    for i in range(5):
        create_player_by_job(f"풀테스터{i}", "전사")
        BalanceHook(create_player_by_job(f"풀테스터{i}b", "전사"), [],
                    show_graph=False, verbose=False)
    workers_after = [t for t in threading.enumerate() if t.name.startswith("balance-sim-")]
    check("BalanceHook을 반복 생성해도 워커 스레드 수는 그대로 4개",
          len(workers_after) == 4, f"workers_after={[t.name for t in workers_after]}")


def test_dead_explore_only_methods_removed():
    print("\n[core/Balance_Hook.py — 폐기된 구 탐험 전용 코드 제거 확인]")
    from core.Balance_Hook import BalanceHook
    check("_ENEMY_POOL 제거됨", not hasattr(BalanceHook, "_ENEMY_POOL"))
    check("_available_enemy_types 제거됨", not hasattr(BalanceHook, "_available_enemy_types"))
    check("pick_random_enemy_type 제거됨", not hasattr(BalanceHook, "pick_random_enemy_type"))


# ─────────────────────────────────────────────
# 4) _get_json_body — non-dict JSON 안전 처리
# ─────────────────────────────────────────────

def test_get_json_body_rejects_non_dict():
    print("\n[_get_json_body() — dict가 아닌 JSON은 500 대신 빈 dict로 처리]")
    from app import create_app
    from app.Shared import _get_json_body

    app = create_app()
    cases = [
        (b'[1,2,3]', "배열"),
        (b'42', "숫자"),
        (b'"just a string"', "문자열"),
        (b'null', "null"),
        (b'', "빈 바디"),
    ]
    for body, label in cases:
        with app.test_request_context("/", method="POST", data=body,
                                       content_type="application/json"):
            result = _get_json_body()
            check(f"{label} JSON → 빈 dict", result == {}, f"got={result}")

    with app.test_request_context("/", method="POST", data=b'{"a":1}',
                                   content_type="application/json"):
        result = _get_json_body()
        check("정상 dict는 그대로 통과", result == {"a": 1}, f"got={result}")


def test_route_survives_non_dict_json_body():
    print("\n[실제 라우트가 배열/숫자 JSON 바디를 받아도 500 대신 정상 처리(회귀 방지)]")
    gs = make_session_dict(gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-json-array")

    r = client.post("/api/map/generate", data="[1, 2, 3]", content_type="application/json")
    check("배열 JSON 바디를 보내도 500이 아님(예전엔 .get()에서 AttributeError)",
          r.status_code != 500, f"status={r.status_code}, body={r.get_data(as_text=True)}")
    store.pop(uid, None)


# ─────────────────────────────────────────────
# 5) Run 생명주기 — dead / abandon
# ─────────────────────────────────────────────

def _make_battle(enemy_name="고블린", is_boss=False):
    from ai.battle import EntitySnapshot
    from ai.Battlesession import BattleSession
    from game.Enemy_Class import Make_Goblin
    from game.Inventory import Inventory
    from game.Player_Class import create_player_by_job
    from app.Shared import _player_to_snap

    player = create_player_by_job("전투테스터", "전사")
    inv = Inventory.new()
    player_snap = _player_to_snap(player, inv)
    enemy_unit = Make_Goblin(player.lv, "중")
    enemy_unit.name = enemy_name
    enemy_snap = EntitySnapshot.from_enemy(enemy_unit)

    battle = BattleSession(
        player_snap, enemy=enemy_snap, items=inv.to_flat_list(),
        is_boss=is_boss, enemy_origins=[enemy_unit], player_original=player,
    )
    from core.Balance_Hook import BalanceHook
    hook = BalanceHook(player, inv.to_flat_list(), show_graph=False, verbose=False)
    gs = make_session_dict(player=player, inventory=inv, gold=100)
    gs["hook"] = hook
    return battle, gs


def _make_test_db_user(nickname: str) -> int:
    from DB import get_session as db_session
    from DB.Models import User
    with db_session() as db:
        user = User(auth_type="guest", nickname=nickname, email=None, is_active=True)
        db.add(user)
        db.flush()
        return user.id


def test_defeat_closes_run_as_dead():
    print("\n[패배 시 Run이 'dead'로 종료 처리되는지 (예전엔 winner=='player' 분기 안에서만 호출됐음)]")
    from DB import init_db, get_session as db_session
    from DB.Models import Run
    from app.Map import _create_run
    from app.Battle import _finish_battle

    init_db()
    db_user_id = _make_test_db_user("패배테스터")
    battle, gs = _make_battle()
    gs["db_user_id"] = db_user_id
    _create_run(gs, chapter=1)
    run_id = gs["run_id"]
    check("run_id 발급됨", run_id is not None)

    result = {"player_hp": 0, "player_mp": battle.player.mp, "messages": []}
    _finish_battle(gs, battle, result, "enemy")

    with db_session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        check("Run.result == 'dead'", run is not None and run.result == "dead",
              f"run={run.to_dict() if run else None}")
    check("gs.run_finished == True로 표시됨(중복 종료 방지용)", gs.get("run_finished") is True)


def test_abandon_closes_unfinished_run_on_new_game():
    print("\n[진행 중이던 Run을 두고 '새 게임'을 누르면 abandon으로 종료되는지]")
    from DB import init_db, get_session as db_session
    from DB.Models import Run
    from app.Map import _create_run
    from app import create_app
    from app.Shared import GAME_SESSIONS

    init_db()
    db_user_id = _make_test_db_user("포기테스터")
    gs = make_session_dict(gold=100)
    gs["db_user_id"] = db_user_id
    _create_run(gs, chapter=1)
    run_id = gs["run_id"]
    check("새 런은 run_finished=False로 시작", gs.get("run_finished") is False)

    old_uid = "test-uid-abandon-old"
    GAME_SESSIONS[old_uid] = gs

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = old_uid

    r = client.post("/api/new_game", json={"name": "새캐릭", "job": "전사"})
    body = r.get_json()
    check("새 게임 시작 성공", r.status_code == 200 and body.get("ok") is True, f"body={body}")

    with db_session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        check("이전 미종료 런은 'abandon'으로 닫힘",
              run is not None and run.result == "abandon", f"run={run.to_dict() if run else None}")

    check("이전 uid는 GAME_SESSIONS에서 제거됨", old_uid not in GAME_SESSIONS)

    new_uid = str(body.get("db_user_id"))
    GAME_SESSIONS.pop(new_uid, None)


def test_finished_run_not_overwritten_by_abandon_close():
    print("\n[이미 clear/dead로 끝난 런은 abandon-close가 덮어쓰지 않는지]")
    from DB import init_db, get_session as db_session
    from DB.Models import Run
    from app.Map import _create_run, _finish_run
    from app import create_app
    from app.Shared import GAME_SESSIONS

    init_db()
    db_user_id = _make_test_db_user("완주테스터")
    gs = make_session_dict(gold=100)
    gs["db_user_id"] = db_user_id
    _create_run(gs, chapter=1)
    run_id = gs["run_id"]

    _finish_run(gs, "clear")   # 정상적으로 클리어까지 끝난 런
    check("run_finished 표시됨", gs.get("run_finished") is True)

    old_uid = "test-uid-finished-old"
    GAME_SESSIONS[old_uid] = gs

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = old_uid

    r = client.post("/api/new_game", json={"name": "새캐릭2", "job": "전사"})
    body = r.get_json()
    check("새 게임 시작 성공", r.status_code == 200 and body.get("ok") is True, f"body={body}")

    with db_session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        check("이미 끝난 런의 result가 그대로 'clear' 유지(abandon으로 덮어쓰지 않음)",
              run is not None and run.result == "clear", f"run={run.to_dict() if run else None}")

    new_uid = str(body.get("db_user_id"))
    GAME_SESSIONS.pop(new_uid, None)


# ─────────────────────────────────────────────
# 6) NodeChoice.battle_result/battle_turns 채워짐
# ─────────────────────────────────────────────

def test_node_choice_battle_result_filled_after_battle_ends():
    print("\n[NodeChoice.battle_result/battle_turns가 전투 종료 후 실제 결과로 채워지는지]")
    from DB import init_db, get_session as db_session
    from DB.Models import NodeChoice
    from app.Map import _create_run, _log_node_choice
    from app.Battle import _finish_battle

    init_db()
    db_user_id = _make_test_db_user("노드기록테스터")
    battle, gs = _make_battle()
    gs["db_user_id"] = db_user_id
    _create_run(gs, chapter=1)

    class _FakeNode:
        layer = 3
        node_id = "3_1"
        node_type = "battle"

    node_choice_id = _log_node_choice(gs, _FakeNode())
    check("NodeChoice 행이 생성되고 id가 반환됨", node_choice_id is not None)
    gs["pending_node_choice_id"] = node_choice_id

    with db_session() as db:
        nc = db.query(NodeChoice).filter(NodeChoice.id == node_choice_id).first()
        check("전투 시작 직후엔 battle_result가 비어있음(기존 버그 재현)",
              nc is not None and nc.battle_result is None)

    battle.turn = 7   # 실제로 몇 턴 진행됐다고 가정
    result = {"player_hp": battle.player.hp, "player_mp": battle.player.mp, "messages": []}
    _finish_battle(gs, battle, result, "player")

    with db_session() as db:
        nc = db.query(NodeChoice).filter(NodeChoice.id == node_choice_id).first()
        check("전투 종료 후 battle_result == 'win'으로 채워짐",
              nc is not None and nc.battle_result == "win", f"nc={nc.to_dict() if nc else None}")
        check("battle_turns도 실제 턴 수로 채워짐",
              nc is not None and nc.battle_turns == 7, f"nc={nc.to_dict() if nc else None}")
    check("gs에서 pending_node_choice_id는 소비되어 제거됨",
          "pending_node_choice_id" not in gs)


# ─────────────────────────────────────────────
# 7) 세션 유휴 정리 동시성 (_session_last_seen / _user_locks)
# ─────────────────────────────────────────────

def test_session_last_seen_concurrent_touch_and_prune_no_crash():
    print("\n[_session_last_seen — 동시 touch(신규 키 삽입)와 prune(순회+삭제)가 예외 없이 공존하는지]")
    import time as _time
    import app.Shared as Shared

    orig_last_prune_at = Shared._last_prune_at
    orig_last_seen = dict(Shared._session_last_seen)
    errors = []

    def toucher(i):
        try:
            for j in range(50):
                Shared._touch_session(f"stress-touch-{i}-{j}")
        except Exception as e:
            errors.append(e)

    def pruner():
        try:
            for _ in range(50):
                # time.monotonic()은 프로세스 시작 시점 근처에서 0에 가깝게
                # 시작할 수 있어(macOS 확인됨) 0.0을 넣으면 "방금 정리함"과
                # 구분이 안 될 수 있다 — 확실히 과거로 보이도록 큰 음수 사용.
                Shared._last_prune_at = -1e9   # 매번 주기 게이트를 열어 실제로 스캔하게 함
                Shared._prune_idle_sessions()
        except Exception as e:
            errors.append(e)

    # prune이 실제로 지울 대상이 있도록 오래된 타임스탬프를 미리 채워둠
    cutoff = _time.monotonic() - Shared._SESSION_MAX_IDLE_SECONDS - 10
    for k in range(200):
        Shared._session_last_seen[f"stress-stale-{k}"] = cutoff

    try:
        threads = [threading.Thread(target=toucher, args=(i,)) for i in range(8)]
        threads.append(threading.Thread(target=pruner))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check("동시 touch/prune 중 예외 없음(예전엔 dict 크기 변경 중 순회로 죽을 수 있었음)",
              errors == [], f"errors={errors}")
    finally:
        Shared._session_last_seen.clear()
        Shared._session_last_seen.update(orig_last_seen)
        Shared._last_prune_at = orig_last_prune_at


def test_prune_idle_sessions_also_clears_user_lock():
    print("\n[_prune_idle_sessions() — 정리 대상 uid의 _user_locks도 락 안에서 함께 제거되는지]")
    import time as _time
    import app.Shared as Shared

    orig_last_prune_at = Shared._last_prune_at
    uid = "stress-lock-prune-target"

    try:
        Shared._get_user_lock(uid)   # _user_locks에 등록 (반환값은 등록 여부 확인용으로 불필요)
        check("정리 전엔 락이 존재", uid in Shared._user_locks)

        cutoff = _time.monotonic() - Shared._SESSION_MAX_IDLE_SECONDS - 10
        with Shared._last_seen_guard:
            Shared._session_last_seen[uid] = cutoff
        Shared.GAME_SESSIONS[uid] = make_session_dict(gold=1)

        # time.monotonic() 기준값이 0에 가깝게 시작할 수 있어(macOS 확인됨)
        # 0.0으로는 "이미 방금 정리함" 게이트를 확실히 못 피할 수 있다.
        Shared._last_prune_at = -1e9
        Shared._prune_idle_sessions()

        check("유휴 세션이 GAME_SESSIONS에서 제거됨", uid not in Shared.GAME_SESSIONS)
        check("같은 uid의 _user_locks 항목도 함께 제거됨(경쟁 가능성 차단)",
              uid not in Shared._user_locks)
    finally:
        Shared._last_prune_at = orig_last_prune_at
        Shared.GAME_SESSIONS.pop(uid, None)
        Shared._session_last_seen.pop(uid, None)
        with Shared._user_locks_guard:
            Shared._user_locks.pop(uid, None)


# ─────────────────────────────────────────────
# 8) 죽은/중복 코드 제거 확인
# ─────────────────────────────────────────────

def test_growth_ratio_not_duplicated():
    print("\n[game/Lv.py — GROWTH_RATIO 중복 선언 제거 확인]")
    import inspect
    from game.Lv import LV_

    src = inspect.getsource(LV_)
    check("GROWTH_RATIO 선언이 한 번만 존재", src.count("GROWTH_RATIO = 0.7") == 1,
          f"count={src.count('GROWTH_RATIO = 0.7')}")
    check("값 자체는 그대로 0.7 유지", LV_.GROWTH_RATIO == 0.7)


def test_inventory_dead_methods_removed():
    print("\n[game/Inventory.py — 미사용 메서드 제거 확인(swap_item은 테스트 커버리지가 있어 유지)]")
    from game.Inventory import Inventory
    for name in ("starting_set", "total_count", "is_potion_full", "is_special_full"):
        check(f"Inventory.{name} 제거됨", not hasattr(Inventory, name))
    check("swap_item은 유지됨(TestFile/test_inventory_swap_parity.py가 커버)",
          hasattr(Inventory, "swap_item"))


def main():
    print("=" * 60)
    print(" Codex 3차 리뷰(보안/우회/자원고갈/동시성/정합성) 수정 회귀 테스트")
    print("=" * 60)
    try:
        test_db_url_masking()
        test_map_generate_rejects_when_battle_active()
        test_map_generate_rejects_when_map_already_exists()
        test_map_generate_rejects_chapter_2_directly()
        test_map_generate_first_time_chapter1_still_works()
        test_balance_hook_uses_bounded_thread_pool()
        test_dead_explore_only_methods_removed()
        test_get_json_body_rejects_non_dict()
        test_route_survives_non_dict_json_body()
        test_defeat_closes_run_as_dead()
        test_abandon_closes_unfinished_run_on_new_game()
        test_finished_run_not_overwritten_by_abandon_close()
        test_node_choice_battle_result_filled_after_battle_ends()
        test_session_last_seen_concurrent_touch_and_prune_no_crash()
        test_prune_idle_sessions_also_clears_user_lock()
        test_growth_ratio_not_duplicated()
        test_inventory_dead_methods_removed()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 60)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
