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
RELIC_IDS = COMMON_RELIC_IDS

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


def relic_debuff_turns(caster, target, turns: int) -> int:
    """거울 파편 — 디버프·상태이상의 지속 턴 보정. 최소 1턴은 남긴다.

    거는 쪽이 가졌으면 1턴 짧아지고(대가), 받는 쪽이 가졌으면 1턴 짧아진다(이득).
    caster를 모르는 호출부는 None을 넘기면 되고, 그때는 받는 쪽만 본다 —
    유물을 아무도 안 가졌으면 turns가 그대로 돌아오므로 기존 전투 계산은 불변이다."""
    turns = int(turns)
    if turns <= 1:
        return turns
    cut = 0
    if has_relic(caster, RELIC_MIRROR_SHARD):
        cut += MIRROR_SHARD_TURN_CUT
    if has_relic(target, RELIC_MIRROR_SHARD):
        cut += MIRROR_SHARD_TURN_CUT
    return max(1, turns - cut)


def relic_telegraph_lead(relics) -> int:
    """예언서 — 적의 예고 배지를 몇 행동 먼저 띄울지. ★ 표시 전용(계산에 쓰지 말 것)."""
    return PROPHECY_TELEGRAPH_LEAD if RELIC_PROPHECY_BOOK in (relics or ()) else 0


def relic_shop_item_price(relics, price: int) -> int:
    """여행자의 지도 — 상점 "아이템" 가격 −20% (1G 미만으로는 안 내려간다).
    유물 가격에는 적용하지 않는다 — 유물까지 깎으면 풀 소진이 다시 빨라진다(7장)."""
    if RELIC_TRAVELERS_MAP not in (relics or ()):
        return int(price)
    return max(1, int(round(int(price) * (1.0 - TRAVELERS_MAP_DISCOUNT))))
