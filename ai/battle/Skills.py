"""Battle/Skills.py — SKILL_META, execute_skill"""
from __future__ import annotations

from random import randint, random, uniform

from .Entity import EntitySnapshot, Debuff, Buff, StatusEffect
from .Damage import DamageCalc
from .Elements import (
    apply_element_and_react, mage_resonance_on_cast, mage_resonance_mult,
    REACT_PARTNER, ELEMENT_STATUS_TURNS, _current_element,
)
from .EliteKit import BAT_SCREAM_SPD_AMOUNT, BAT_SCREAM_TURNS
from .BossKit import MIDBOSS_RIFT_MULT, MIDBOSS_RIFT_ARM_PEN, RIFT_STATUS, is_boss_or_elite
from .MonsterKit import BAT_WING_SKILL, BAT_WING_ATB_DRAIN, BAT_WING_MP

SKILL_META = {
    "약화1": {
        "mp": 8, "type": "debuff",
        "debuff_stat": "arm",
        "debuff_amount": (0.10, 0.15),
        "debuff_turns": (3, 4)
    },
    "약화2": {
        "mp": 14, "type": "debuff",
        "debuff_stat": "arm",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (4, 5)
    },
    "미약화1": {
        "mp": 8, "type": "debuff",
        "debuff_stat": "sparm",
        "debuff_amount": (0.10, 0.15),
        "debuff_turns": (3, 4)
    },
    "미약화2": {
        "mp": 14, "type": "debuff",
        "debuff_stat": "sparm",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (4, 5)
    },
    "저주1": {
        "mp": 10, "type": "debuff",
        "debuff_stat": "stg",
        "debuff_amount": (0.10, 0.20),
        "debuff_turns": (3, 5)
    },
    "저주2": {
        "mp": 18, "type": "debuff",
        "debuff_stat": "stg",
        "debuff_amount": (0.20, 0.30),
        "debuff_turns": (4, 6)
    },
    "둔화1": {
        "mp": 7, "type": "debuff",
        "debuff_stat": "spd",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (3, 4)
    },
    "둔화2": {
        "mp": 15, "type": "debuff",
        "debuff_stat": "spd",
        "debuff_amount": (0.25, 0.35),
        "debuff_turns": (4, 5)
    },

    "연속공격1": {
        # 다대일 보정: 적 2마리 이상일 때만 전사에게 maxhp 6% 실드 (cap 12%)
        # — 초반 1대2를 "해볼 만하게", 1대3은 여전히 위험하게. 계수는 무변경.
        "mp": 8, "mult": 0.80, "type": "physical", "hits": 2,  # 0.70 → 0.80: 초반 연타 체감 개선
        "multi_shield": 0.06, "multi_shield_cap": 0.12
    },
    "연속공격2": {
        # 스펙: mult 0.70, hits 3 (약간 하향)
        "mp": 13, "mult": 0.70, "type": "physical", "hits": 3
    },
    "강타1": {
        # 처형(6-1): 대상 HP가 30% 이하면 계수 +50% (1.55 → 2.33). 평소엔 연속공격, 마무리는 강타.
        #   몬스터판(고블린 강타1)은 MONSTER_SKILL_META에 개편 전 값으로 고정 — 처형 없음.
        "mp": 10, "mult": 1.55, "type": "physical", "hits": 1,
        "execute_hp": 0.30, "execute_mult": 1.5,
    },
    "강타2": {
        # 스펙: mult 1.80 — 처형 시 2.70
        "mp": 16, "mult": 1.80, "type": "physical", "hits": 1,
        "execute_hp": 0.30, "execute_mult": 1.5,
    },
    "슬래시1": {
        # 전사 광역 생존기 — AoE 딜 + 명중한 적 수만큼 실드 (maxhp 5%/명중, 최대 15%)
        "mp": 12, "mult": 0.65, "type": "physical", "hits": 1, "aoe": True,
        "shield_per_hit": 0.05, "shield_cap": 0.15
    },
    "슬래시2": {
        # maxhp 7%/명중, 최대 21%
        "mp": 18, "mult": 0.80, "type": "physical", "hits": 1, "aoe": True,
        "shield_per_hit": 0.07, "shield_cap": 0.21
    },
    "강화1": {
        # 지속 2 → 3턴(6-1): ATB 턴제에서 2턴 버프는 공격 1~2회분이라 강타 한 번보다 못했다.
        #   유령의 강화1은 MONSTER_SKILL_META(2턴) 그대로.
        "mp": 14, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.15, "buff_turns": 3
    },
    "강화2": {
        "mp": 20, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.25, "buff_turns": 3
    },

    "파이어볼1": {
        "mp": 10, "mult": 1.50, "type": "magical", "hits": 1, "element": "fire"
    },
    "파이어볼2": {
        # 스펙: mult 1.55 (후반 화력 억제)
        "mp": 16, "mult": 1.55, "type": "magical", "hits": 1, "element": "fire"
    },
    "아이스볼릿1": {
        # 확정 둔화(6-2): 확률 30%·10~15% → 100%·−10% 2턴. 계수는 그대로 —
        #   "계수는 낮지만 반드시 늦춘다"로 파이어볼(화력)/라이트닝(대물리)과 역할을 가른다.
        #   빙결 슬라임의 아이스볼릿은 MONSTER_SKILL_META에 개편 전 값으로 고정.
        "mp": 11, "mult": 1.25, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 1.0,
        "debuff_amount": (0.10, 0.10), "debuff_turns": (2, 2)
    },
    "아이스볼릿2": {
        # 확정 둔화 −15% 3턴
        "mp": 17, "mult": 1.45, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 1.0,
        "debuff_amount": (0.15, 0.15), "debuff_turns": (3, 3)
    },
    "라이트닝1": {
        "mp": 12, "mult": 1.55, "type": "magical", "hits": 1, "element": "lightning"
    },
    "라이트닝2": {
        # 스펙: mult 1.60
        "mp": 19, "mult": 1.60, "type": "magical", "hits": 1, "element": "lightning"
    },
    "힐1": {
        "mp": 12, "type": "heal",
        "base_heal": 80, "sp_mult": 1.2, "cap": 0.22
    },
    "힐2": {
        # 스펙: base_heal 130, sp_mult 1.15, cap 0.30 (유지력 억제)
        "mp": 20, "type": "heal",
        "base_heal": 130, "sp_mult": 1.15, "cap": 0.30
    },
    "효율성1": {
        "mp": 14, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.20, "buff_turns": 2
    },
    "효율성2": {
        # 스펙: buff_amount 0.25 (0.35 → 0.25, 후반 무한화력 억제)
        "mp": 22, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.25, "buff_turns": 2
    },

    "몸통박치기1": {
        # 밸런스 패치: 1.4/0.03 → 1.45/0.032 (탱커 Lv10 장기전 완화 — MC: 1v1 10.7턴)
        "mp": 8, "type": "tank_attack",
        "arm_mult": 1.45, "hp_mult": 0.032
    },
    "몸통박치기2": {
        # 밸런스 패치: 1.5/0.035 → 1.55/0.038
        "mp": 13, "type": "tank_attack",
        "arm_mult": 1.55, "hp_mult": 0.038
    },
    "되갚기1": {
        "mp": 10, "type": "counter",
        "counter_mult": 0.5, "arm_mult": 1.0, "cap": 0.18
    },
    "되갚기2": {
        "mp": 16, "type": "counter",
        "counter_mult": 0.6, "arm_mult": 1.2, "cap": 0.25
    },
    "수비태세1": {
        "mp": 12, "type": "buff",
        "buff_stat": "arm", "buff_amount": 0.15, "buff_turns": 2
    },
    "수비태세2": {
        "mp": 18, "type": "buff",
        "buff_stat": "arm", "buff_amount": 0.25, "buff_turns": 2
    },
    "실드": {
        "mp": 16, "type": "shield",
        "shield_mult": 0.20
    },

    "급소찌르기1": {
        # 출혈 중인 대상에게 +15%(6-3): 주사위 3·6 출혈 → 다음 턴 급소찌르기 루프.
        #   암살자의 급소찌르기1은 MONSTER_SKILL_META(보너스 없음) 그대로.
        "mp": 7, "mult": 1.20, "type": "physical", "hits": 1,
        "luc_bonus": 0.8, "bleed_bonus": 0.15
    },
    "급소찌르기2": {
        # 스펙: mult 1.30, luc_bonus 0.8 (후반 폭주 억제)
        "mp": 15, "mult": 1.30, "type": "physical", "hits": 1,
        "luc_bonus": 0.8, "bleed_bonus": 0.15
    },
    "연속찌르기": {
        # 스펙: max_hits 4, base_prob 5, luc_mult 3, prob_decay 20, dmg_decay 0.68
        "mp": 14, "type": "multi_hit",
        "max_hits": 4, "base_prob": 5, "luc_mult": 3,
        "prob_decay": 20, "dmg_decay": 0.68
    },
    "난사1": {
        "mp": 12, "mult": 0.65, "type": "physical", "hits": 1, "aoe": True
    },
    "난사2": {
        "mp": 18, "mult": 0.85, "type": "physical", "hits": 1, "aoe": True
    },
    "추진력": {
        "mp": 13, "type": "buff",
        "buff_stat": "spd", "buff_amount": 0.10, "buff_turns": 2
    },
    # ─────────────────────────────────────────────
    # 신규 스킬 6종 (Combat Content Brief 9·10장 · 11-1 2차 6번) — 직업별 2개
    #   공통 키: requires_element / requires_bleed(대상 조건 — 없으면 시전 불가, 메뉴 회색),
    #            hp_cost_ratio(MP 대신 현재 HP 지불), atb_drain(+_boss/_max_uses), max_uses
    # ─────────────────────────────────────────────
    "화염 폭풍": {
        # 마법사 최초 AoE (9장, Lv7): fire 0.95배 전체, 명중 대상에게 점화 확정.
        #   점화는 maxHP 비례 DoT라 대상이 많을수록 총량이 커진다.
        "mp": 16, "mult": 0.95, "type": "magical", "hits": 1, "aoe": True, "element": "fire",
        "on_hit_status": {"effect_type": "ignite", "turns": ELEMENT_STATUS_TURNS["ignite"], "name": "fire"},
    },
    "원소 폭발": {
        # 마법사 Lv9: 대상에 부착된 원소를 읽어 반응이 성립하는 상대 원소를 주입(REACT_PARTNER).
        #   부착 원소가 없으면 사용 불가. 주입 원소가 공명 단계에도 그대로 반영된다.
        "mp": 15, "mult": 1.2, "type": "magical", "hits": 1, "element": "react",
        "requires_element": True,
    },
    "방패치기": {
        # 전사 Lv8: 물리 0.70배 + 명중 시 대상 ATB −25 (추가 행동권 억제기 — 정규 큐 순서는 못 바꾼다).
        #   보스·엘리트는 −12, 전투당 3회까지만 (4회째부터 피해만) — 6-1 상한 근거.
        "mp": 9, "mult": 0.70, "type": "physical", "hits": 1,
        "atb_drain": 25.0, "atb_drain_boss": 12.0, "atb_drain_max_uses": 3,
    },
    "피의 격노": {
        # 전사 Lv11: MP 대신 현재 HP 15%를 지불(max(1, hp×0.85)) → 3턴간 흡혈 25% (10-4 상한 그대로).
        "mp": 0, "hp_cost_ratio": 0.15, "type": "buff",
        "buff_stat": "lifesteal", "buff_amount": 0.25, "buff_turns": 3,
    },
    "패 고치기": {
        # 도적 Lv8: 이 스킬을 배우면 다음 공격의 주사위가 미리 보인다(pending_dice — 전투 시작·소비 직후 굴림).
        #   시전하면 그 눈을 MP만 쓰고 다시 굴린다 — 턴을 소비하지 않는다(free_action). 전투당 3회.
        #   저장된 눈은 다음 공격(일반공격/공격형 스킬)이 소비한다 — 소급 수정 없음(6-3).
        #   턴을 쓰는 첫 형태는 TestFile/dice_fix_measure.py에서 손해로 측정돼(전체 −1.5p, Lv8 보스 −28p)
        #   6-3의 규칙대로 이 형태로 바꿨다.
        "mp": 6, "type": "dice", "max_uses": 3, "free_action": True,
    },
    "피의 수확": {
        # 도적 Lv19: 단일 대상의 출혈 스택을 전부 소비, 스택당 maxHP 6% 고정 피해(보스·엘리트 3%).
        #   출혈이 없으면 사용 불가. 고정 피해 — 회피·크리·방어 무관, 실드는 적용.
        "mp": 14, "type": "harvest", "per_stack": 0.06, "per_stack_boss": 0.03,
        "requires_bleed": True,
    },

    # ─────────────────────────────────────────────
    # 사제(서포터형 몬스터) 전용 스킬 — 적이 사용
    # 플레이어 스킬 트리에는 등록되지 않음.
    # ─────────────────────────────────────────────
    "홀리볼트": {
        # 사제의 공격 스킬 — 마법 데미지 (약함)
        # 골렘(마법 저항 0.65)에는 잘 안 통하고, 슬라임(마법 +10%)에는 잘 통함
        "mp": 8, "mult": 1.10, "type": "magical", "hits": 1
    },
    "사제축복": {
        # 사제 본인이 사용 안 함. Battlesession._priest_action에서 다른 아군에게 적용.
        # SKILL_META에는 buff 형태로만 정의 (실제 발동은 별도 처리).
        "mp": 12, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.15, "buff_turns": 3
    },
    "사제힐": {
        # 사제의 핵심 — 다른 아군 회복.
        # SKILL_META에는 heal 형태로만 정의 (실제 발동은 Battlesession에서 별도 처리).
        # 자기 자신 X / 가장 HP 비율 낮은 아군 O.
        "mp": 14, "type": "heal",
        "base_heal": 60, "sp_mult": 1.4, "cap": 0.40
    },
}


