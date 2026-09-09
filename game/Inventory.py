"""
Inventory.py
─────────────────────────────────────────────
인벤토리 관리 모듈 — 포션/특수 분리 시스템.

데이터 구조:
  inv = {
      "potions": ["HP_S_potion", "HP_M_potion", ...],  # max 6
      "special": ["bomb", "concentration_potion"],     # max 3
  }

특징:
  - ITEM_META의 "slot" 필드로 자동 분류 ("potion" or "special")
  - 슬롯별 최대 개수 제한 (포션 6, 특수 3)
  - 가득 차면 "버릴 아이템 선택" 신호 반환

사용:
  from game.Inventory import Inventory

  # 새 게임
  inv = Inventory.new()

  # 아이템 추가 (자동 분류)
  result = inv.add("HP_S_potion")  # → {"ok": True, "slot": "potion"}
  result = inv.add("bomb")          # → {"ok": True, "slot": "special"}

  # 가득 찬 경우
  result = inv.add("bomb")          # 특수가 가득
  # → {"ok": False, "reason": "full", "slot": "special",
  #    "candidates": [...], "incoming": "bomb"}

  # 특정 아이템 버리고 새 아이템 추가
  inv.swap("web_bomb", new_item="bomb")  # 기존 거 제거 후 새 거 추가

  # 사용 (제거)
  inv.use("HP_S_potion")
"""

from __future__ import annotations
from typing import Optional, List


# ─────────────────────────────────────────────
# 슬롯 제한
# ─────────────────────────────────────────────

SLOT_LIMITS = {
    "potion": 6,
    "special": 3,
}


# ─────────────────────────────────────────────
# 슬롯 자동 분류
# ─────────────────────────────────────────────

def get_slot(item_name: str) -> str:
    """
    ITEM_META에서 slot 정보 가져옴.
    기본값: 모든 *_potion 은 "potion", 나머지는 "special".
    ITEM_META에 slot 명시되어 있으면 그걸 우선.
    """
    from ai.battle import ITEM_META

    meta = ITEM_META.get(item_name, {})
    if "slot" in meta:
        return meta["slot"]

    # 폴백: 이름 패턴
    if item_name.endswith("_potion") and item_name.startswith(("HP_", "MP_")):
        return "potion"
    return "special"


# ─────────────────────────────────────────────
# Inventory 클래스
# ─────────────────────────────────────────────

