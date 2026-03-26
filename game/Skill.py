"""
Skill.py
─────────────────────────────────────────────
플레이어 스킬 시스템.

변경사항:
  - 디버프 스킬 추가 (약화/마약화/저주/둔화)
  - try_skill()을 Battle_Engine 기반으로 리팩토링
  - 스킬 목록 출력 개선 (MP 비용, 타입 표시)
"""

from game.Damge import *
from ai.Battle_Engine import execute_skill, SKILL_META, EntitySnapshot, Action


class Ply_Skill:
    def __init__(self):
        # 스킬명: 습득 레벨
        self.all_skills = {
            # ── 공격 스킬 ──
            "셰이드 1":      3,
            "파이어볼 1":    5,
            "아이스 볼릿 1": 7,
            "셰이드 2":      10,
            "파이어볼 2":    13,
            "아이스 볼릿 2": 15,
            "파이어볼 3":    17,
            "아이스 볼릿 3": 21,
            # ── 디버프 스킬 ──
            "약화 1":        8,   # 적 방어력 감소
            "마약화 1":      9,   # 적 마법 방어력 감소
            "저주 1":        11,  # 적 공격력 감소
            "둔화 1":        12,  # 적 스피드 감소
            "약화 2":        16,
            "마약화 2":      18,
            "저주 2":        20,
        }
        self.learned_skills = []

    # ── 스킬 습득 업데이트 ──────────────────

    def update_skills(self, lv: int):
        """레벨업 시 호출 — 새로 배운 스킬 추가"""
        for skill, require_lv in self.all_skills.items():
            if require_lv <= lv and skill not in self.learned_skills:
                meta = SKILL_META.get(skill, {})
                skill_type = {
                    "physical": "물리", "magical": "마법", "debuff": "디버프"
                }.get(meta.get("type", ""), "")
                print(f"🎉 새로운 스킬 [{skill_type}] '{skill}'을(를) 배웠습니다!\n")
                self.learned_skills.append(skill)

    # ── 스킬 목록 출력 ──────────────────────

    def show_skills(self):
        """스킬 목록을 번호/이름/타입/MP비용으로 출력"""
        if not self.learned_skills:
            print("아직 배운 스킬이 없습니다.\n")
            return

        print("\n  ── 스킬 목록 ──")
        for i, skill in enumerate(self.learned_skills):
            meta = SKILL_META.get(skill, {})
            stype = {
                "physical": "물리", "magical": "마법", "debuff": "디버프"
            }.get(meta.get("type", ""), "?")
            mp_cost = meta.get("mp", 0)
            mp_str  = f"MP {mp_cost}" if mp_cost > 0 else "MP 없음"
            print(f"  {i+1:>2}. {skill:<14} [{stype}]  {mp_str}")
        print()

    # ── 스킬 실행 (실제 전투용) ─────────────

    def try_skill(
        self,
        player,
        enemy,
        damage_to_player: int,
        selected_skill:   str
    ):
        """
        실제 전투에서 스킬 사용.
        Battle_Engine의 execute_skill()을 활용.
        player/enemy는 EntitySnapshot으로 변환 후 처리.
        """
        meta = SKILL_META.get(selected_skill)
        if not meta:
            print("해당 스킬은 아직 구현되지 않았습니다.\n")
            return

        # EntitySnapshot 임시 생성 (실제 객체에 반영하기 위해 직접 수정)
        p_snap = EntitySnapshot.from_player(player)
        e_snap = EntitySnapshot.from_enemy(enemy)

        dmg, mp_lack, debuff_name = execute_skill(selected_skill, p_snap, e_snap)

        if mp_lack:
            print("MP가 부족합니다!\n")
            # 적 반격
            self._enemy_counter(player, enemy, damage_to_player)
            return

        # ── 결과 반영 ──
        player.mp = p_snap.mp  # MP 소모 반영

        if meta["type"] == "debuff":
            if debuff_name == "miss":
                # 빗나감 — MP는 소모됨
                print(f"\n{selected_skill}을(를) 사용했다!")
                print(f"  빗나갔다! (적중률 {int(meta.get('hit_rate', 0.70)*100)}%)\n")
                # 빗나겨도 적 반격은 발생
                self._enemy_counter(player, enemy, damage_to_player)
                return
            elif debuff_name and e_snap.debuffs:
                # 적중 성공
                db = e_snap.debuffs[-1]
                stat_name = {"arm": "방어력", "sparm": "마법방어력",
                             "stg": "공격력", "spd": "스피드"}.get(db.stat, db.stat)
                print(f"\n{selected_skill}을(를) 사용했다!")
                print(f"{enemy.name}의 {stat_name}이(가) {int(db.amount*100)}% 감소! "
                      f"({db.turns}턴 지속)\n")
            # 디버프를 실제 enemy 객체에도 반영 (enemy가 EntitySnapshot인 경우)
            if hasattr(enemy, 'debuffs'):
                enemy.debuffs = e_snap.debuffs
        else:
            # 공격 스킬
            enemy.hp -= dmg
            print(f"\n{selected_skill}을(를) 사용했다!")
            print(f"{enemy.name}에게 {dmg}의 데미지!\n")

        # 적 반격
        self._enemy_counter(player, enemy, damage_to_player)

    def _enemy_counter(self, player, enemy, damage_to_player: int):
        """적 반격 처리"""
        if enemy.hp > 0 and damage_to_player > 0:
            player.hp = Stg_massege_p(
                enemy.name, player.name, player.hp, damage_to_player
            )

    # ── 적 반격 (외부 호출용) ───────────────

    def enemy_att(self, pl, en, x):
        if en.hp > 0:
            pl.hp = Stg_massege_p(en.name, pl.name, pl.hp, x)

    def enemy_att_mp(player, enemy, y):
        if enemy.hp > 0:
            Ply_Skill.enemy_att(player, enemy, y)