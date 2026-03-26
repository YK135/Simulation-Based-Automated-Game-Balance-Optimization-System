"""
Lv.py
─────────────────────────────────────────────
레벨업 및 경험치 시스템.

변경사항:
  - 레벨업 시 MP 회복: 레벨업 전 MP 비율(%) 유지
    ex) 레벨업 전 maxmp의 75% → 레벨업 후 새 maxmp의 75%로 회복
  - 경험치는 몬스터 등급별로 차등 지급 (Enemy_Class에서 계산)
"""

from random import randint
from game.Skill import *


class LV_:
    def __init__(self, ply):
        self.player = ply

    @staticmethod
    def Lv_up(player):
        """레벨업 처리. 레벨업 전 MP 비율을 유지하며 회복."""

        # ── 1. 레벨업 전 MP 비율 저장 ──
        mp_ratio = player.mp / player.maxmp if player.maxmp > 0 else 1.0

        # ── 2. 이전 스탯 저장 (출력용) ──
        before = {
            "maxhp": player.maxhp,
            "maxmp": player.maxmp,
            "stg":   player.stg,
            "sp":    player.sp,
            "arm":   player.arm,
            "sparm": player.sparm,
            "luc":   player.luc,
        }

        # ── 3. 레벨 및 스킬 갱신 ──
        player.lv  += 1
        player.skill = Ply_Skill()
        player.skill.update_skills(player.lv)
        base_lv = player.lv

        # ── 4. 스탯 상승 ──
        player.exp   -= player.maxexp
        player.maxhp += 40 + (base_lv * 3)
        player.hp    += 20 + (base_lv * 3)          # HP 일부 회복
        player.hp     = min(player.hp, player.maxhp) # maxhp 초과 방지

        player.maxmp += 5 + (base_lv // 4)
        # MP: 레벨업 전 비율로 회복
        player.mp = round(player.maxmp * mp_ratio)
        player.mp = min(player.mp, player.maxmp)

        player.stg   += 1.5 + (base_lv // 5)
        player.sp    += 2   + (base_lv // 5)
        player.arm   += 1.5
        player.sparm += 1.2
        player.luc   += (base_lv % 2)

        # ── 5. 변화 출력 ──
        after = {
            "maxhp": player.maxhp,
            "maxmp": player.maxmp,
            "stg":   player.stg,
            "sp":    player.sp,
            "arm":   player.arm,
            "sparm": player.sparm,
            "luc":   player.luc,
        }
        name_map = {
            "maxhp": "HP",  "maxmp": "MP",
            "stg":   "힘",  "sp":    "마력",
            "arm":   "방어력", "sparm": "마법방어력",
            "luc":   "행운",
        }

        print(f"\n📈 {player.name} 레벨업! (Lv.{base_lv - 1} → Lv.{base_lv})")
        print(f"   MP 회복: {int(mp_ratio * 100)}% 유지 → {int(player.mp)}/{int(player.maxmp)}")
        for stat in before:
            b = round(before[stat], 2)
            a = round(after[stat],  2)
            if b != a:
                print(f"   {name_map[stat]}: {b} → {a}")

    def Get_exp(self, player, reward_exp: int = None):
        """
        경험치 획득 처리.
        reward_exp: 몬스터에서 받은 경험치 (없으면 랜덤 45~60)
        연속 레벨업도 처리.
        """
        if reward_exp is None:
            reward_exp = randint(45, 60)

        print(f"{reward_exp}의 경험치를 획득!!\n")
        player.exp += reward_exp

        # 연속 레벨업 처리
        while player.exp >= player.maxexp:
            print("레벨이 올랐습니다!\n")
            LV_.Lv_up(player)