# ────────────────────────────────────────────
# MONSTER_SKILL_META — 플레이어 전용기를 몬스터가 사용할 때의 별도 계수.
#   같은 스킬명을 SKILL_META와 공유하지만(표시 텍스트 동일), 몬스터가 시전하면
#   이 표의 수치가 우선 적용된다 (execute_skill의 _resolve_meta 참고).
#   플레이어는 MP 자원 제약이 있어 재사용에 비용이 크지만, 몬스터는 매턴 무제한
#   재시전이 가능하므로 1회당 위력을 플레이어판보다 낮게 잡는다.
# ────────────────────────────────────────────
MONSTER_SKILL_META = {
    # ── 6장 역할 분화에서 플레이어판만 바뀐 스킬 — 몬스터판은 개편 전 값으로 고정 ──
    #   (몬스터 개편은 2차 3번, 스킬 분화는 2차 4번 — 원인 분리를 위해 서로 섞지 않는다)
    "강타1": {            # 고블린 킷 — 처형 없음
        "mp": 10, "mult": 1.55, "type": "physical", "hits": 1
    },
    "아이스볼릿1": {      # 빙결 슬라임 킷 — 확률 둔화 그대로
        "mp": 11, "mult": 1.25, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 0.3,
        "debuff_amount": (0.10, 0.15), "debuff_turns": (2, 3)
    },
    "아이스볼릿2": {
        "mp": 17, "mult": 1.45, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 0.5,
        "debuff_amount": (0.15, 0.20), "debuff_turns": (2, 3)
    },
    # 유령 전용
    "강화1": {
        "mp": 10, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.12, "buff_turns": 2
    },
    "연속공격1": {
        "mp": 10, "mult": 0.55, "type": "physical", "hits": 2
    },
    "저주1": {
        "mp": 10, "type": "debuff",
        "debuff_stat": "stg",
        "debuff_amount": (0.08, 0.15),
        "debuff_turns": (2, 3)
    },
    # 암살자 전용
    "난사2": {
        "mp": 12, "mult": 0.55, "type": "physical", "hits": 1, "aoe": True
    },
    "급소찌르기1": {
        "mp": 8, "mult": 1.05, "type": "physical", "hits": 1,
        "luc_bonus": 0.5
    },
    "추진력": {
        "mp": 10, "type": "buff",
        "buff_stat": "spd", "buff_amount": 0.10, "buff_turns": 2
    },
    # 골렘 전용
    "몸통박치기2": {
        "mp": 10, "type": "tank_attack",
        "arm_mult": 1.30, "hp_mult": 0.028
    },
    "수비태세2": {
        "mp": 10, "type": "buff",
        "buff_stat": "arm", "buff_amount": 0.18, "buff_turns": 2
    },
    "실드": {
        "mp": 12, "type": "shield",
        "shield_mult": 0.15
    },
    # 엘리트 골렘(고대 수호 골렘) 전용 — 몬스터만 시전, 플레이어는 배울 수 없음.
    # 몬스터판 몸통박치기2(arm_mult 1.30, hp_mult 0.028)의 1.3배.
    "몸통박치기_강화": {
        "mp": 0, "type": "tank_attack",
        "arm_mult": 1.69, "hp_mult": 0.0364
    },
    # 엘리트 흡혈 박쥐 전용 — 3번째 행동마다 예고 후 사용, 대미지 없이 SPD만 약화.
    "초음파비명": {
        "mp": 0, "type": "debuff",
        "debuff_stat": "spd",
        "debuff_amount": (BAT_SCREAM_SPD_AMOUNT, BAT_SCREAM_SPD_AMOUNT),
        "debuff_turns": (BAT_SCREAM_TURNS, BAT_SCREAM_TURNS),
    },
    # 일반 박쥐 전용 — 날갯소리 (ai/battle/MonsterKit.py). 피해 없이 플레이어 ATB를 깎는다.
    #   type "atb_drain": execute_skill은 MP만 소모하고 0 피해를 돌려주며, ATB 자체는
    #   세션(player_atb)/엔진(ATBSystem)이 들고 있으므로 호출부가 skill_atb_drain()으로 적용한다.
    BAT_WING_SKILL: {
        "mp": BAT_WING_MP, "type": "atb_drain", "atb_drain": BAT_WING_ATB_DRAIN,
    },
    # 중간 보스 전용 — 「대지 균열」 (ai/battle/BossKit.py). 예고(관망) 뒤 다음 행동에 발동.
    #   arm_pen       : 플레이어 ARM을 이 비율만큼 무시 (0.5 = 절반 관통)
    #   on_hit_status : 명중(피해 > 0)했을 때 대상에게 거는 상태이상 — 전용 타입 rift
    #   _강화는 페이즈 2 이후 계수 (1.8 → 2.1), 나머지는 같다
    "대지 균열": {
        "mp": 0, "type": "physical", "mult": MIDBOSS_RIFT_MULT[1], "hits": 1,
        "arm_pen": MIDBOSS_RIFT_ARM_PEN, "on_hit_status": RIFT_STATUS,
    },
    "대지 균열_강화": {
        "mp": 0, "type": "physical", "mult": MIDBOSS_RIFT_MULT[2], "hits": 1,
        "arm_pen": MIDBOSS_RIFT_ARM_PEN, "on_hit_status": RIFT_STATUS,
    },
}


