"""
Battle/Relics.py — 유물의 전투 효과 (Combat Content Brief 7장 · 11-1 2차 7번)
─────────────────────────────────────────────
수치 상수와 전투 안에서 쓰는 순수 함수만 둔다 — 실전(ai/Battlesession.py)과
튜너 엔진(ai/battle/Engine.py)이 같은 함수를 부른다. 이름·설명·가격·선택 규칙처럼
전투 밖의 것은 game/Relics.py(이 모듈의 상수를 읽는다).

유물 id — 공용 8종 (브리프 7장 「유물 확장」, 직업 전용은 아래 JOB_RELIC_IDS):
  hourglass       깨진 모래시계    — 전투 종료 시 잔여 ATB가 2배로 이월
  greed_seal      탐욕의 인장      — 골드 획득 +40%, 포션 슬롯 −1 (game/Inventory.py · app/Battle.py)
  frost_mark      서리 사냥꾼의 각인 — ice가 부착된 적에게 주는 물리 피해 +15%, 파쇄 시 ATB +5
  priest_remains  사제의 유해      — 전투당 1회, HP가 0이 될 때 최대 HP 20%로 부활
  mirror_shard    거울 파편        — 내가 받는 디버프도, 내가 거는 디버프도 지속 −1턴 (Entity.apply_debuff)
  prophecy_book   예언서           — 적의 예고 배지가 한 행동 먼저 뜬다 (표시 전용 — State._pattern_badges)
  loot_sack       전리품 자루      — 포션 슬롯 +1 (탐욕의 인장과 정확히 상쇄된다)
  travelers_map   여행자의 지도    — 상점 "아이템" 가격 −20% (유물 가격은 제외 — app/Map.py)

직업 전용 12종 (JOB_RELIC_IDS) — 전부 그 직업이 이미 가진 축의 상한·대가만 건드린다:
  전사   iron_heart 무쇠 심장 / hungry_blade 굶주린 칼날 / executioner_mark 처형인의 각인 / beast_blood 짐승의 피
  마법사 resonance_crystal 공명의 수정 / mana_circuit 마나 회로 / frozen_time 얼어붙은 시간 / ember_remnant 화염의 잔재
  도적   loaded_dice 납으로 만든 주사위 / bleed_dagger 사혈 단검 / shadow_step 그림자 걸음 / target_manual 표적 안내서
탱커 전용은 만들지 않는다 — 탱커는 생성 화면에서 잠겨 있다(사용자 결정 2026-09-20).
"""
from __future__ import annotations

RELIC_HOURGLASS = "hourglass"
RELIC_GREED_SEAL = "greed_seal"
RELIC_FROST_MARK = "frost_mark"
RELIC_PRIEST_REMAINS = "priest_remains"
RELIC_MIRROR_SHARD = "mirror_shard"
RELIC_PROPHECY_BOOK = "prophecy_book"
RELIC_LOOT_SACK = "loot_sack"
RELIC_TRAVELERS_MAP = "travelers_map"

# 공용 풀 — 상점에 진열되고 모든 직업에게 제시된다
COMMON_RELIC_IDS = (
    RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS,
    RELIC_MIRROR_SHARD, RELIC_PROPHECY_BOOK, RELIC_LOOT_SACK, RELIC_TRAVELERS_MAP,
)
# ── 직업 전용 12종 ──
RELIC_IRON_HEART = "iron_heart"
RELIC_HUNGRY_BLADE = "hungry_blade"
RELIC_EXECUTIONER_MARK = "executioner_mark"
RELIC_BEAST_BLOOD = "beast_blood"

RELIC_RESONANCE_CRYSTAL = "resonance_crystal"
RELIC_MANA_CIRCUIT = "mana_circuit"
RELIC_FROZEN_TIME = "frozen_time"
RELIC_EMBER_REMNANT = "ember_remnant"

RELIC_LOADED_DICE = "loaded_dice"
RELIC_BLEED_DAGGER = "bleed_dagger"
RELIC_SHADOW_STEP = "shadow_step"
RELIC_TARGET_MANUAL = "target_manual"

JOB_RELIC_IDS = {
    "전사":   (RELIC_IRON_HEART, RELIC_HUNGRY_BLADE, RELIC_EXECUTIONER_MARK, RELIC_BEAST_BLOOD),
    "마법사": (RELIC_RESONANCE_CRYSTAL, RELIC_MANA_CIRCUIT, RELIC_FROZEN_TIME, RELIC_EMBER_REMNANT),
    "도적":   (RELIC_LOADED_DICE, RELIC_BLEED_DAGGER, RELIC_SHADOW_STEP, RELIC_TARGET_MANUAL),
}

