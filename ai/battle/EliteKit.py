"""
Battle/EliteKit.py — 엘리트 몬스터 패턴 수치/판단 (챕터 기준)
─────────────────────────────────────────────
MonsterKit.py와 같은 계층이지만 별도 파일로 분리 — get_monster_kit()의
기존 시그니처/호출부를 건드리지 않기 위함.

실행(대미지 적용, 버프/디버프 부여, 로그 출력)은
ai/battle_session/Elite_Actions.py가 담당하고, 이 파일은 수치 상수와
"이번 행동을 강제할지" 판단 로직만 담는다.
"""
from __future__ import annotations

from .Actions import Action

# ── 고블린 대장 ──
GOBLIN_START_BUFF_AMOUNT = 0.10
GOBLIN_START_BUFF_TURNS = 2
GOBLIN_RAGE_HP_THRESHOLD = 0.50
GOBLIN_RAGE_STG_AMOUNT = 0.15
GOBLIN_RAGE_DEF_AMOUNT = 0.15

# ── 흡혈 박쥐 ──
BAT_LIFESTEAL_RATIO = 0.20
BAT_LIFESTEAL_CAP_RATIO = 0.10
BAT_SCREAM_INTERVAL = 3
BAT_SCREAM_SPD_AMOUNT = 0.20
BAT_SCREAM_TURNS = 2

# ── 증식 슬라임 ──
SLIME_SPLIT_COUNT = 2
SLIME_SPLIT_HP_RATIO = 0.30
SLIME_SPLIT_STAT_RATIO = 0.65

# ── 원소 슬라임(화염/빙결/번개) ──
FIRE_SLIME_STACK_THRESHOLD = 3
LIGHTNING_SLIME_STACK_THRESHOLD = 3
LIGHTNING_SLIME_OVERLOAD_SPD_AMOUNT = 0.20
LIGHTNING_SLIME_OVERLOAD_SPD_TURNS = 1
ICE_SLIME_ARMOR_REDUCTION = 0.15   # physical_resist 배율 (1 - 0.15)
ICE_SLIME_BREAK_SPARM_AMOUNT = 0.20
ICE_SLIME_BREAK_TURNS = 2

# ── 고대 수호 골렘 ──
# phase: 0=수비태세, 1=충전예고, 2=공격(다음 행동에서 발동)
GOLEM_PHASE_GUARD = 0
GOLEM_PHASE_CHARGE = 1
GOLEM_PHASE_STRIKE = 2

# ── 그림자 암살자 ──
ASSASSIN_MARK_INTERVAL = 3
ASSASSIN_MARK_TURNS = 2
ASSASSIN_MARK_BONUS = 0.25
ASSASSIN_RETREAT_HP_THRESHOLD = 0.30

# ── 타락한 고위 사제 (2단계: 평시 → 준비 → 발동 후 평시로 복귀) ──
PRIEST_REVIVE_HP_RATIO = 0.25
PRIEST_PHASE_IDLE = 0
PRIEST_PHASE_PREPARING = 1


def elite_forced_action(attacker, defender, chapter: int = 1):
    """
    엘리트 리더가 이번 행동에 특정 스킬/공격을 강제로 써야 하는지 판단.
    강제할 게 없으면 None (호출부가 평소 EnemyAI.decide()로 폴백).

    박쥐(비명 예고 소진)/암살자(표식 부여 다음 행동)/화염·번개 슬라임
    (스택 3 도달)만 여기서 다루고, 골렘/사제는 전용 분기(Elite_Actions.py)가
    자체 처리하므로 이 함수를 거치지 않는다.
    """
    et = getattr(attacker, "enemy_type", "")

    if et == "박쥐":
        if getattr(attacker, "elite_phase", 0) == 1:
            attacker.elite_phase = 0
            return Action("skill", "초음파비명")
        return None

    if et == "암살자":
        if getattr(attacker, "elite_phase", 0) == 1:
            attacker.elite_phase = 0
            return Action("skill", "급소찌르기1")
        return None

    if et == "화염 슬라임":
        if getattr(attacker, "elite_pattern_turn", 0) >= FIRE_SLIME_STACK_THRESHOLD:
            attacker.elite_pattern_turn = 0
            return Action("skill", "파이어볼2" if chapter >= 2 else "파이어볼1")
        return None

    if et == "번개 슬라임":
        if getattr(attacker, "elite_pattern_turn", 0) >= LIGHTNING_SLIME_STACK_THRESHOLD:
            attacker.elite_pattern_turn = 0
            return Action("skill", "라이트닝2" if chapter >= 2 else "라이트닝1")
        return None

    return None