def _resolve_meta(skill_name: str, attacker: EntitySnapshot) -> dict | None:
    """몬스터가 플레이어 전용기를 쓰면 MONSTER_SKILL_META를 우선 조회한다.
    attacker.enemy_type은 플레이어는 항상 "", 몬스터는 항상 값이 있다."""
    if getattr(attacker, "enemy_type", ""):
        meta = MONSTER_SKILL_META.get(skill_name)
        if meta:
            return meta
    return SKILL_META.get(skill_name)


def physical_skill_mult(meta: dict, defender: EntitySnapshot) -> tuple:
    """물리 스킬의 조건부 계수 보정(6장 역할 분화). 반환 (배율, 발동한 태그 목록).
      execute  : meta.execute_hp 이하 HP의 대상 → ×execute_mult (강타 처형)
      bleed    : 출혈 중인 대상 → ×(1 + bleed_bonus) (급소찌르기)
    시전 시점의 대상 상태로 한 번만 판정한다 — execute_skill / execute_single_hit 두 경로가 공유."""
    mult, tags = 1.0, []
    ex_hp = meta.get("execute_hp")
    if ex_hp is not None and defender is not None and defender.maxhp > 0 \
            and defender.hp / defender.maxhp <= ex_hp:
        mult *= meta.get("execute_mult", 1.0)
        tags.append("execute")
    bb = meta.get("bleed_bonus", 0.0)
    if bb and defender is not None and any(
            getattr(e, "effect_type", "") == "bleed" for e in getattr(defender, "status_effects", [])):
        mult *= (1.0 + bb)
        tags.append("bleed")
    return mult, tags


