# -*- coding: utf-8 -*-
"""
test_inventory_swap_parity.py — 포션/특수 인벤토리 교체 동등성 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_inventory_swap_parity.py

검증 대상 (실플레이 피드백 반영 — 포션도 특수템과 동일하게 "버릴 아이템
선택" UI를 받도록 일반화):
  game/Inventory.py의 add()가 포션 가득 시에도 candidates를 반환하는지,
  swap_special() → swap_item()으로 일반화된 함수가 포션/특수 양쪽에서
  정상 동작하는지, 종류가 다른 아이템끼리는 교체를 거부하는지.
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


def _full_potion_inventory():
    from game.Inventory import Inventory
    inv = Inventory.new()
    inv.potions = ["HP_S_potion"] * 6   # SLOT_LIMITS["potion"] == 6
    inv.special = []
    return inv


def _full_special_inventory():
    from game.Inventory import Inventory
    inv = Inventory.new()
    inv.potions = []
    inv.special = ["bomb", "web_bomb", "focus_drug"]   # SLOT_LIMITS["special"] == 3
    return inv


def test_potion_full_returns_candidates():
    print("\n[포션 가득 → candidates 반환 (특수템과 동등)]")
    inv = _full_potion_inventory()
    result = inv.add("MP_S_potion")
    check("ok=False", result["ok"] is False)
    check("reason=potion_full", result.get("reason") == "potion_full", f"got={result}")
    check("candidates에 기존 포션 6개 전부 포함",
          result.get("candidates") == ["HP_S_potion"] * 6, f"got={result.get('candidates')}")
    check("incoming 필드 존재", result.get("incoming") == "MP_S_potion")


def test_special_full_still_returns_candidates():
    print("\n[특수 가득 → candidates 반환 (회귀 확인 — 기존 동작 유지)]")
    inv = _full_special_inventory()
    result = inv.add("fire_vial")
    check("ok=False", result["ok"] is False)
    check("reason=special_full", result.get("reason") == "special_full", f"got={result}")
    check("candidates에 기존 특수템 3개 전부 포함",
          set(result.get("candidates", [])) == {"bomb", "web_bomb", "focus_drug"},
          f"got={result.get('candidates')}")


def test_swap_item_potion():
    print("\n[swap_item() — 포션 교체]")
    inv = _full_potion_inventory()
    result = inv.swap_item("HP_S_potion", "MP_S_potion")
    check("ok=True", result.get("ok") is True, f"got={result}")
    check("slot=potion", result.get("slot") == "potion")
    check("실제로 포션 목록이 교체됨",
          inv.potions.count("HP_S_potion") == 5 and inv.potions.count("MP_S_potion") == 1,
          f"potions={inv.potions}")


def test_swap_item_special():
    print("\n[swap_item() — 특수템 교체 (회귀 확인)]")
    inv = _full_special_inventory()
    result = inv.swap_item("bomb", "fire_vial")
    check("ok=True", result.get("ok") is True, f"got={result}")
    check("slot=special", result.get("slot") == "special")
    check("실제로 특수 목록이 교체됨",
          "bomb" not in inv.special and "fire_vial" in inv.special, f"special={inv.special}")


def test_swap_item_rejects_cross_slot():
    print("\n[swap_item() — 포션/특수 종류가 다르면 거부]")
    inv = _full_potion_inventory()
    result = inv.swap_item("bomb", "MP_S_potion")   # bomb은 포션 목록에 없음(종류도 다름)
    check("ok=False (drop_item이 special인데 potion 슬롯 교체 시도)",
          result.get("ok") is False, f"got={result}")
    check("reason=slot_mismatch", result.get("reason") == "slot_mismatch", f"got={result}")


def test_swap_item_drop_not_found():
    print("\n[swap_item() — 버릴 아이템이 실제로 없으면 거부]")
    inv = _full_potion_inventory()
    result = inv.swap_item("MP_L_potion", "MP_S_potion")   # 보유하지 않은 포션을 버리려 함
    check("ok=False", result.get("ok") is False, f"got={result}")
    check("reason=drop_not_found", result.get("reason") == "drop_not_found", f"got={result}")


def main():
    print("=" * 50)
    print(" 포션/특수 인벤토리 교체 동등성 회귀 테스트")
    print("=" * 50)
    try:
        test_potion_full_returns_candidates()
        test_special_full_still_returns_candidates()
        test_swap_item_potion()
        test_swap_item_special()
        test_swap_item_rejects_cross_slot()
        test_swap_item_drop_not_found()
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
