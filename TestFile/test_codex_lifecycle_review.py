# -*- coding: utf-8 -*-
"""
test_codex_lifecycle_review.py — Codex 생명주기/상태검증 리뷰 수정 잠금용
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_codex_lifecycle_review.py

검증 대상 (Codex가 찾고, 실제 코드 대조 후 수정한 항목들):
  1. /api/rest가 "현재 휴식 노드인지"를 확인하지 않아 브라우저 콘솔/직접
     HTTP 요청으로 {"choice":"train"}을 반복 전송하면 경험치를 무한정
     얻을 수 있었음 (app/Rest.py).
  2. /api/map/node/complete가 클라이언트가 보낸 node_id를 서버의
     pending_node_id보다 우선 신뢰해서, 임의 노드(보스 포함)를 완료
     처리할 수 있었음 (app/Map.py).
  3. FloorMap.mark_visited()가 node.available을 확인하지 않아, 선택
     가능하지 않은 노드도 완료 처리할 수 있었음 (game/Map.py).
  4. /api/map/next_chapter가 현재 챕터 클리어 여부를 확인하지 않아
     한 노드도 안 밟고 다음 챕터로 건너뛸 수 있었음 (app/Map.py).
  5. /api/inventory/swap이 new(획득 아이템)를 검증 없이 그대로 인벤토리에
     추가해서, 서버가 실제로 발급한 적 없는 아이템을 얻을 수 있었고,
     상점 구매 경로는 결제 없이 아이템을 얻을 수도 있었음
     (app/Inventory.py + app/Shared.py의 pending_swaps 티켓).
  6. GAME_SESSIONS[uid]가 여러 스레드(--threads 8) 사이에 아무 잠금 없이
     공유돼 동시 요청 시 상태가 경쟁할 수 있었음 (app/Shared.py 사용자별
     락 + app/__init__.py의 before_request/teardown_request).
  7. Balance_Hook의 레벨업 시 백그라운드 시뮬 스레드 세대 관리 부재
     (core/Balance_Hook.py의 _sim_generation).
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
# 테스트용 최소 맵 (Node.to_dict()/from_dict()와 동일한 필드 형태)
# ─────────────────────────────────────────────

def _node(node_id, node_type, layer, branch="left", available=False,
          visited=False, next_ids=None):
    return {
        "node_id": node_id, "chapter": 1, "layer": layer, "branch": branch,
        "index": 0, "node_type": node_type, "next_ids": next_ids or [],
        "visited": visited, "available": available, "on_path": False,
        "x_offset": 0, "x_pos": 0,
    }


def _minimal_map(rest_available=True, completed=False):
    return {
        "chapter": 1, "current_layer": 0, "player_branch": "left",
        "completed": completed,
        "nodes": {
            "start": _node("start", "event", 0, branch="start", visited=True,
                            next_ids=["rest1"]),
            "rest1": _node("rest1", "rest", 1, available=rest_available,
                            next_ids=["boss1"]),
            "boss1": _node("boss1", "boss", 15, branch="boss",
                            available=False, next_ids=[]),
        },
    }


def _rest_client(gold=100):
    # /api/rest의 "train" 분기가 gs["hook"].check_level_up()을 호출하므로
    # (다른 hook 필요없는 테스트와 달리) 진짜 BalanceHook이 있어야 한다 —
    # 생성자는 백그라운드 스레드를 non-blocking으로 띄우기만 하므로 빠르다.
    from core.Balance_Hook import BalanceHook

    gs = make_session_dict(gold=gold)
    gs["hook"] = BalanceHook(gs["player"], gs["items"], show_graph=False, verbose=False)
    gs["map"] = _minimal_map(rest_available=True)
    gs["pending_node_id"] = "rest1"
    return inject_test_session(gs, uid="test-uid-rest")


# ─────────────────────────────────────────────
# 1) /api/rest — 휴식 노드 검증 + 1회 한정
# ─────────────────────────────────────────────

def test_rest_blocked_when_not_on_rest_node():
    print("\n[휴식 노드가 아닐 때 /api/rest 차단]")
    gs = make_session_dict(gold=100)
    gs["map"] = _minimal_map(rest_available=True)
    gs["pending_node_id"] = None   # 휴식 노드에 있지 않음
    client, uid, store = inject_test_session(gs, uid="test-uid-rest-blocked")

    r = client.post("/api/rest", json={"choice": "train"})
    body = r.get_json()
    check("휴식 노드 아니면 400", r.status_code == 400 and body.get("ok") is False,
          f"body={body}")
    check("reason=not_rest_node", body.get("reason") == "not_rest_node", f"body={body}")
    store.pop(uid, None)


def test_rest_repeated_call_blocked_before_complete():
    print("\n[같은 휴식 노드에서 /api/rest 반복 호출 → 두 번째부터 차단]")
    client, uid, store = _rest_client(gold=100)
    player_before = store[uid]["player"]
    exp_before = player_before.exp

    r1 = client.post("/api/rest", json={"choice": "train"})
    b1 = r1.get_json()
    check("첫 호출 성공", r1.status_code == 200 and b1.get("ok") is True, f"body={b1}")
    check("경험치 증가", store[uid]["player"].exp > exp_before or store[uid]["player"].lv > player_before.lv)

    r2 = client.post("/api/rest", json={"choice": "train"})
    b2 = r2.get_json()
    check("완료 처리(/map/node/complete) 전 재호출은 차단",
          r2.status_code == 400 and b2.get("ok") is False, f"body={b2}")
    check("reason=rest_already_used", b2.get("reason") == "rest_already_used", f"body={b2}")
    store.pop(uid, None)


def test_concurrent_rest_calls_grant_exp_exactly_once():
    print("\n[동시 다발 /api/rest 요청 — 사용자별 락으로 정확히 1번만 성공]")
    client, uid, store = _rest_client(gold=100)

    N = 10
    results = []
    results_lock = threading.Lock()

    def worker():
        r = client.post("/api/rest", json={"choice": "train"})
        with results_lock:
            results.append(r.get_json())

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = sum(1 for b in results if b.get("ok"))
    check(f"{N}개 동시 요청 중 정확히 1개만 성공 (사용자별 락 직렬화)",
          ok_count == 1, f"ok_count={ok_count}, results={results}")
    store.pop(uid, None)


# ─────────────────────────────────────────────
# 2)+3) /api/map/node/complete — 서버 pending_node_id만 신뢰
# ─────────────────────────────────────────────

def test_node_complete_ignores_client_supplied_node_id():
    print("\n[/api/map/node/complete — 클라이언트가 보낸 node_id는 무시하고 서버 pending만 사용]")
    gs = make_session_dict(gold=100)
    gs["map"] = _minimal_map(rest_available=True)
    gs["pending_node_id"] = "rest1"   # 서버가 실제로 진입을 검증해 기록한 값
    client, uid, store = inject_test_session(gs, uid="test-uid-complete")

    # 공격자가 보스 노드를 대신 완료 처리하려고 시도
    r = client.post("/api/map/node/complete", json={"node_id": "boss1"})
    body = r.get_json()
    check("요청 자체는 200/ok (서버가 자기 pending을 처리)",
          r.status_code == 200 and body.get("ok") is True, f"body={body}")

    updated_map = store[uid]["map"]
    check("실제로는 rest1(서버 pending)만 완료 처리됨",
          updated_map["nodes"]["rest1"]["visited"] is True, f"map={updated_map}")
    check("클라이언트가 지정한 boss1은 건드리지 않음(조기 클리어 불가)",
          updated_map["nodes"]["boss1"]["visited"] is False, f"map={updated_map}")
    check("보스를 안 거쳤으므로 맵이 완료 처리되지 않음",
          updated_map["completed"] is False, f"map={updated_map}")
    store.pop(uid, None)


def test_node_complete_without_pending_id_rejected():
    print("\n[대기 중인 노드가 없을 때 /api/map/node/complete 거부]")
    gs = make_session_dict(gold=100)
    gs["map"] = _minimal_map(rest_available=True)
    gs["pending_node_id"] = None
    client, uid, store = inject_test_session(gs, uid="test-uid-complete-none")

    r = client.post("/api/map/node/complete", json={"node_id": "boss1"})
    body = r.get_json()
    check("완료할 노드 없음 → 400", r.status_code == 400 and body.get("ok") is False,
          f"body={body}")
    store.pop(uid, None)


def test_mark_visited_rejects_unavailable_node():
    print("\n[FloorMap.mark_visited() — available 아닌 노드는 거부 (game/Map.py 단위 테스트)]")
    from game.Map import FloorMap

    fmap = FloorMap.from_dict(_minimal_map(rest_available=False))
    result = fmap.mark_visited("boss1")   # available=False인 보스 노드를 바로 완료 시도
    check("available=False 노드는 처리 안 함(False 반환)", result is False, f"result={result}")
    check("실제로 visited 상태가 안 바뀜", fmap.nodes["boss1"].visited is False)

    ok_fmap = FloorMap.from_dict(_minimal_map(rest_available=True))
    ok_result = ok_fmap.mark_visited("rest1")
    check("available=True 노드는 정상 처리(True 반환)", ok_result is True, f"result={ok_result}")
    check("이미 처리된 노드 재호출은 다시 False", ok_fmap.mark_visited("rest1") is False)


# ─────────────────────────────────────────────
# 4) /api/map/next_chapter — 클리어 여부 확인
# ─────────────────────────────────────────────

def test_next_chapter_blocked_before_clear():
    print("\n[챕터를 클리어하지 않고 /api/map/next_chapter 직접 호출 → 차단]")
    gs = make_session_dict(gold=100)
    gs["chapter"] = 1
    gs["map"] = _minimal_map(completed=False)
    client, uid, store = inject_test_session(gs, uid="test-uid-nextch-blocked")

    r = client.post("/api/map/next_chapter", json={})
    body = r.get_json()
    check("클리어 전엔 400", r.status_code == 400 and body.get("ok") is False, f"body={body}")
    check("챕터가 그대로 1로 유지됨", store[uid]["chapter"] == 1)
    store.pop(uid, None)


def test_next_chapter_allowed_after_clear():
    print("\n[챕터 클리어 후 /api/map/next_chapter 정상 진행 (회귀 방지)]")
    gs = make_session_dict(gold=100)
    gs["chapter"] = 1
    gs["map"] = _minimal_map(completed=True)
    client, uid, store = inject_test_session(gs, uid="test-uid-nextch-ok")

    r = client.post("/api/map/next_chapter", json={})
    body = r.get_json()
    check("클리어 후엔 200/ok", r.status_code == 200 and body.get("ok") is True, f"body={body}")
    check("챕터 2로 진행", store[uid]["chapter"] == 2, f"chapter={store[uid].get('chapter')}")
    store.pop(uid, None)


# ─────────────────────────────────────────────
# 5) /api/inventory/swap — pending_swaps 티켓 검증
# ─────────────────────────────────────────────

def test_inventory_swap_rejects_unregistered_item():
    print("\n[서버가 발급한 적 없는 아이템으로 /api/inventory/swap 시도 → 거부]")
    from game.Inventory import Inventory

    inv = Inventory.new()
    inv.potions = ["HP_S_potion"] * 6   # 포션 슬롯 가득
    gs = make_session_dict(inventory=inv, gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-swap-fake")

    r = client.post("/api/inventory/swap", json={"drop": "HP_S_potion", "new": "완전_조작된_아이템"})
    body = r.get_json()
    check("등록된 적 없는 아이템 → 400", r.status_code == 400 and body.get("ok") is False,
          f"body={body}")
    check("reason=no_pending_swap", body.get("reason") == "no_pending_swap", f"body={body}")
    check("인벤토리는 그대로", store[uid]["inventory"].potions.count("HP_S_potion") == 6)
    store.pop(uid, None)


def test_inventory_swap_shop_ticket_charges_gold():
    print("\n[상점발 대기 티켓 스왑 확정 시 결제 (예전엔 무료 획득 가능했음)]")
    from game.Inventory import Inventory
    from app.Shared import _register_pending_swap

    inv = Inventory.new()
    inv.potions = ["HP_S_potion"] * 6
    gs = make_session_dict(inventory=inv, gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-swap-shop")

    _register_pending_swap(store[uid], "HP_M_potion", source="shop", price=50)

    r = client.post("/api/inventory/swap", json={"drop": "HP_S_potion", "new": "HP_M_potion"})
    body = r.get_json()
    check("정상 스왑 성공", r.status_code == 200 and body.get("ok") is True, f"body={body}")
    check("결제됨 (100 - 50 = 50G)", body.get("gold") == 50, f"body={body}")
    check("인벤토리에 새 아이템 반영됨",
          store[uid]["inventory"].has("HP_M_potion") and
          store[uid]["inventory"].potions.count("HP_S_potion") == 5)
    check("티켓은 1회 소모되어 재사용 불가", store[uid].get("pending_swaps", []) == [])

    # 같은 티켓으로 재시도 — 이미 소모됨
    r2 = client.post("/api/inventory/swap", json={"drop": "HP_S_potion", "new": "HP_M_potion"})
    check("소모된 티켓 재사용 시도는 거부", r2.get_json().get("ok") is False)
    store.pop(uid, None)


def test_inventory_swap_insufficient_gold_restores_ticket():
    print("\n[골드 부족 시 결제 실패 → 티켓은 되돌려놔서 나중에 재시도 가능]")
    from game.Inventory import Inventory
    from app.Shared import _register_pending_swap

    inv = Inventory.new()
    inv.potions = ["HP_S_potion"] * 6
    gs = make_session_dict(inventory=inv, gold=10)
    client, uid, store = inject_test_session(gs, uid="test-uid-swap-poor")

    _register_pending_swap(store[uid], "HP_L_potion", source="shop", price=80)

    r = client.post("/api/inventory/swap", json={"drop": "HP_S_potion", "new": "HP_L_potion"})
    body = r.get_json()
    check("골드 부족 → 400", r.status_code == 400 and body.get("ok") is False, f"body={body}")
    check("골드 차감 안 됨", store[uid]["gold"] == 10)
    pending = store[uid].get("pending_swaps", [])
    check("티켓은 소모되지 않고 남아있음(나중에 골드 채워서 재시도 가능)",
          any(p["item"] == "HP_L_potion" for p in pending), f"pending={pending}")
    store.pop(uid, None)


def test_inventory_swap_reward_ticket_no_charge():
    print("\n[전투 보상발 대기 티켓은 결제 없이 스왑 (이미 획득한 보상)]")
    from game.Inventory import Inventory
    from app.Shared import _register_pending_swap

    inv = Inventory.new()
    inv.special = ["bomb", "web_bomb", "focus_drug"]   # 특수 슬롯 가득(3)
    gs = make_session_dict(inventory=inv, gold=100)
    client, uid, store = inject_test_session(gs, uid="test-uid-swap-reward")

    _register_pending_swap(store[uid], "haste_drug", source="reward")   # price=0

    r = client.post("/api/inventory/swap", json={"drop": "bomb", "new": "haste_drug"})
    body = r.get_json()
    check("결제 없이 스왑 성공", r.status_code == 200 and body.get("ok") is True, f"body={body}")
    check("골드 그대로 100G", store[uid]["gold"] == 100)
    store.pop(uid, None)


# ─────────────────────────────────────────────
# 6) 사용자별 락 레지스트리
# ─────────────────────────────────────────────

def test_user_lock_registry_identity():
    print("\n[사용자별 락 — 같은 uid는 같은 락, 다른 uid는 다른 락]")
    from app.Shared import _get_user_lock

    l1 = _get_user_lock("lock-test-uid-a")
    l2 = _get_user_lock("lock-test-uid-a")
    l3 = _get_user_lock("lock-test-uid-b")
    check("같은 uid → 동일 락 객체", l1 is l2)
    check("다른 uid → 별개 락 객체", l1 is not l3)


# ─────────────────────────────────────────────
# 7) BalanceHook 세대(generation) 카운터
# ─────────────────────────────────────────────

def test_balance_hook_generation_counter():
    print("\n[BalanceHook — on_level_up()마다 _sim_generation 증가 (스레드 세대 관리)]")
    from core.Balance_Hook import BalanceHook
    from game.Player_Class import create_player_by_job

    player = create_player_by_job("세대테스터", "전사")
    hook = BalanceHook(player, [], show_graph=False, verbose=False)

    gen0 = hook._sim_generation
    check("초기 세대 == 0", gen0 == 0, f"gen0={gen0}")

    hook.on_level_up()
    check("레벨업 1회 후 세대 +1", hook._sim_generation == gen0 + 1,
          f"gen={hook._sim_generation}")

    hook.on_level_up()
    hook.on_level_up()
    check("반복 레벨업마다 계속 증가", hook._sim_generation == gen0 + 3,
          f"gen={hook._sim_generation}")


def main():
    print("=" * 56)
    print(" Codex 생명주기/상태검증 리뷰 수정 회귀 테스트")
    print("=" * 56)
    try:
        test_rest_blocked_when_not_on_rest_node()
        test_rest_repeated_call_blocked_before_complete()
        test_concurrent_rest_calls_grant_exp_exactly_once()
        test_node_complete_ignores_client_supplied_node_id()
        test_node_complete_without_pending_id_rejected()
        test_mark_visited_rejects_unavailable_node()
        test_next_chapter_blocked_before_clear()
        test_next_chapter_allowed_after_clear()
        test_inventory_swap_rejects_unregistered_item()
        test_inventory_swap_shop_ticket_charges_gold()
        test_inventory_swap_insufficient_gold_restores_ticket()
        test_inventory_swap_reward_ticket_no_charge()
        test_user_lock_registry_identity()
        test_balance_hook_generation_counter()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