_PHYSICAL_TAG_MSG = {
    "execute": "⚔ 처형! 대상 HP 30% 이하 — 피해 +50%",
    "bleed":   "🩸 출혈 급소! 피해 +15%",
}


def skill_atb_drain(skill_name: str, attacker: EntitySnapshot) -> float:
    """이 스킬이 대상의 ATB에서 깎는 양 (없으면 0). 실전 세션과 튜너 엔진이 같은 값을 읽는다."""
    meta = _resolve_meta(skill_name, attacker) or {}
    return float(meta.get("atb_drain", 0.0) or 0.0)


def consume_atb_drain(skill_name: str, attacker: EntitySnapshot, defender: EntitySnapshot | None) -> float:
    """명중한 ATB 감소기의 실제 감소량 — 보스·엘리트 대상은 atb_drain_boss로 줄고 전투당
    atb_drain_max_uses회까지만(그 뒤 0). 한 번 부를 때마다 횟수를 센다(호출부는 명중 시 1회만 부른다).
    상한이 없는 스킬(날갯소리)은 그대로 atb_drain."""
    meta = _resolve_meta(skill_name, attacker) or {}
    drain = float(meta.get("atb_drain", 0.0) or 0.0)
    if drain <= 0:
        return 0.0
    if defender is not None and is_boss_or_elite(defender) and "atb_drain_boss" in meta:
        max_uses = meta.get("atb_drain_max_uses")
        if max_uses is not None:
            if attacker.atb_drain_uses >= max_uses:
                return 0.0
            attacker.atb_drain_uses += 1
        return float(meta["atb_drain_boss"])
    return drain


