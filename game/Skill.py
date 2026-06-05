"""
Skill.py — 직업별 스킬 트리 시스템
레벨업 시 자동 스킬 습득 + 상위 스킬 대체
"""
from __future__ import annotations

try:
    from ai.Battle_Engine import SKILL_META
except ModuleNotFoundError:
    try:
        from ai.Battle_Engine import SKILL_META
    except Exception:
        SKILL_META = {}

# 스킬 해금 테이블 단일 소스: game/Lv.py JOB_SKILL_UNLOCKS
# 순환 import 방지 — 모듈 로드 시점이 아닌 최초 접근 시 lazy 로드


class Ply_Skill:
    # ────────────────────────────────────────────
    # 직업별 스킬 트리
    # ────────────────────────────────────────────
    # 스킬 해금 테이블은 game/Lv.py의 JOB_SKILL_UNLOCKS가 단일 소스(정본).
    # 순환 import 방지를 위해 lazy 접근.
    @staticmethod
    def _get_unlocks():
        try:
            from game.Lv import JOB_SKILL_UNLOCKS
        except ModuleNotFoundError:
            try:
                from Lv import JOB_SKILL_UNLOCKS
            except Exception:
                JOB_SKILL_UNLOCKS = {}
        return JOB_SKILL_UNLOCKS
    
    # ────────────────────────────────────────────
    # 상위 스킬 → 하위 스킬 매핑
    # ────────────────────────────────────────────
    SKILL_UPGRADES = {
        "강타2": "강타1",
        "연속공격2": "연속공격1",
        "강화2": "강화1",
        "슬래시2": "슬래시1",
        "약화2": "약화1",
        "파이어볼2": "파이어볼1",
        "힐2": "힐1",
        "아이스볼릿2": "아이스볼릿1",
        "라이트닝2": "라이트닝1",
        "효율성2": "효율성1",
        "마약화2": "마약화1",
        "몸통박치기2": "몸통박치기1",
        "수비태세2": "수비태세1",
        "되갚기2": "되갚기1",
        "저주2": "저주1",
        "급소찌르기2": "급소찌르기1",
        "난사2": "난사1",
        "둔화2": "둔화1",
    }

    def __init__(self, job: str):
        self.job = job
        self.learned_skills = []

    def update_skills(self, lv: int):
        """레벨업 시 스킬 습득 + 상위 스킬 자동 대체"""
        unlocks = self._get_unlocks()
        if self.job not in unlocks:
            return

        skill_tree = unlocks[self.job]

        if lv in skill_tree:
            for new_skill in skill_tree[lv]:
                # 상위 스킬인 경우 하위 스킬 제거
                if new_skill in self.SKILL_UPGRADES:
                    old_skill = self.SKILL_UPGRADES[new_skill]
                    if old_skill in self.learned_skills:
                        self.learned_skills.remove(old_skill)
                        print(f"  [스킬 강화] '{old_skill}' → '{new_skill}'")

                # 새 스킬 추가
                if new_skill not in self.learned_skills:
                    self.learned_skills.append(new_skill)

                    # 스킬 타입 표시
                    meta = SKILL_META.get(new_skill, {})
                    skill_type = {
                        "physical": "물리",
                        "magical": "마법",
                        "buff": "버프",
                        "debuff": "디버프",
                        "heal": "회복",
                        "multi_hit": "연타",
                        "counter": "반격",
                        "tank_attack": "방어공격",
                        "shield": "보호막",
                    }.get(meta.get("type", ""), "")

                    # 상위 스킬이 아닌 경우에만 신규 습득 메시지
                    if new_skill not in self.SKILL_UPGRADES:
                        print(f"  🎉 새 스킬 [{skill_type}] '{new_skill}' 습득!")

    def show_skills(self, for_battle: bool = False):
        """스킬 목록 표시 (공격/보조 분리, n행 2열)"""
        if not self.learned_skills:
            print("  아직 배운 스킬이 없습니다.\n")
            return

        attack_skills = []
        support_skills = []

        for i, sk in enumerate(self.learned_skills):
            meta = SKILL_META.get(sk, {})
            stype = meta.get("type", "")
            mp = meta.get("mp", 0)
            label = f"{i+1}. {sk} [MP{mp}]".ljust(22)

            if stype in ["debuff", "buff", "heal", "shield"]:
                support_skills.append((i+1, label))
            else:
                attack_skills.append((i+1, label))

        def _print_2col(items):
            for j in range(0, len(items), 2):
                left = items[j][1]
                right = items[j+1][1] if j+1 < len(items) else ""
                print(f"  {left}  {right}")

        if attack_skills:
            print("  ── 공격 스킬 ──────────────────────")
            _print_2col(attack_skills)
        if support_skills:
            print("  ── 보조 스킬 ──────────────────────")
            _print_2col(support_skills)
        print()

# ────────────────────────────────────────────
# 데이터 무결성 검증 (개발용)
# ────────────────────────────────────────────

def validate_skill_data() -> list:
    """
    JOB_SKILL_UNLOCKS에 있는 모든 스킬이 SKILL_META에 정의됐는지 검사.
    반환: 누락된 스킬 이름 리스트 (비어있으면 정상)
    """
    missing = []
    for job, table in Ply_Skill._get_unlocks().items():
        for lv, skills in table.items():
            for sk in skills:
                if sk not in SKILL_META:
                    missing.append(f"{job} Lv{lv}: {sk}")
    return missing


if __name__ == "__main__":
    miss = validate_skill_data()
    if miss:
        print("⚠ SKILL_META에 누락된 스킬:")
        for m in miss:
            print(f"  - {m}")
    else:
        print("✅ 모든 해금 스킬이 SKILL_META에 정의됨")