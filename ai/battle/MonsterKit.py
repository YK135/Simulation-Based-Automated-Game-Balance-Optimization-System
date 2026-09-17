"""
Battle/MonsterKit.py — 몬스터별 행동 확률 + 스킬 세트 (챕터 기준)
─────────────────────────────────────────────
몬스터별 "일반 공격 / 스킬 사용 / 대기" 확률과 스킬 후보 목록을 데이터로 정의한다.
사제는 서포터 전용 로직(BattleSession._priest_action)이 따로 있어 여기 없음.

키: (enemy_type, chapter) → {"attack_prob", "skill_prob", "watch_prob", "skills"}
  - 세 확률의 합은 1.0.
  - "skills"는 균등 가중치 후보 목록 — MP가 부족한 스킬은 자동 제외.
  - 플레이어 전용기(강화1/연속공격1/저주1/난사2/급소찌르기1/추진력/
    몸통박치기2/수비태세2/실드)를 재사용하는 항목은 표시 스킬명은 같지만
    실제 수치는 Skills.MONSTER_SKILL_META가 우선 적용된다.

아래쪽 「일반 몬스터 정체성 규칙」(Combat Content Brief 2장 · 11-1 2차 3번)은
킷 표와 같은 계층의 수치·판단 함수다 — 실제 상태 변경·메시지·TurnLog는
ai/battle_session/Enemy_Actions.py(실전)와 ai/battle/Engine.py(튜너 1v1)가
같은 함수를 불러 처리한다(실전/시뮬 경로를 포크하지 않기 위해 한 곳에 둔다).
"""
from __future__ import annotations

from .EliteKit import BAT_LIFESTEAL_RATIO, BAT_LIFESTEAL_CAP_RATIO

MONSTER_KITS: dict[tuple[str, int], dict] = {
    ("고블린", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["강타1"],
    },

    # 박쥐 — 2장 정체성 교체: 파이어볼·미약화 제거, 흡혈(일반공격) + 날갯소리(ATB −12).
    #   엘리트 흡혈 박쥐(흡혈 20%·초음파비명)의 축소 예습판. 확률은 그대로.
    ("박쥐", 1): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["날갯소리", "약화1"],
    },
    ("박쥐", 2): {
        "attack_prob": 0.65, "skill_prob": 0.35, "watch_prob": 0.0,
        "skills": ["날갯소리", "약화1"],
    },

    ("슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["둔화1"],
    },

    ("화염 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["파이어볼1"],
    },
    ("화염 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["파이어볼2", "둔화1"],
    },

    ("빙결 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["아이스볼릿1"],
    },
    ("빙결 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["아이스볼릿2", "둔화1"],
    },

    ("번개 슬라임", 1): {
        "attack_prob": 0.80, "skill_prob": 0.20, "watch_prob": 0.0,
        "skills": ["라이트닝1"],
    },
    ("번개 슬라임", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["라이트닝2", "둔화1"],
    },

    ("골렘", 2): {
        "attack_prob": 0.70, "skill_prob": 0.25, "watch_prob": 0.05,
        "skills": ["몸통박치기2", "수비태세2", "실드"],
    },

    ("유령", 2): {
        "attack_prob": 0.70, "skill_prob": 0.30, "watch_prob": 0.0,
        "skills": ["강화1", "연속공격1", "저주1"],
    },

    ("암살자", 2): {
        "attack_prob": 0.65, "skill_prob": 0.35, "watch_prob": 0.0,
        "skills": ["난사2", "급소찌르기1", "추진력"],
    },
}


def get_monster_kit(enemy_type: str, chapter: int = 1) -> dict | None:
    """(enemy_type, chapter) → 없으면 챕터2 → 챕터1 순으로 폴백.
    정의 자체가 없는 타입(보스 등)은 None → 호출부가 기존 휴리스틱으로 폴백."""
    kit = MONSTER_KITS.get((enemy_type, chapter))
    if kit is not None:
        return kit
    kit = MONSTER_KITS.get((enemy_type, 2))
    if kit is not None:
        return kit
    return MONSTER_KITS.get((enemy_type, 1))


# ════════════════════════════════════════════════════════════
# 일반 몬스터 정체성 규칙 (Combat Content Brief 2장 · 11-1 2차 3번)
#   원칙: 몬스터 하나당 "기억되는 규칙" 하나, 일반판은 엘리트판의 축소 예습.
#   슬라임·원소 슬라임·암살자·유령은 보류(2차 3번 범위 밖).
# ════════════════════════════════════════════════════════════