def skill_effective_element(meta: dict, defender: EntitySnapshot | None) -> str:
    """스킬이 실제로 부딪히는 원소 — "react"(원소 폭발)는 대상 부착 원소의 상대 원소, 없으면 ""."""
    elem = meta.get("element", "") or ""
    if elem != "react":
        return elem
    if defender is None:
        return ""
    return REACT_PARTNER.get(_current_element(defender), "")


def skill_requirement_error(skill_name: str, attacker: EntitySnapshot,
                            defender: EntitySnapshot | None) -> str:
    """지금 이 스킬을 쓸 수 없는 이유 — ""(가능) / "mp" / "no_element" / "no_bleed" / "max_uses".
    세션의 get_skills(메뉴 회색 처리)·사전 검사, 측정용 AI, execute_skill 안전망이 같은 판정을 쓴다."""
    meta = _resolve_meta(skill_name, attacker)
    if not meta:
        return ""
    cost = max(0, int(round(meta.get("mp", 0) * attacker.mp_cost_multiplier())))
    if attacker.mp < cost:
        return "mp"
    if meta.get("requires_element") and not skill_effective_element(meta, defender):
        return "no_element"
    if meta.get("requires_bleed") and not (defender is not None and any(
            getattr(e, "effect_type", "") == "bleed" for e in getattr(defender, "status_effects", []))):
        return "no_bleed"
    if meta.get("type") == "dice" and attacker.dice_fix_uses >= meta.get("max_uses", 0):
        return "max_uses"
    return ""


SKILL_REQUIREMENT_LABEL = {
    "mp":         "MP 부족",
    "no_element": "대상에 부착된 원소가 없음",
    "no_bleed":   "대상이 출혈 중이 아님",
    "max_uses":   "이번 전투 사용 횟수 소진",
}


def is_free_action(skill_name: str, attacker: EntitySnapshot) -> bool:
    """턴을 소비하지 않는 스킬(패 고치기) — 세션·엔진이 정규 행동 앞에서 따로 처리한다."""
    meta = _resolve_meta(skill_name, attacker) or {}
    return bool(meta.get("free_action"))