RELIC_IDS = COMMON_RELIC_IDS + tuple(r for ids in JOB_RELIC_IDS.values() for r in ids)

HOURGLASS_ATB_MULT = 2.0
GREED_GOLD_BONUS = 0.40
GREED_POTION_SLOT_PENALTY = 1
FROST_MARK_PHYS_BONUS = 0.15
FROST_MARK_SHATTER_ATB = 5.0
REMAINS_REVIVE_HP_RATIO = 0.20
MIRROR_SHARD_TURN_CUT = 1        # 거는 쪽·받는 쪽 각각 1턴 (둘 다 가진 경우는 없다 — 적은 유물이 없다)
LOOT_SACK_POTION_SLOT_BONUS = 1
TRAVELERS_MAP_DISCOUNT = 0.20
PROPHECY_TELEGRAPH_LEAD = 1      # 예고를 몇 "행동" 먼저 배지에 띄우는가 (표시 전용)

# 전사
IRON_HEART_SHIELD_RATIO = 0.12   # 전투 시작 시 maxHP의 이만큼을 실드로 (전투당 1회 = 전투 시작)
HUNGRY_BLADE_KILL_HEAL = 0.08    # 적 처치 시 maxHP 회복 비율
HUNGRY_BLADE_MAXHP_COST = 0.10   # 대가 — 획득 시점의 maxHP를 이만큼 영구히 깎는다
EXECUTIONER_HP_RATIO = 0.25      # 대상 HP가 이 비율 이하일 때
EXECUTIONER_BONUS = 0.20         #   주는 피해 +20%
BEAST_BLOOD_LIFESTEAL_CAP = 0.06 # 흡혈 1회 상한 maxHP 4% → 6%
# 마법사
RESONANCE_CRYSTAL_MAX_STACK = 4  # 원소 공명 최대 스택 3 → 4
MANA_CIRCUIT_MP = 5              # 반응이 터질 때마다 MP 회복
FROZEN_TIME_SLOW_BONUS = 1       # 내가 거는 둔화(spd 디버프) 지속 +1턴
EMBER_REMNANT_IGNITE_BONUS = 1   # 내가 거는 점화 지속 +1틱
# 도적
LOADED_DICE_FLOOR = 4            # 주사위 눈 1이 나오면 이 값으로
BLEED_DAGGER_STACK_MAX = 4       # 출혈 최대 스택 3 → 4
SHADOW_STEP_DODGE_ATB = 15.0     # 회피 성공 시 ATB
# target_manual: 적 처치 시 다음 공격 확정 치명타 (전투당 1회 — 세션이 플래그를 관리)


def has_relic(entity, relic_id: str) -> bool:
    return relic_id in (getattr(entity, "relics", None) or ())


def relic_atb_carry(entity, atb: float) -> float:
    """전투 종료 시 다음 전투로 이월할 ATB — 깨진 모래시계면 2배."""
    atb = max(0.0, float(atb))
    return atb * HOURGLASS_ATB_MULT if has_relic(entity, RELIC_HOURGLASS) else atb


def frost_mark_mult(attacker, defender) -> float:
    """서리 사냥꾼의 각인 — ice가 부착된 대상에게 주는 물리 피해 배율 (Elements 물리 분기가 부른다)."""
    if not has_relic(attacker, RELIC_FROST_MARK):
        return 1.0
    q = getattr(defender, "element_queue", None) or []
    return 1.0 + FROST_MARK_PHYS_BONUS if q and q[-1] == "ice" else 1.0


def frost_mark_on_shatter(attacker) -> float:
    """파쇄를 터뜨린 공격자에게 줄 ATB — 세션/엔진이 행동 뒤에 더한다 (_pending_atb_bonus)."""
    if not has_relic(attacker, RELIC_FROST_MARK):
        return 0.0
    attacker._pending_atb_bonus = getattr(attacker, "_pending_atb_bonus", 0) + FROST_MARK_SHATTER_ATB
    return FROST_MARK_SHATTER_ATB


def relic_try_revive(entity) -> float:
    """사제의 유해 — HP가 0 이하일 때 전투당 1회 최대 HP 20%로 되살린다. 반환: 회복량(0이면 미발동)."""
    if entity.hp > 0 or not has_relic(entity, RELIC_PRIEST_REMAINS) or getattr(entity, "relic_revive_used", False):
        return 0.0
    entity.relic_revive_used = True
    before = entity.hp
    entity.hp = entity.maxhp * REMAINS_REVIVE_HP_RATIO
    if getattr(entity, "hit_ledger", None) is not None:
        entity._record_hit("heal", entity.hp - before, via="relic", element="", reaction="")
    return entity.hp - before


