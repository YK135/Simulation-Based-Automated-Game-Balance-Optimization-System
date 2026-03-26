"""
Action_Class.py
─────────────────────────────────────────────
실제 전투 UI 처리.

수정사항:
  - Battle_interface()에 clear() 제거 → 행동 결과가 화면에 남음
  - 매 행동 후 [Enter] 대기 → 결과 확인 후 다음 턴으로
  - Battle_interface(player, enemy) 전달 → HP바 표시
  - 스킬/아이템 선택 후 결과 보임
"""

from game.Damge import *
from game.Player_Class import *
from game.Skill import Ply_Skill
from game.Item import Item_
from interfave.Game_Interface import (
    clear, GameEmdKey, Battle_interface, show_enemy_status
)
from game.Lv import LV_

pl_skill = Ply_Skill()


class Act:
    def __init__(self, player, enemy, item_list):
        self.player = player
        self.enemy  = enemy
        self.item   = item_list
        if self.player.lv >= 3:
            pl_skill.update_skills(self.player.lv)

    def action(self):
        pl_item = Item_(self.player, self.item)
        pl_lv   = LV_(self.player)

        # 전투 시작 알림 (clear 없이 출력)
        print("\n" + "=" * 40)
        print(f"  전투 시작!  {self.player.name}  vs  {self.enemy.name}")
        print("=" * 40 + "\n")

        while True:
            damage_to_enemy  = stg_Attack(self.player.stg, self.player.luc,
                                           self.enemy.arm,   self.enemy.luc)
            damage_to_player = stg_Attack(self.enemy.stg,   self.enemy.luc,
                                           self.player.arm,  self.player.luc)

            # ── 전투 종료 판정 ──
            if self.enemy.hp <= 0:
                print(f"\n  ★ {self.enemy.name}을(를) 퇴치했습니다!\n")
                if hasattr(self.enemy, 'exp_reward'):
                    exp = self.enemy.exp_reward(self.player.maxexp)
                    pl_lv.Get_exp(self.player, reward_exp=exp)
                else:
                    pl_lv.Get_exp(self.player)
                input("[Enter] 계속...")
                break

            if self.player.hp <= 0:
                print(f"\n  {self.player.name}이(가) 쓰러졌다...\n")
                input("[Enter] 계속...")
                break

            # ── 전투 UI 출력 (clear 없음 — 결과 유지) ──
            Battle_interface(self.player, self.enemy)
            key = input("  입력: ").strip()

            # ── 1. 일반 공격 ──
            if key == '1':
                print()
                self.enemy.hp = Stg_massege_e(
                    self.enemy.name, self.enemy.hp, damage_to_enemy
                )
                pl_skill.enemy_att(self.player, self.enemy, damage_to_player)
                input("\n[Enter] 계속...")

            # ── 2. 스킬 ──
            elif key == '2':
                if pl_skill.learned_skills:
                    print()
                    pl_skill.show_skills()
                    print("  사용할 스킬 번호 입력 (취소: q):")
                    key2 = input("  입력: ").strip()
                    if key2.lower() == 'q':
                        continue
                    try:
                        idx            = int(key2)
                        selected_skill = pl_skill.learned_skills[idx - 1]
                        print(f"\n  선택: {selected_skill}\n")
                        pl_skill.try_skill(
                            self.player, self.enemy,
                            damage_to_player, selected_skill
                        )
                    except (IndexError, ValueError):
                        print("  잘못된 스킬 번호입니다.\n")
                    input("\n[Enter] 계속...")
                else:
                    print("  아직 배운 스킬이 없습니다.\n")
                    input("[Enter] 계속...")

            # ── 3. 아이템 ──
            elif key == '3':
                print()
                pl_item.show_item()
                if not self.item:
                    input("[Enter] 계속...")
                    continue
                print("  사용할 아이템 번호 선택 (취소: q)")
                key2 = input("  입력: ").strip()
                if key2.lower() == 'q':
                    continue
                try:
                    idx    = int(key2)
                    unique = list(dict.fromkeys(self.item))
                    if 0 <= idx < len(unique):
                        pl_item.use_item(unique[idx])
                    else:
                        print("  잘못된 번호입니다.\n")
                except (ValueError, IndexError):
                    print("  잘못된 입력입니다.\n")
                input("\n[Enter] 계속...")

            # ── 4. 내 상태 ──
            elif key == '4':
                print()
                self.player.Show_Staters()
                if self.player.skill:
                    self.player.skill.show_skills()
                input("[Enter] 계속...")

            # ── 5. 적 상태 ──
            elif key == '5':
                show_enemy_status(self.enemy)
                input("[Enter] 계속...")

            # ── 6. 도망가기 ──
            elif key == '6':
                from random import random as _rnd
                p_spd  = getattr(self.player, 'spd', 10)
                e_spd  = getattr(self.enemy,  'spd', 10)
                ratio  = p_spd / max(e_spd, 1.0)
                if ratio >= 2.0:   chance = 0.95
                elif ratio >= 1.5: chance = 0.80
                elif ratio >= 1.0: chance = 0.60
                elif ratio >= 0.7: chance = 0.35
                else:              chance = 0.15

                print(f"\n  도망 시도... (성공률 {int(chance*100)}%)")
                if _rnd() <= chance:
                    print("  도망에 성공했다!\n")
                    input("[Enter] 계속...")
                    return "escaped"
                else:
                    print("  도망에 실패했다!")
                    print(f"  {self.enemy.name}의 반격!")
                    self.player.hp = Stg_massege_p(
                        self.enemy.name, self.player.name,
                        self.player.hp, damage_to_player
                    )
                    input("\n[Enter] 계속...")

            elif key == 'q':
                GameEmdKey()

            else:
                print("  1~6 중에서 입력하세요.\n")