def preview_next_dice(attacker: EntitySnapshot) -> int:
    """패 고치기를 배운 도적의 '다음 주사위 미리 보기' — 전투 시작과 눈을 소비한 직후에 굴려 둔다.
    (스킬이 없으면 0 = 미리 보기 없음, 공격 시점에 굴린다.)"""
    if getattr(attacker, "job", "") == "도적" and "패 고치기" in getattr(attacker, "learned_skills", []):
        attacker.pending_dice = randint(1, 6)
    else:
        attacker.pending_dice = 0
    return attacker.pending_dice


def harvest_damage(meta: dict, defender: EntitySnapshot) -> tuple:
    """피의 수확 — 대상의 출혈 스택 수와 고정 피해 (보스·엘리트는 per_stack_boss). 반환 (스택, 피해)."""
    eff = next((e for e in getattr(defender, "status_effects", []) if e.effect_type == "bleed"), None)
    if eff is None:
        return 0, 0
    per = meta["per_stack_boss"] if is_boss_or_elite(defender) else meta["per_stack"]
    return eff.stacks, int(defender.maxhp * per * eff.stacks)


# ────────────────────────────────────────────
# 원소 시스템 — element_queue 기반
# ────────────────────────────────────────────

# 반응 테이블: (큐[0], 큐[1]) → 반응명

def consume_skill_mp(skill_name: str, attacker: EntitySnapshot) -> bool:
    """
    스킬 MP를 1회만 소모한다.
    반환값: True면 MP 부족, False면 정상 소모 완료.
    """
    meta = _resolve_meta(skill_name, attacker)
    if not meta:
        return False

    base_mp_cost = meta.get("mp", 0)
    real_mp_cost = int(round(base_mp_cost * attacker.mp_cost_multiplier()))
    real_mp_cost = max(0, real_mp_cost)

    if attacker.mp < real_mp_cost:
        return True

    attacker.mp -= real_mp_cost
    return False


def roll_multi_hit_count(meta: dict, attacker: EntitySnapshot) -> int:
    """multi_hit(연속찌르기류)의 이번 시전 타수를 굴린다.
    1타는 확정이고, 2타부터는 매 타마다 luc 기반 확률로 이어진다(실패 시 즉시 중단).
    ★ execute_skill의 multi_hit 분기와 ai/battle_session/Player_Actions.py의
      타격별 경로가 이 함수 하나를 공유한다 — 두 곳에 확률식을 두면
      "시뮬과 실전의 타수 분포가 다르다"는 형태로 조용히 어긋난다.
    """
    base_prob  = meta["base_prob"]
    luc_mult   = meta["luc_mult"]
    prob_decay = meta["prob_decay"]
    max_hits   = meta["max_hits"]

    hit_count = 1
    for hit_index in range(1, max_hits):
        prob = max(base_prob, min(85, attacker.luc * luc_mult - hit_index * prob_decay))
        if randint(1, 100) <= prob:
            hit_count += 1
        else:
            break
    return hit_count


def execute_single_hit(
    skill_name: str,
    attacker: EntitySnapshot,
    defender: EntitySnapshot,
    hit_count: int = 1,
) -> tuple[int, bool, bool]:
    """
    연속 타격류(hits>1 physical/magical, multi_hit)의 단일 타격 판정.
    MP/원소/상태이상/실드 적용은 호출부가 처리하고, 여기서는 1타의
    기본 데미지/회피/크리티컬만 계산한다.

    hit_count: 이번 시전의 총 타수 — 유령의 dodge_penalty_per_extra_hit
      (다단히트일수록 회피율 감소)에 쓰인다. physical/magical 경로는
      타격마다 독립 판정이라 1을 유지하고(기존 동작 불변), multi_hit은
      execute_skill의 한 방 계산과 수치를 맞추기 위해 굴린 총 타수를 넘긴다.
    """
    meta = _resolve_meta(skill_name, attacker)
    if not meta:
        return 0, False, False

    stype = meta.get("type", "")

    # multi_hit(연속찌르기류) — execute_skill의 루프 1회분과 동일한 계산.
    #   ★ skill_mult은 표에 없고 항상 1.0 (execute_skill과 같은 값 — 여기서
    #     meta.get("mult", 1.0)을 쓰면 나중에 표에 mult가 붙는 순간 두 경로가
    #     조용히 달라진다).
    if stype == "multi_hit":
        raw, dodge, crit = DamageCalc.physical(
            attacker.effective_stg(),
            attacker.luc,
            defender.effective_arm(),
            defender.luc,
            skill_mult=1.0,
            attacker=attacker,
            defender=defender,
            hit_count=hit_count,
        )
        return int(raw), dodge, crit

    if stype == "physical":
        cond_mult, _tags = physical_skill_mult(meta, defender)   # 처형 · 출혈 급소 (6장)
        raw, dodge, crit = DamageCalc.physical(
            attacker.effective_stg(),
            attacker.luc,
            defender.effective_arm() * (1.0 - meta.get("arm_pen", 0.0)),   # ARM 관통 (대지 균열)
            defender.luc,
            skill_mult=meta.get("mult", 1.0) * cond_mult,
            attacker=attacker,
            defender=defender,
            hit_count=1,
        )
        bonus = meta.get("luc_bonus", 0.0)
        if bonus and not dodge:
            raw += int(attacker.luc * bonus)
        return int(raw), dodge, crit

    if stype == "magical":
        raw, dodge, crit = DamageCalc.magical(
            attacker.sp,
            attacker.luc,
            defender.effective_sparm(),
            defender.luc,
            skill_mult=meta.get("mult", 1.0),
            attacker=attacker,
            defender=defender,
            hit_count=1,
        )
        return int(raw), dodge, crit

    return 0, False, False


