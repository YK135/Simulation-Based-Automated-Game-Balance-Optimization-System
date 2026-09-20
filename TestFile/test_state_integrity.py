# -*- coding: utf-8 -*-
"""
test_state_integrity.py — 세션·런·인벤토리 상태 무결성 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_state_integrity.py

외부 검토 2차에서 나온 문제들을 고정한다. 전부 "서버가 아는 것을
클라이언트 입력으로 대신하지 않는다"(CLAUDE.md)와 "실패를 성공으로
보고하지 않는다"에 해당한다.

  1) /api/map/node/complete 가 전투 노드와 전투 중 상태를 거부하는가
     — 예전엔 보스전이 진행 중인데도 보스 노드를 완료 처리하고
       챕터 클리어(_finish_run "clear")까지 갔다.
  2) /api/inventory/swap 이 add() 실패를 롤백하는가
     — 포션 6개 + 「탐욕의 인장」(용량 5)에서 하나만 버리면 여전히 가득 차
       add가 실패하는데, 예전엔 결과를 안 보고 ok:true + 골드 차감이었다.
  3) 끝난 런(clear/dead)을 abandon으로 덮어쓰지 않는가 (스냅샷 + DB 양쪽)
  4) /api/status 가 대기 중인 교체 티켓을 돌려주는가 (새로고침 복구)
  5) RL 로그의 "선택 가능 행동"이 전투 메뉴와 같은 대상을 보는가
"""
import sys, os, io, contextlib, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DB는 임시 파일로 — 로컬 ai_rpg.db를 건드리지 않는다
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

PASS = FAIL = 0
_buf = io.StringIO()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}  {detail}")


def _client(gs, uid):
    from _helpers import inject_test_session
    with contextlib.redirect_stdout(_buf):
        return inject_test_session(gs, uid=uid)


# ─────────────────────────────────────────────
def test_node_complete_rejects_battle_nodes():
    print("\n[1] /api/map/node/complete — 전투 노드·전투 중 거부")
    from _helpers import make_session_dict
    from game.Map import FloorMap

    with contextlib.redirect_stdout(_buf):
        fmap = FloorMap.generate(1)
    gs = make_session_dict(map=fmap.to_dict(), chapter=1)
    c, uid, store = _client(gs, "test-uid-node-complete")
    try:
        picks = {}
        for nid, nd in gs["map"]["nodes"].items():
            picks.setdefault(nd["node_type"], nid)

        for kind in ("battle", "elite", "boss"):
            if kind not in picks:
                continue
            gs["pending_node_id"] = picks[kind]
            gs["battle"] = None
            body = c.post("/api/map/node/complete", json={}).get_json()
            check(f"{kind} 노드 → battle_node 거부",
                  body.get("reason") == "battle_node", f"body={body}")

        # 전투 중이면 노드 타입과 무관하게 거부
        gs["pending_node_id"] = picks.get("rest") or next(iter(gs["map"]["nodes"]))
        gs["battle"] = object()
        body = c.post("/api/map/node/complete", json={}).get_json()
        check("전투 중 → battle_in_progress 거부",
              body.get("reason") == "battle_in_progress", f"body={body}")
        gs["battle"] = None
    finally:
        store.pop(uid, None)


