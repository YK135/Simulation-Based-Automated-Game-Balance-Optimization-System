"""
Item.py — 아이템 시스템
n행 2열 표시, 비율+고정 혼합 회복
"""
from __future__ import annotations
import time
from collections import Counter

# 회복량 단일 소스: ai/Battle_Engine.py ITEM_META
# Digital Twin 원칙 — 웹/콘솔/시뮬 회복량 일치
try:
    from ai.Battle_Engine import ITEM_META
except ModuleNotFoundError:
    try:
        from ai.Battle_Engine import ITEM_META
    except Exception:
        ITEM_META = {}


class Item_():
    def __init__(self, ply, item_list):
        self.player = ply
        self.item   = item_list

    # ── 회복 공식: ITEM_META 단일 소스 ───────
    # 폴백 공식 (ITEM_META 로드 실패 시에만 사용)
    _FALLBACK_AMOUNT = {
        "HP_S_potion": lambda u: max(200, int(u.maxhp * 0.12)),
        "HP_M_potion": lambda u: max(300, int(u.maxhp * 0.20)),
        "HP_L_potion": lambda u: max(500, int(u.maxhp * 0.30)),
        "MP_S_potion": lambda u: max(25,  int(u.maxmp * 0.15)),
        "MP_M_potion": lambda u: max(40,  int(u.maxmp * 0.25)),
        "MP_L_potion": lambda u: max(50,  int(u.maxmp * 0.35)),
    }

    @staticmethod
    def _apply_potion(player, item_name: str):
        """ITEM_META 기준 회복 (콘솔 출력 포함)."""
        meta = ITEM_META.get(item_name)
        if meta:
            stat   = meta["stat"]
            amount = meta["amount"](player)
        else:
            stat   = "hp" if item_name.startswith("HP") else "mp"
            amount = Item_._FALLBACK_AMOUNT.get(
                item_name, lambda u: 0)(player)

        if stat == "hp":
            before = int(player.hp)
            player.hp = min(player.maxhp, player.hp + amount)
            after = int(player.hp)
            print(f"  HP {before} -> {after}  (+{after - before} 회복!)")
        else:
            before = int(player.mp)
            player.mp = min(player.maxmp, player.mp + amount)
            after = int(player.mp)
            print(f"  MP {before} -> {after}  (+{after - before} 회복!)")
        time.sleep(1.0)

    # ── 아이템 목록 (n행 2열) ────────────────
    def show_item(self):
        if not self.item:
            print("  보유 아이템이 없습니다\n")
            return

        # (인덱스, 이름, 개수) 중복 제거
        item_count = Counter(self.item)
        unique     = list(dict.fromkeys(self.item))  # 순서 유지
        entries    = []
        for idx, name in enumerate(unique):
            cnt   = item_count[name]
            label = (str(idx) + ". " + name + " x" + str(cnt)).ljust(24)
            entries.append(label)

        print("  ── 아이템 목록 ─────────────────────")
        for j in range(0, len(entries), 2):
            left  = entries[j]
            right = entries[j+1] if j+1 < len(entries) else ""
            print("  " + left + "  " + right)
        print()

    # ── 아이템 사용 ──────────────────────────
    def use_item(self, item):
        valid = {"HP_S_potion", "HP_M_potion", "HP_L_potion",
                 "MP_S_potion", "MP_M_potion", "MP_L_potion"}
        if item in valid:
            Item_._apply_potion(self.player, item)
            self.item.remove(item)
        else:
            print("  잘못된 입력입니다.\n")