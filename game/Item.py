"""
Item.py — 아이템 시스템
n행 2열 표시, 비율+고정 혼합 회복
"""
from __future__ import annotations
import time
from collections import Counter


class Item_():
    def __init__(self, ply, item_list):
        self.player = ply
        self.item   = item_list

    # ── HP 포션 ──────────────────────────────
    def HP_Potion_S(player):
        amount = max(300, int(player.maxhp * 0.12))
        before = int(player.hp)
        player.hp = min(player.maxhp, player.hp + amount)
        print("  HP " + str(before) + " -> " + str(int(player.hp)) +
              "  (+" + str(int(player.hp) - before) + " 회복!)")
        time.sleep(1.0)

    def HP_Potion_M(player):
        amount = max(500, int(player.maxhp * 0.20))
        before = int(player.hp)
        player.hp = min(player.maxhp, player.hp + amount)
        print("  HP " + str(before) + " -> " + str(int(player.hp)) +
              "  (+" + str(int(player.hp) - before) + " 회복!)")
        time.sleep(1.0)

    def HP_Potion_L(player):
        amount = max(850, int(player.maxhp * 0.30))
        before = int(player.hp)
        player.hp = min(player.maxhp, player.hp + amount)
        print("  HP " + str(before) + " -> " + str(int(player.hp)) +
              "  (+" + str(int(player.hp) - before) + " 회복!)")
        time.sleep(1.0)

    # ── MP 포션 ──────────────────────────────
    def MP_Potion_S(player):
        amount = max(20, int(player.maxmp * 0.15))
        before = int(player.mp)
        player.mp = min(player.maxmp, player.mp + amount)
        print("  MP " + str(before) + " -> " + str(int(player.mp)) +
              "  (+" + str(int(player.mp) - before) + " 회복!)")
        time.sleep(1.0)

    def MP_Potion_M(player):
        amount = max(40, int(player.maxmp * 0.25))
        before = int(player.mp)
        player.mp = min(player.maxmp, player.mp + amount)
        print("  MP " + str(before) + " -> " + str(int(player.mp)) +
              "  (+" + str(int(player.mp) - before) + " 회복!)")
        time.sleep(1.0)

    def MP_Potion_L(player):
        amount = max(60, int(player.maxmp * 0.35))
        before = int(player.mp)
        player.mp = min(player.maxmp, player.mp + amount)
        print("  MP " + str(before) + " -> " + str(int(player.mp)) +
              "  (+" + str(int(player.mp) - before) + " 회복!)")
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
        effects = {
            "HP_S_potion": Item_.HP_Potion_S,
            "HP_M_potion": Item_.HP_Potion_M,
            "HP_L_potion": Item_.HP_Potion_L,
            "MP_S_potion": Item_.MP_Potion_S,
            "MP_M_potion": Item_.MP_Potion_M,
            "MP_L_potion": Item_.MP_Potion_L,
        }
        if item in effects:
            effects[item](self.player)
            self.item.remove(item)
        else:
            print("  잘못된 입력입니다.\n")