def test_swap_rollback_when_still_full():
    print("\n[2] /api/inventory/swap — add() 실패 시 전부 되돌린다")
    from _helpers import make_session_dict
    from game.Inventory import Inventory
    from app.Shared import _register_pending_swap
    from ai.battle.Relics import relic_potion_slot_penalty

    inv = Inventory.new()
    inv.potion_penalty = relic_potion_slot_penalty(["greed_seal"])   # 탐욕의 인장 → 용량 5
    inv.potions = ["HP_S_potion"] * 6                                # 유물 전에 이미 6개
    check("전제: 용량 5인데 6개 보유", inv.potion_capacity() == 5 and len(inv.potions) == 6,
          f"cap={inv.potion_capacity()} used={len(inv.potions)}")

    gs = make_session_dict(inventory=inv, gold=100, pending_swaps=[])
    c, uid, store = _client(gs, "test-uid-swap-rollback")
    try:
        tid = _register_pending_swap(gs, "HP_M_potion", "shop", price=20)

        r = c.post("/api/inventory/swap", json={"ticket_id": tid, "drops": {"HP_S_potion": 1}})
        body = r.get_json()
        check("1개만 버리면 400", r.status_code == 400, f"code={r.status_code}")
        check("need_more=2로 몇 개가 더 필요한지 알려준다", body.get("need_more") == 2, f"body={body}")
        check("골드가 차감되지 않았다", gs["gold"] == 100, f"gold={gs['gold']}")
        check("버린 포션이 되돌아왔다", len(gs["inventory"].potions) == 6,
              f"potions={len(gs['inventory'].potions)}")
        check("티켓이 살아 있다 (같은 id로 재시도 가능)",
              any(t["ticket_id"] == tid for t in gs["pending_swaps"]), f"swaps={gs['pending_swaps']}")
        check("용량 패널티가 유지된다", gs["inventory"].potion_capacity() == 5,
              f"cap={gs['inventory'].potion_capacity()}")

        r2 = c.post("/api/inventory/swap", json={"ticket_id": tid, "drops": {"HP_S_potion": 2}})
        check("2개 버리면 성공", r2.status_code == 200 and r2.get_json().get("ok") is True,
              f"code={r2.status_code} body={r2.get_json()}")
        check("이번엔 골드가 결제된다", gs["gold"] == 80, f"gold={gs['gold']}")
        check("새 포션이 실제로 들어왔다", "HP_M_potion" in gs["inventory"].potions,
              f"potions={gs['inventory'].potions}")
    finally:
        store.pop(uid, None)


def test_finished_run_not_overwritten():
    print("\n[3] 끝난 런을 abandon으로 덮어쓰지 않는다")
    from _helpers import make_session_dict
    from app.Shared import _snapshot_dict, _gs_from_snapshot
    from app.Map import _create_run, _finish_run
    from DB import get_session as db_session, init_db
    from DB.Models import Run, User

    with contextlib.redirect_stdout(_buf):
        init_db()
        with db_session() as s:
            u = User(nickname="런무결성", auth_type="guest"); s.add(u); s.flush(); db_uid = u.id

    gs = make_session_dict(db_user_id=db_uid, chapter=1, map_turn=5)
    with contextlib.redirect_stdout(_buf):
        _create_run(gs, 1)
        _finish_run(gs, "clear")
    check("클리어 직후 run_finished=True", gs.get("run_finished") is True, f"gs={gs.get('run_finished')}")

    snap = _snapshot_dict(gs)
    check("스냅샷에 run_finished가 실린다", snap.get("run_finished") is True, f"snap={snap.get('run_finished')}")
    with contextlib.redirect_stdout(_buf):
        gs2 = _gs_from_snapshot(str(db_uid), snap)
    check("복구 후에도 True", gs2.get("run_finished") is True, f"gs2={gs2.get('run_finished')}")

    # 표시를 잃어버린 최악의 경우에도 DB가 막는다
    gs3 = {**gs, "run_finished": False}
    with contextlib.redirect_stdout(_buf):
        _finish_run(gs3, "abandon")
    with db_session() as s:
        row = s.query(Run).filter(Run.id == gs["run_id"]).first()
        check("DB result가 clear로 유지된다", row is not None and row.result == "clear",
              f"result={getattr(row, 'result', None)}")
        check("boss_cleared도 유지된다", row is not None and bool(row.boss_cleared) is True,
              f"boss_cleared={getattr(row, 'boss_cleared', None)}")
    check("gs의 종료 표시도 복구된다", gs3.get("run_finished") is True, f"gs3={gs3.get('run_finished')}")