# ── 고블린 — 무리 전술 / 겁쟁이 ──
# 같은 전투에 살아있는 고블린이 2마리 이상이면 각자 STG +8%/추가 1마리 (최대 +16%).
# 한 마리가 죽거나 달아나면 즉시 다시 센다 (EntitySnapshot.pack_bonus — 세션이 동기화).
GOBLIN_TYPE = "고블린"
GOBLIN_PACK_STG_PER_ALLY = 0.08
GOBLIN_PACK_STG_CAP = 0.16
# HP 15% 이하 + 다른 고블린이 이미 죽은(달아난) 상태면 도주 시도 — 전투당 1회, 성공하면
# 그 개체의 보상은 사라진다(reward_eligible=False). 판정은 플레이어 도주와 같은
# Engine._escape_chance(자기 SPD / 상대 SPD) 표를 쓴다. 엘리트 리더(고블린 대장)는 안 달아난다.
GOBLIN_FLEE_HP_RATIO = 0.15

# ── 박쥐 — 흡혈 / 날갯소리 ──
# 일반공격 피해의 10%를 회복, 1회 상한 자기 maxHP 5% (엘리트 흡혈 박쥐: 20% / 10% — EliteKit).
BAT_TYPE = "박쥐"
NORMAL_BAT_LIFESTEAL_RATIO = 0.10
NORMAL_BAT_LIFESTEAL_CAP_RATIO = 0.05
# 날갯소리 — 피해 없이 플레이어 ATB를 깎는다 (2장: "오래 끌면 안 되는 적" + ATB 이월 체감의 첫 접점).
BAT_WING_SKILL = "날갯소리"
BAT_WING_ATB_DRAIN = 12.0
BAT_WING_MP = 6

# ── 사제 — 약식 소생 ──
# 일반 사제도 전투당 1회, 죽은 아군을 maxHP 10%로 되살린다 (엘리트 의식은 25% — EliteKit).
# 예고·인터럽트 없이 자기 행동으로 즉시 발동한다는 점이 "약식"이다.
PRIEST_TYPE = "사제"
PRIEST_QUICK_REVIVE_HP_RATIO = 0.10
PRIEST_QUICK_REVIVE_SKILL = "약식 소생"


def goblin_pack_bonus(alive_goblins: int) -> float:
    """살아있는 고블린 수 → 각자에게 붙는 STG 가산 비율 (0 / 0.08 / 0.16)."""
    if alive_goblins < 2:
        return 0.0
    return min(GOBLIN_PACK_STG_CAP, GOBLIN_PACK_STG_PER_ALLY * (alive_goblins - 1))


def is_goblin(en) -> bool:
    return getattr(en, "enemy_type", "") == GOBLIN_TYPE


def goblin_wants_to_flee(goblin, enemies: list) -> bool:
    """겁쟁이 조건: 일반 고블린 · HP ≤ 15% · 같은 전투의 다른 고블린이 이미 죽었거나 달아남 ·
    아직 도주를 시도한 적 없음. (판정 확률은 호출부가 굴린다.)"""
    if not is_goblin(goblin) or getattr(goblin, "elite_leader", False):
        return False
    if getattr(goblin, "flee_attempted", False) or goblin.hp <= 0 or goblin.maxhp <= 0:
        return False
    if goblin.hp / goblin.maxhp > GOBLIN_FLEE_HP_RATIO:
        return False
    return any(is_goblin(e) and e is not goblin and e.hp <= 0 for e in enemies)


def bat_lifesteal_amount(bat, hp_damage: float) -> float:
    """박쥐(일반/엘리트)가 준 HP 피해로 회복할 양 — 비율 + 1회 상한. 상한은 자기 maxHP 기준."""
    if hp_damage <= 0:
        return 0.0
    if getattr(bat, "elite_leader", False):
        ratio, cap = BAT_LIFESTEAL_RATIO, BAT_LIFESTEAL_CAP_RATIO
    else:
        ratio, cap = NORMAL_BAT_LIFESTEAL_RATIO, NORMAL_BAT_LIFESTEAL_CAP_RATIO
    return min(hp_damage * ratio, bat.maxhp * cap)