def relic_gold_mult(relics) -> float:
    """탐욕의 인장 — 골드 획득 배율 (app/Battle.py가 보상 계산 뒤에 곱한다)."""
    return 1.0 + GREED_GOLD_BONUS if RELIC_GREED_SEAL in (relics or ()) else 1.0


def relic_potion_slot_penalty(relics) -> int:
    """포션 슬롯 증감의 합 — 용량에서 뺄 값이라 음수면 슬롯이 늘어난다.
    탐욕의 인장 +1(감소) · 전리품 자루 −1(증가) — 둘 다 가지면 정확히 상쇄된다.
    (game/Inventory.py의 potion_capacity()가 max(1, 기본 − 이 값)으로 쓴다)"""
    owned = set(relics or ())
    penalty = 0
    if RELIC_GREED_SEAL in owned:
        penalty += GREED_POTION_SLOT_PENALTY
    if RELIC_LOOT_SACK in owned:
        penalty -= LOOT_SACK_POTION_SLOT_BONUS
    return penalty


def relic_debuff_turns(caster, target, turns: int, kind: str = "") -> int:
    """디버프·상태이상의 지속 턴 보정. 최소 1턴은 남긴다.

    거울 파편 : 거는 쪽이 가졌으면 −1턴(대가), 받는 쪽이 가졌으면 −1턴(이득)
    얼어붙은 시간 : 내가 거는 둔화(spd 디버프) +1턴
    화염의 잔재   : 내가 거는 점화(ignite) +1틱

    kind는 Debuff.stat 또는 StatusEffect.effect_type — Entity.apply_debuff/
    apply_status_effect가 자동으로 넘기므로 호출부가 따로 신경 쓸 게 없다.
    caster를 모르면 None이고, 그때는 받는 쪽만 본다. 유물을 아무도 안 가졌으면
    turns가 그대로 돌아오므로 기존 전투 계산은 불변이다."""
    turns = int(turns)
    bonus = 0
    if kind == "spd" and has_relic(caster, RELIC_FROZEN_TIME):
        bonus += FROZEN_TIME_SLOW_BONUS
    if kind == "ignite" and has_relic(caster, RELIC_EMBER_REMNANT):
        bonus += EMBER_REMNANT_IGNITE_BONUS
    cut = 0
    if has_relic(caster, RELIC_MIRROR_SHARD):
        cut += MIRROR_SHARD_TURN_CUT
    if has_relic(target, RELIC_MIRROR_SHARD):
        cut += MIRROR_SHARD_TURN_CUT
    if not bonus and not cut:
        return turns
    return max(1, turns + bonus - cut)


def relic_job_of(relic_id: str) -> str:
    """이 유물이 어느 직업 전용인지. 공용이면 빈 문자열."""
    for job, ids in JOB_RELIC_IDS.items():
        if relic_id in ids:
            return job
    return ""


# ── 전사 ──

def relic_battle_start_shield(entity) -> float:
    """무쇠 심장 — 전투 시작 시 실드. 반환: 추가된 양(0이면 미발동)."""
    if not has_relic(entity, RELIC_IRON_HEART):
        return 0.0
    amount = entity.maxhp * IRON_HEART_SHIELD_RATIO
    entity.shield = getattr(entity, "shield", 0.0) + amount
    return amount


def relic_on_kill_heal(entity) -> float:
    """굶주린 칼날 — 적 처치 시 회복. 반환: 실제 회복량(0이면 미발동)."""
    if not has_relic(entity, RELIC_HUNGRY_BLADE) or entity.hp <= 0:
        return 0.0
    before = entity.hp
    entity.hp = min(entity.maxhp, entity.hp + entity.maxhp * HUNGRY_BLADE_KILL_HEAL)
    healed = entity.hp - before
    if healed > 0 and getattr(entity, "hit_ledger", None) is not None:
        entity._record_hit("heal", healed, via="relic", element="", reaction="")
    return healed


