# -*- coding: utf-8 -*-
"""
test_shop_buy_price_authority.py — /api/shop/buy 클라이언트 price 신뢰 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_shop_buy_price_authority.py

검증 대상 (전체 코드베이스 보안 리뷰에서 발견·수정된 취약점 잠금용):
  app/Map.py의 shop_buy()가 요청 바디의 "price" 필드를 그대로 믿고
  gs["gold"] -= price를 계산했음. {"price": 0}이나 음수 price를 보내면
  무료 구매 또는 골드 무한 생성이 가능했음.

  수정: price는 요청에서 받지 않고, 항상 _get_shop_items(player.lv)의
  서버 측 가격표에서 item_id로 조회한다. 카탈로그에 없는 item_id는 거부.

방식:
  실제 Flask test_client + 실제 GAME_SESSIONS 세션으로 /api/shop/buy 호출.
  1) price=0으로 조작 → 서버가 정가(50G)를 차감하는지 확인
  2) price=-9999로 조작(골드 획득 시도) → 정가만 차감되는지 확인
  3) 골드 부족 상태에서 구매 시도 → 거부되는지 확인 (정상 가드 회귀 방지)
  4) 카탈로그에 없는 item_id → 거부되는지 확인
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def _make_client_with_session(gold=100, lv=5):
    from app import create_app
    from app.Shared import GAME_SESSIONS
    from game.Player_Class import create_player_by_job
    from game.Inventory import Inventory

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    player = create_player_by_job("상점테스터", "전사")
    player.lv = lv
    inv = Inventory.new()

    uid = "test-uid-shop"
    GAME_SESSIONS[uid] = {
        "player": player,
        "inventory": inv,
        "items": inv.to_flat_list(),
        "battle": None,
        "turn": 0,
        "hook": None,
        "gold": gold,
        "map": None, "chapter": None, "map_turn": 0,
        "mid_boss_cleared": False, "run_id": None,
        "pending_node_id": None,
    }
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid, GAME_SESSIONS


def test_zero_price_manipulation():
    print("\n[price=0 조작 → 정가(HP_M_potion=50G) 차감]")
    client, uid, store = _make_client_with_session(gold=100)
    r = client.post("/api/shop/buy", json={"item_id": "HP_M_potion", "price": 0})
    body = r.get_json()
    check("요청 200/ok", r.status_code == 200 and body.get("ok") is True,
          f"code={r.status_code}, body={body}")
    check("실제로는 정가 50G가 차감됨 (조작한 0원 아님)",
          body.get("gold") == 50, f"gold={body.get('gold')}")
    store.pop(uid, None)


def test_negative_price_manipulation():
    print("\n[price=-9999 조작 → 골드 획득 시도 차단]")
    client, uid, store = _make_client_with_session(gold=100)
    r = client.post("/api/shop/buy", json={"item_id": "HP_L_potion", "price": -9999})
    body = r.get_json()
    check("요청 200/ok", r.status_code == 200 and body.get("ok") is True,
          f"code={r.status_code}, body={body}")
    # HP_L_potion 정가 80G → 100 - 80 = 20 (음수 price로 골드가 늘어나면 안 됨)
    check("정가 80G만 차감됨 (골드가 늘어나지 않음)",
          body.get("gold") == 20, f"gold={body.get('gold')}")
    store.pop(uid, None)


def test_insufficient_gold_still_blocked():
    print("\n[골드 부족 시 정상적으로 차단되는지 (회귀 방지)]")
    client, uid, store = _make_client_with_session(gold=10)
    r = client.post("/api/shop/buy", json={"item_id": "HP_M_potion", "price": 10})
    body = r.get_json()
    check("골드 부족 → 400", r.status_code == 400, f"code={r.status_code}, body={body}")
    check("골드가 차감되지 않음", store.get(uid, {}).get("gold", None) in (10, None) or uid not in store)
    store.pop(uid, None)


def test_unknown_item_rejected():
    print("\n[카탈로그에 없는 item_id → 거부]")
    client, uid, store = _make_client_with_session(gold=1000)
    r = client.post("/api/shop/buy", json={"item_id": "완전_가짜_아이템", "price": 0})
    body = r.get_json()
    check("존재하지 않는 아이템: 400", r.status_code == 400, f"code={r.status_code}, body={body}")
    store.pop(uid, None)


def main():
    print("=" * 50)
    print(" /api/shop/buy price 신뢰 회귀 테스트")
    print("=" * 50)
    try:
        test_zero_price_manipulation()
        test_negative_price_manipulation()
        test_insufficient_gold_still_blocked()
        test_unknown_item_rejected()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 50)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 50)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
