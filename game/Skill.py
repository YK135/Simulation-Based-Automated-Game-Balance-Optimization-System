"""
Skill.py — 직업별 스킬 트리 시스템
레벨업 시 자동 스킬 습득 + 상위 스킬 대체
"""
from __future__ import annotations

try:
    from ai.battle import SKILL_META
except ModuleNotFoundError:
    try:
        from ai.battle import SKILL_META
    except Exception:
        SKILL_META = {}

# 스킬 해금 테이블 단일 소스: game/Lv.py JOB_SKILL_UNLOCKS
# 순환 import 방지 — 모듈 로드 시점이 아닌 최초 접근 시 lazy 로드


# 스킬 2택 1 선택 화면의 한 줄 설명 (game/Lv.py JOB_SKILL_CHOICES의 18종) — 수치는 ai/battle/Skills.py가 원본
SKILL_BRIEF = {
    # 전사
    "피의 격노":   "현재 HP 15%를 내고 3턴간 흡혈 25% — 흡혈 특화",
    "방패치기":    "물리 0.70배 + 대상 ATB −25 (보스·엘리트 −12, 전투당 3회) — 템포 특화",
    "광풍 베기":   "적 전체 물리 0.90배 + 명중한 적마다 흡혈 8% — 회복형 광역",
    "슬래시2":     "적 전체 물리 0.80배 + 명중 수만큼 실드(최대 21%) — 실드형 광역",
    "피의 맹세":   "3턴간 흡혈 40%, 끝나면 현재 HP 20% 지불 — 고위험 고보상",
    "철벽 의지":   "3턴간 받는 피해 −20% + 흡혈량 2배 — 안정형",
    # 마법사
    "연쇄 번개":   "적 전체 번개 0.80배, 원소가 붙은 적은 ×1.3 — 광역 과부하",
    "파이어볼2":   "단일 화염 1.55배 — 파이어볼1을 대체하는 단일 화력",
    "마나 장막":   "2턴간 받는 피해의 50%를 MP로 대신 냄 — MP로 막기",
    "힐2":         "HP 130 + SP×1.15 회복(최대 30%) — 힐1을 대체하는 회복",
    "서리 결계":   "3턴간 나를 공격한 적에게 ice + SPD −10% — 반격형 원소",
    "아이스볼릿2": "단일 빙결 1.45배 + 확정 둔화 −15% 3턴 — 제어 강화",
    # 도적
    "약점 표식":   "3턴간 대상에게 주사위 5도 치명타 + 받는 피해 +8% — 확률 조작",
    "둔화2":       "대상 SPD −25~35% 4~5턴 — 둔화1을 대체하는 속도 제어",
    "혈흔 추적":   "물리 1.0배, 출혈 중인 적에게 명중하면 ATB +25 — 출혈 템포",
    "난사2":       "적 전체 물리 0.85배 — 난사1을 대체하는 즉발 광역",
    "칼날 폭풍":   "적 전체 물리 0.70배 × 2타, 타격마다 출혈 40% — 출혈 축적 광역",
    "연막":        "2턴간 회피 +35%, 회피하면 패 고치기 무료 재굴림 — 회피 생존",
}


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
        "미약화2": "미약화1",
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