def test_status_returns_pending_swap():
    print("\n[4] /api/status — 대기 중인 교체 티켓을 돌려준다 (새로고침 복구)")
    from _helpers import make_session_dict
    from game.Inventory import Inventory
    from app.Shared import _register_pending_swap

    inv = Inventory.new()
    for _ in range(6):
        inv.add("HP_S_potion")
    gs = make_session_dict(inventory=inv, pending_swaps=[])
    c, uid, store = _client(gs, "test-uid-status-swap")
    try:
        body = c.get("/api/status").get_json()
        check("티켓이 없으면 필드도 없다", not body.get("inventory_overflow"), f"body={body.get('inventory_overflow')}")

        tid = _register_pending_swap(gs, "HP_M_potion", "battle")
        body = c.get("/api/status").get_json()
        ov = body.get("inventory_overflow") or []
        check("티켓 1건이 내려온다", len(ov) == 1, f"ov={ov}")
        if ov:
            check("ticket_id가 서버 발급 값과 같다", ov[0]["ticket_id"] == tid, f"ov={ov[0]}")
            check("item이 실린다", ov[0]["item"] == "HP_M_potion", f"ov={ov[0]}")
            check("candidates를 현재 인벤토리에서 다시 계산한다",
                  len(ov[0]["candidates"]) == 6, f"candidates={ov[0]['candidates']}")
    finally:
        store.pop(uid, None)


def test_rl_available_uses_action_target():
    print("\n[5] RL 로그의 선택 가능 행동이 '겨눈 대상'을 본다")
    import random
    from game.Enemy_Class import Make_Goblin
    from ai.battle import EntitySnapshot, StatusEffect
    from ai.Battlesession import BattleSession
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from montecarlo import build_player, player_snap

    random.seed(20260919)
    with contextlib.redirect_stdout(_buf):
        p = build_player("도적", 20)
        enemies = [EntitySnapshot.from_enemy(Make_Goblin(18, "중")) for _ in range(2)]
        bs = BattleSession(player_snap(p, ["HP_M_potion"]), enemies=enemies, items=["HP_M_potion"])

    if "피의 수확" not in (bs.player.learned_skills or []):
        check("전제: 도적 Lv20이 피의 수확을 배운다", False,
              f"skills={bs.player.learned_skills}")
        return

    # 2번 적에게만 출혈
    bs.enemies[1].apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=2))

    bs._target_idx = 1
    menu = {s["name"]: s["usable"] for s in bs.get_skills()}
    with contextlib.redirect_stdout(_buf):
        pre = bs._rl_pre("skill:피의 수확:1")
    check("출혈 대상을 겨누면 메뉴가 사용 가능으로 본다", menu.get("피의 수확") is True, f"menu={menu.get('피의 수확')}")
    check("로그도 available에 넣는다",
          any("피의 수확" in a for a in pre["action"]["available"]), f"available={pre['action']['available']}")
    check("blocked에 없다", "피의 수확" not in pre["action"]["blocked"], f"blocked={pre['action']['blocked']}")

    bs._target_idx = 0
    with contextlib.redirect_stdout(_buf):
        pre0 = bs._rl_pre("skill:피의 수확:0")
    check("출혈 없는 대상을 겨누면 no_bleed로 기록된다",
          pre0["action"]["blocked"].get("피의 수확") == "no_bleed", f"blocked={pre0['action']['blocked']}")


def main():
    print("=" * 52)
    print(" 세션 · 런 · 인벤토리 상태 무결성 회귀 테스트")
    print("=" * 52)
    try:
        test_node_complete_rejects_battle_nodes()
        test_swap_rollback_when_still_full()
        test_finished_run_not_overwritten()
        test_status_returns_pending_swap()
        test_rl_available_uses_action_target()
    except Exception as ex:
        import traceback; traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    finally:
        try:
            os.unlink(_db)
        except OSError:
            pass
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
