# -*- coding: utf-8 -*-
"""
test_api_guards.py — /api/use_item 가드 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 test_api_guards.py

검증 대상 (최근 버그 수정 잠금용):
  1. 사망 상태(hp<=0)에서 필드 포션 사용  → 400 + reason "player_dead"
  2. 전투 전용 특수 아이템(bomb 등) 필드 사용 → 400 + reason "battle_only"
  3. amount/stat 없는 비필드 아이템        → 400 + reason "not_field_item" (500 아님)
  + 회귀: 정상 포션은 그대로 200/ok

방식:
  실제 Flask 라우트(/api/use_item)를 test_client로 호출.
  GAME_SESSIONS에 가짜 게임 상태를 주입하고 session 쿠키로 연결 →
  가드의 '차단 순서'까지 실제 코드 경로로 검증한다.
"""
import sys

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2705 {name}")
    else:
        FAIL += 1
        print(f"  \u274c {name}  {detail}")


class StubPlayer:
    """use_item 라우트 + _player_dict 직렬화가 요구하는 필드를 모두 가진 가짜 플레이어.
       (정상 포션 경로는 성공 시 _player_dict(player, inv)로 응답을 만든다.)"""
    def __init__(self, hp=500, maxhp=500, mp=100, maxmp=100):
        self.name = "테스터"
        self.hp = hp
        self.maxhp = maxhp
        self.mp = mp
        self.maxmp = maxmp
        self.lv = 5
        self.job = "전사"
        # _player_dict 직렬화 필드
        self.stg = 10
        self.arm = 10
        self.sp = 10
        self.sparm = 10
        self.spd = 10
        self.luc = 10
        self.exp = 0
        self.maxexp = 100
        self.skill = None          # 'if player.skill else []' 로 안전
        self.pending_points = 0


def _build_inventory(items):
    """실제 game.Inventory 객체 구성 (정상 포션 경로가 remove/to_flat_list 호출)."""
    from game.Inventory import Inventory, get_slot
    inv = Inventory.new()
    for it in items:
        try:
            slot = get_slot(it)
        except Exception:
            slot = "potion" if it.endswith("_potion") else "special"
        if slot == "potion":
            inv.potions.append(it)
        else:
            inv.special.append(it)
    return inv


def _make_client_with_session(items, hp=500):
    """create_app() 후 GAME_SESSIONS에 가짜 gs 주입, session 쿠키 연결."""
    from app import create_app
    from app.Shared import GAME_SESSIONS

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    inv = _build_inventory(items)
    uid = "test-uid-guard"
    GAME_SESSIONS[uid] = {
        "player": StubPlayer(hp=hp),
        "inventory": inv,                  # 실제 Inventory (정상 포션 경로용)
        "items": inv.to_flat_list(),       # 세션 구조와 동일
        "battle": None,                    # 전투 외 상태
        "turn": 0,
        "hook": None,
        "gold": 100,
    }
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid, GAME_SESSIONS


def _post_use(client, item):
    return client.post("/api/use_item", json={"item": item})


def test_guards():
    print("\n[/api/use_item 가드]")

    # 1. 사망 상태 → player_dead
    items = ["HP_S_potion"]
    client, uid, store = _make_client_with_session(items, hp=0)
    r = _post_use(client, "HP_S_potion")
    body = r.get_json()
    check("사망 상태 포션: 400", r.status_code == 400, f"code={r.status_code}")
    check("사망 상태 포션: reason=player_dead",
          body.get("reason") == "player_dead", f"body={body}")
    store.pop(uid, None)

    # 2. 특수 아이템(bomb 등) → battle_only
    specials = ["bomb", "web_bomb", "fire_vial", "ice_vial", "lightning_crystal"]
    client, uid, store = _make_client_with_session(specials, hp=500)
    for it in specials:
        r = _post_use(client, it)
        body = r.get_json()
        check(f"특수 '{it}': 400 + battle_only",
              r.status_code == 400 and body.get("reason") == "battle_only",
              f"code={r.status_code}, body={body}")
    store.pop(uid, None)

    # 3. 정상 포션 회귀 (가드 통과 → 200/ok)
    client, uid, store = _make_client_with_session(["HP_S_potion"], hp=300)
    r = _post_use(client, "HP_S_potion")
    body = r.get_json()
    check("정상 포션 HP_S_potion: 가드 통과(ok)",
          r.status_code == 200 and body.get("ok") is True,
          f"code={r.status_code}, body={body}")
    store.pop(uid, None)

    # 4. drug 류(buff 특수)도 battle_only
    client, uid, store = _make_client_with_session(["focus_drug", "haste_drug"], hp=500)
    for it in ["focus_drug", "haste_drug"]:
        r = _post_use(client, it)
        body = r.get_json()
        check(f"특수 '{it}': 400 + battle_only",
              r.status_code == 400 and body.get("reason") == "battle_only",
              f"code={r.status_code}, body={body}")
    store.pop(uid, None)


def test_not_field_item():
    """
    amount/stat가 없지만 slot=special도 category도 아닌 가상의 아이템 →
    not_field_item 분기(500 아님)를 검증.
    실제 ITEM_META에는 그런 항목이 없으므로 임시 주입 후 복구.
    """
    print("\n[not_field_item 분기 (500 방지)]")
    try:
        from ai.battle import Items as ItemsMod
        ITEM_META = ItemsMod.ITEM_META
    except Exception as ex:
        print(f"  \u26a0 ITEM_META 로드 실패, 건너뜀: {str(ex)[:60]}")
        return

    fake = "broken_test_item"
    ITEM_META[fake] = {"foo": "bar"}  # amount/stat/slot/category 전부 없음
    try:
        client, uid, store = _make_client_with_session([fake], hp=500)
        r = _post_use(client, fake)
        body = r.get_json()
        check("비필드 아이템: 500 아님 (400)", r.status_code == 400,
              f"code={r.status_code}")
        check("비필드 아이템: reason=not_field_item",
              body.get("reason") == "not_field_item", f"body={body}")
        store.pop(uid, None)
    finally:
        ITEM_META.pop(fake, None)  # 원상복구


def main():
    print("=" * 50)
    print(" /api/use_item 가드 회귀 테스트")
    print("=" * 50)
    try:
        test_guards()
        test_not_field_item()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  \u274c 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 50)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 50)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()