def execute_skill(
    skill_name: str,
    attacker: EntitySnapshot,
    defender: EntitySnapshot,
) -> tuple[int, bool, str]:
    meta = _resolve_meta(skill_name, attacker)
    if not meta:
        return 0, False, ""

    base_mp_cost = meta.get("mp", 0)
    real_mp_cost = int(round(base_mp_cost * attacker.mp_cost_multiplier()))
    real_mp_cost = max(0, real_mp_cost)

    if attacker.mp < real_mp_cost:
        return 0, True, ""

    # ── 대상 조건 안전망 (원소 폭발 / 피의 수확 / 패 고치기 횟수) — 호출부가 먼저 거르지만 MP는 지키지 않는다 ──
    req = skill_requirement_error(skill_name, attacker, defender)
    if req and req != "mp":
        return 0, False, ""

    attacker.mp -= real_mp_cost
    stype = meta["type"]
    element = skill_effective_element(meta, defender)     # "react"는 여기서 실제 원소로 확정

    # ── HP 지불 스킬 (피의 격노): 현재 HP 기준, 절대 죽지 않는다 — max(1, hp × 0.85) ──
    hp_cost = meta.get("hp_cost_ratio", 0.0)
    if hp_cost:
        before_hp = attacker.hp
        attacker.hp = max(1.0, attacker.hp * (1.0 - hp_cost))
        if getattr(attacker, "hit_ledger", None) is not None:
            attacker._record_hit("damage", before_hp - attacker.hp, via="cost", element="", reaction="")

    # ── 마법사 원소 공명(6-2) — 시전 1회당 한 번, 원소 마법 스킬만 상태를 바꾼다 ──
    #    (실전 세션과 튜너 엔진이 모두 execute_skill을 거치므로 여기가 공용 훅 자리.
    #     AoE는 세션이 첫 대상만 execute_skill로 처리하므로 역시 1회.)
    resonance_note = mage_resonance_on_cast(attacker, element, stype)

    if stype == "dice":
        # 패 고치기 — 다음 공격 주사위를 미리 굴려 저장. 호출부(세션/엔진)의 주사위 굴림이 소비한다.
        attacker.pending_dice = randint(1, 6)
        attacker.dice_fix_uses += 1
        return 0, False, f"dice:{attacker.pending_dice}"

    if stype == "harvest":
        # 피의 수확 — 출혈 스택 전부 소비 → 스택당 maxHP 비율 고정 피해 (회피·크리·방어 무관)
        stacks, dmg = harvest_damage(meta, defender)
        defender.status_effects = [e for e in defender.status_effects if e.effect_type != "bleed"]
        if hasattr(defender, "_stamp_last_hit"):
            defender._stamp_last_hit("bleed", "")        # 숫자 색: 출혈 계열 (표시 전용)
        return dmg, False, f"harvest:{stacks}"

    if stype == "debuff":
        amt = round(
            meta["debuff_amount"][0]
            + random() * (meta["debuff_amount"][1] - meta["debuff_amount"][0]),
            2
        )
        turns = randint(meta["debuff_turns"][0], meta["debuff_turns"][1])
        defender.apply_debuff(Debuff(
            stat=meta["debuff_stat"],
            amount=amt,
            turns=turns,
            name=skill_name,
        ))
        return 0, False, skill_name

    if stype == "buff":
        attacker.apply_buff(Buff(
            stat=meta["buff_stat"],
            amount=meta["buff_amount"],
            turns=meta["buff_turns"],
            name=skill_name,
        ))
        return 0, False, skill_name

    if stype == "heal":
        heal = meta["base_heal"] + attacker.sp * meta["sp_mult"]
        heal = min(heal, attacker.maxhp * meta["cap"])
        before = attacker.hp
        attacker.hp = min(attacker.maxhp, attacker.hp + int(heal))
        if getattr(attacker, "hit_ledger", None) is not None:   # 표시 전용 장부
            attacker._record_hit("heal", attacker.hp - before)
        return 0, False, "heal"

    if stype == "atb_drain":
        # 피해 없는 ATB 감소기(날갯소리) — MP는 위에서 소모됐고, ATB 적용은 호출부(skill_atb_drain).
        return 0, False, skill_name

    if stype == "shield":
        new_shield = attacker.maxhp * meta["shield_mult"]
        before = attacker.shield
        attacker.shield = max(attacker.shield, new_shield)
        if getattr(attacker, "hit_ledger", None) is not None:   # 표시 전용 장부
            attacker._record_hit("shield", attacker.shield - before)
        return 0, False, "shield"

    if stype == "tank_attack":
        damage = (attacker.effective_arm() * meta["arm_mult"]) + (attacker.maxhp * meta["hp_mult"])
        damage *= uniform(0.9, 1.1)
        _d = int(damage); _em=[]
        _d = apply_element_and_react(attacker, defender, meta.get("element",""), _d, _em)
        return _d, False, ("|".join(_em)) if _em else ""

    if stype == "counter":
        damage = (attacker.last_damage_taken * meta["counter_mult"]) + (attacker.effective_arm() * meta["arm_mult"])
        damage = min(damage, attacker.maxhp * meta["cap"])
        damage *= uniform(0.9, 1.1)
        _d = int(damage); _em=[]
        _d = apply_element_and_react(attacker, defender, meta.get("element",""), _d, _em)
        return _d, False, ("|".join(_em)) if _em else ""


    if stype == "multi_hit":
        total = 0
        dmg_decay = meta["dmg_decay"]
        hit_count = roll_multi_hit_count(meta, attacker)

        # multi_hit은 hit_count 개수만큼 다단히트 →
        # defender의 dodge_penalty_per_extra_hit이 적용되어 유령 회피율 감소.
        for i in range(hit_count):
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(),
                attacker.luc,
                defender.effective_arm(),
                defender.luc,
                skill_mult=1.0,
                attacker=attacker,
                defender=defender,
                hit_count=hit_count,  # 다단히트 정보 전달
            )
            total += int(raw * (dmg_decay ** i))

        # multi_hit 원소 반응
        _elem = meta.get("element", "")
        _msgs: list = []
        if total > 0 or _elem:
            total = apply_element_and_react(attacker, defender, _elem, total, _msgs)
        return total, False, ("|".join(_msgs)) if _msgs else ""

    total = 0
    hits = meta.get("hits", 1)
    cond_mult, cond_tags = (physical_skill_mult(meta, defender) if stype == "physical" else (1.0, []))
    res_mult = mage_resonance_mult(attacker, element) if stype == "magical" else 1.0

    for _ in range(hits):
        if stype == "physical":
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(),
                attacker.luc,
                defender.effective_arm() * (1.0 - meta.get("arm_pen", 0.0)),   # ARM 관통 (대지 균열)
                defender.luc,
                skill_mult=meta.get("mult", 1.0) * cond_mult,    # 처형 · 출혈 급소 (6장)
                attacker=attacker,
                defender=defender,
                hit_count=hits,  # hits>1이면 다단히트로 회피 페널티 적용
            )
            bonus = meta.get("luc_bonus", 0.0)
            if bonus:
                raw += int(attacker.luc * bonus)

        elif stype == "magical":
            raw, _, _ = DamageCalc.magical(
                attacker.sp,
                attacker.luc,
                defender.effective_sparm(),
                defender.luc,
                skill_mult=meta.get("mult", 1.0) * res_mult,     # 원소 공명 단계 배율 (마법사)
                attacker=attacker,
                defender=defender,
                hit_count=hits,
            )
        else:
            return 0, False, ""

        total += int(raw)

    if stype == "magical" and "debuff_stat" in meta and random() <= meta.get("debuff_chance", 0.0):
        amt = round(
            meta["debuff_amount"][0]
            + random() * (meta["debuff_amount"][1] - meta["debuff_amount"][0]),
            2
        )
        turns = randint(meta["debuff_turns"][0], meta["debuff_turns"][1])
        defender.apply_debuff(Debuff(
            stat=meta["debuff_stat"],
            amount=amt,
            turns=turns,
            name=skill_name,
        ))

    # ── 원소 큐 + 반응 + 상태이상 (element는 위에서 확정 — 원소 폭발은 주입 원소) ──
    extra_msgs: list = []
    if total > 0:
        extra_msgs.extend(_PHYSICAL_TAG_MSG[t] for t in cond_tags)      # 처형 / 출혈 급소
        if res_mult > 1.0:
            extra_msgs.append(f"🔮 원소 공명 {attacker.resonance_stack}단계 — 피해 +{int(round((res_mult - 1) * 100))}%")
    if total > 0 or element:
        total = apply_element_and_react(attacker, defender, element, total, extra_msgs)
    # ── 명중 시 부여하는 상태이상 (중간 보스 「대지 균열」의 균열) ──
    #    total 0 = 회피(또는 무효)이므로 걸리지 않는다. 실드에 전부 흡수돼도 명중은 명중이다.
    #    적용 규칙(중첩 없이 남은 턴 갱신)은 apply_status_effect가 그대로 담당.
    on_hit = meta.get("on_hit_status")
    if on_hit and total > 0 and hasattr(defender, "apply_status_effect"):
        defender.apply_status_effect(StatusEffect(**on_hit))
    info = skill_name if extra_msgs else (skill_name if "debuff_stat" in meta else "")
    return total, False, (info + "|" + "|".join(extra_msgs)) if extra_msgs else info


# ────────────────────────────────────────────
# 아이템