class Inventory:
    """
    인벤토리 — 포션/특수 분리.
    dict 기반 (직렬화 가능 → DB 저장/배포 대비).
    """

    def __init__(self, data: Optional[dict] = None):
        """
        data: {"potions": [...], "special": [...]} 또는 None (빈 인벤토리)
        """
        if data is None:
            data = {"potions": [], "special": []}
        self.potions = list(data.get("potions", []))
        self.special = list(data.get("special", []))

    @classmethod
    def new(cls) -> "Inventory":
        """빈 인벤토리"""
        return cls()

    # ─────────────────────────────────────────
    # 직렬화 (DB/JSON 저장용)
    # ─────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "potions": list(self.potions),
            "special": list(self.special),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Inventory":
        return cls(data)

    # ─────────────────────────────────────────
    # 평탄화 (BattleSession/EntitySnapshot 호환)
    # ─────────────────────────────────────────

    def to_flat_list(self) -> List[str]:
        """
        BattleSession은 단순 list를 받음.
        포션 + 특수 합쳐서 리스트 반환 (전투용).
        """
        return list(self.potions) + list(self.special)

    # ─────────────────────────────────────────
    # 추가
    # ─────────────────────────────────────────

    def add(self, item_name: str) -> dict:
        """
        아이템 추가. 슬롯 자동 분류.

        성공: {"ok": True, "slot": "potion" or "special"}
        실패: {"ok": False, "reason": "full", "slot": ...,
               "candidates": [...], "incoming": item_name}
        """
        slot = get_slot(item_name)

        if slot == "potion":
            if len(self.potions) >= SLOT_LIMITS["potion"]:
                # ★ 예전엔 포션은 가득 차면 그냥 거절(선택 없음)이었는데, 특수템과
                #   일관되게 "버릴 아이템 선택" UI를 받도록 변경 — candidates 추가.
                return {
                    "ok": False,
                    "reason": "potion_full",
                    "slot": "potion",
                    "incoming": item_name,
                    "candidates": list(self.potions),
                    "message": "포션 가방이 가득 찼습니다. 버릴 아이템을 선택하세요.",
                }
            self.potions.append(item_name)
            return {"ok": True, "slot": "potion", "item": item_name}

        elif slot == "special":
            if len(self.special) >= SLOT_LIMITS["special"]:
                # 특수는 가득 차면 선택 모달
                return {
                    "ok": False,
                    "reason": "special_full",
                    "slot": "special",
                    "incoming": item_name,
                    "candidates": list(self.special),
                    "message": "특수 가방이 가득 찼습니다. 버릴 아이템을 선택하세요.",
                }
            self.special.append(item_name)
            return {"ok": True, "slot": "special", "item": item_name}

        return {"ok": False, "reason": "unknown_slot", "slot": slot}

    # ─────────────────────────────────────────
    # 슬롯 교체 (포션/특수 공용 — 가득 찼을 때 사용)
    # ─────────────────────────────────────────

    def discard_multi(self, drops: dict) -> dict:
        """
        여러 아이템을 한 번에, 원자적으로 버린다.
        drops: {item_name: count} — 포션/특수 섞여도 무방(버킷은 remove()가
        알아서 찾음). 실행 전 모든 (item, count)가 실제 보유 수량 이내인지
        먼저 전부 검증하고, 하나라도 부족하면 아무것도 지우지 않고 실패를
        반환한다(중간 실패로 일부만 삭제되는 일이 없음).

        성공: {"ok": True, "dropped": {item: count, ...}}
        실패: {"ok": False, "reason": "empty"|"invalid_count"|"insufficient",
               "message": ...}
        """
        if not drops:
            return {"ok": False, "reason": "empty", "message": "버릴 아이템이 없습니다."}

        for item_name, count in drops.items():
            if not isinstance(count, int) or count <= 0:
                return {"ok": False, "reason": "invalid_count",
                        "message": f"{item_name}의 수량이 올바르지 않습니다."}
            owned = self.count(item_name)
            if owned < count:
                return {"ok": False, "reason": "insufficient",
                        "message": f"{item_name}을(를) {count}개 버리려 했지만 "
                                   f"{owned}개만 보유 중입니다."}

        for item_name, count in drops.items():
            for _ in range(count):
                self.remove(item_name)

        return {"ok": True, "dropped": dict(drops)}

    def swap_item(self, drop_item: str, new_item: str) -> dict:
        """
        포션/특수 슬롯이 가득 찼을 때 호출. drop_item을 제거하고 new_item 추가.
        new_item의 슬롯 종류(포션/특수)로 대상 버킷을 정하고, drop_item이
        같은 종류가 아니면 거부한다(포션 칸이 꽉 찼는데 특수템을 버려서
        자리를 만드는 식의 뒤섞임 방지). 실제 제거는 discard_multi()에
        위임 — 중복 로직 없이 동일한 원자성 보장을 재사용한다.
        """
        slot = get_slot(new_item)
        if slot not in ("potion", "special"):
            return {"ok": False, "reason": "unknown_slot",
                    "message": f"{new_item}은(는) 알 수 없는 종류입니다."}

        if get_slot(drop_item) != slot:
            return {"ok": False, "reason": "slot_mismatch",
                    "message": f"{drop_item}과(와) {new_item}은(는) 종류가 달라 교체할 수 없습니다."}

        discard_res = self.discard_multi({drop_item: 1})
        if not discard_res["ok"]:
            reason = "drop_not_found" if discard_res["reason"] == "insufficient" else discard_res["reason"]
            message = (f"버릴 아이템 {drop_item}이(가) 인벤토리에 없습니다."
                       if reason == "drop_not_found" else discard_res["message"])
            return {"ok": False, "reason": reason, "message": message}

        bucket = self.potions if slot == "potion" else self.special
        bucket.append(new_item)
        return {"ok": True, "dropped": drop_item, "added": new_item, "slot": slot}

    # ─────────────────────────────────────────
    # 사용 (제거)
    # ─────────────────────────────────────────

    def has(self, item_name: str) -> bool:
        return item_name in self.potions or item_name in self.special

    def remove(self, item_name: str) -> bool:
        """첫 발견된 아이템 1개 제거. 성공 True / 실패 False."""
        if item_name in self.potions:
            self.potions.remove(item_name)
            return True
        if item_name in self.special:
            self.special.remove(item_name)
            return True
        return False

    def use(self, item_name: str) -> bool:
        """remove의 별칭 (의미 명확화용)"""
        return self.remove(item_name)

    # ─────────────────────────────────────────
    # 조회
    # ─────────────────────────────────────────

    def count(self, item_name: str) -> int:
        """특정 아이템 보유 수"""
        return self.potions.count(item_name) + self.special.count(item_name)

    # ─────────────────────────────────────────
    # 응답용 dict (UI 표시)
    # ─────────────────────────────────────────

    def to_response_dict(self) -> dict:
        """
        프론트에 보낼 응답 형식.
        포션은 종류별 카운트, 특수는 리스트 그대로.
        """
        from collections import Counter
        pot_counts = Counter(self.potions)
        return {
            "potions": [{"name": k, "count": v} for k, v in pot_counts.items()],
            "special": list(self.special),
            "potion_capacity": SLOT_LIMITS["potion"],
            "special_capacity": SLOT_LIMITS["special"],
            "potion_used": len(self.potions),
            "special_used": len(self.special),
        }