def relic_maxhp_cost_mult(relic_id: str) -> float:
    """유물을 얻는 순간 maxHP에 곱할 값 — 굶주린 칼날의 대가. 다른 유물은 1.0.
    ★ 획득 시점에 한 번만 적용한다(app/Shared._grant_relic). 이후 레벨업 증가분은
      깎지 않으므로, 늦게 얻을수록 체감 비용이 작아진다 — 의도된 절충."""
    return 1.0 - HUNGRY_BLADE_MAXHP_COST if relic_id == RELIC_HUNGRY_BLADE else 1.0


def relic_execute_mult(attacker, defender) -> float:
    """처형인의 각인 — 대상 HP가 25% 이하면 피해 배율. (DamageCalc._calc이 부른다)"""
    if not has_relic(attacker, RELIC_EXECUTIONER_MARK) or defender is None:
        return 1.0
    maxhp = getattr(defender, "maxhp", 0) or 0
    if maxhp <= 0 or defender.hp / maxhp > EXECUTIONER_HP_RATIO:
        return 1.0
    return 1.0 + EXECUTIONER_BONUS


def relic_lifesteal_hit_cap(attacker, base_ratio: float) -> float:
    """짐승의 피 — 흡혈 1회 상한 비율."""
    return BEAST_BLOOD_LIFESTEAL_CAP if has_relic(attacker, RELIC_BEAST_BLOOD) else base_ratio


# ── 마법사 ──

def relic_resonance_max(attacker, base_max: int) -> int:
    """공명의 수정 — 원소 공명 최대 스택."""
    return RESONANCE_CRYSTAL_MAX_STACK if has_relic(attacker, RELIC_RESONANCE_CRYSTAL) else base_max


def relic_mana_circuit(attacker) -> int:
    """마나 회로 — 원소 반응이 터질 때 MP 회복. 반환: 실제 회복량(0이면 미발동)."""
    if not has_relic(attacker, RELIC_MANA_CIRCUIT):
        return 0
    before = attacker.mp
    attacker.mp = min(attacker.maxmp, attacker.mp + MANA_CIRCUIT_MP)
    return int(attacker.mp - before)


# ── 도적 ──

def relic_dice_roll(attacker, dice: int) -> int:
    """납으로 만든 주사위 — 1이 나오면 4로. 굴림 지점마다 이 함수를 거친다."""
    if dice == 1 and has_relic(attacker, RELIC_LOADED_DICE):
        return LOADED_DICE_FLOOR
    return dice


def relic_bleed_stack_max(caster, base_max: int) -> int:
    """사혈 단검 — 출혈 최대 스택. 스택은 대상에 쌓이지만 상한은 거는 쪽의 유물이 정한다."""
    return BLEED_DAGGER_STACK_MAX if has_relic(caster, RELIC_BLEED_DAGGER) else base_max


def relic_dodge_atb(entity) -> float:
    """그림자 걸음 — 회피에 성공했을 때 얻는 ATB (0이면 미발동)."""
    return SHADOW_STEP_DODGE_ATB if has_relic(entity, RELIC_SHADOW_STEP) else 0.0


def relic_arm_kill_crit(entity) -> bool:
    """표적 안내서 — 적을 처치하면 "다음 공격 확정 치명타"를 장전한다(전투당 1회).
    반환 True면 이번에 장전됐다(메시지용)."""
    if not has_relic(entity, RELIC_TARGET_MANUAL):
        return False
    if getattr(entity, "relic_crit_used", False) or getattr(entity, "relic_crit_armed", False):
        return False
    entity.relic_crit_armed = True
    return True


def relic_take_guaranteed_crit(attacker) -> bool:
    """장전된 확정 치명타를 소비한다. 회피한 공격에서는 부르지 않는다(DamageCalc이 회피 후에 부름)."""
    if attacker is None or not getattr(attacker, "relic_crit_armed", False):
        return False
    attacker.relic_crit_armed = False
    attacker.relic_crit_used = True
    return True


def relic_telegraph_lead(relics) -> int:
    """예언서 — 적의 예고 배지를 몇 행동 먼저 띄울지. ★ 표시 전용(계산에 쓰지 말 것)."""
    return PROPHECY_TELEGRAPH_LEAD if RELIC_PROPHECY_BOOK in (relics or ()) else 0


def relic_shop_item_price(relics, price: int) -> int:
    """여행자의 지도 — 상점 "아이템" 가격 −20% (1G 미만으로는 안 내려간다).
    유물 가격에는 적용하지 않는다 — 유물까지 깎으면 풀 소진이 다시 빨라진다(7장)."""
    if RELIC_TRAVELERS_MAP not in (relics or ()):
        return int(price)
    return max(1, int(round(int(price) * (1.0 - TRAVELERS_MAP_DISCOUNT))))
