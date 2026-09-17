"""
Battle/Relics.py — 유물의 전투 효과 (Combat Content Brief 7장 · 11-1 2차 7번)
─────────────────────────────────────────────
수치 상수와 전투 안에서 쓰는 순수 함수만 둔다 — 실전(ai/Battlesession.py)과
튜너 엔진(ai/battle/Engine.py)이 같은 함수를 부른다. 이름·설명·가격·선택 규칙처럼
전투 밖의 것은 game/Relics.py(이 모듈의 상수를 읽는다).

유물 id (4종, 전 직업 공용 — 사용자 결정 2026-09-17):
  hourglass       깨진 모래시계    — 전투 종료 시 잔여 ATB가 2배로 이월
  greed_seal      탐욕의 인장      — 골드 획득 +40%, 포션 슬롯 −1 (game/Inventory.py · app/Battle.py)
  frost_mark      서리 사냥꾼의 각인 — ice가 부착된 적에게 주는 물리 피해 +15%, 파쇄 시 ATB +5
  priest_remains  사제의 유해      — 전투당 1회, HP가 0이 될 때 최대 HP 20%로 부활
"""
from __future__ import annotations

RELIC_HOURGLASS = "hourglass"
RELIC_GREED_SEAL = "greed_seal"
RELIC_FROST_MARK = "frost_mark"
RELIC_PRIEST_REMAINS = "priest_remains"
RELIC_IDS = (RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS)

HOURGLASS_ATB_MULT = 2.0
GREED_GOLD_BONUS = 0.40
GREED_POTION_SLOT_PENALTY = 1
FROST_MARK_PHYS_BONUS = 0.15
FROST_MARK_SHATTER_ATB = 5.0
REMAINS_REVIVE_HP_RATIO = 0.20


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
    """탐욕의 인장 — 포션 슬롯 감소 수 (game/Inventory.py가 용량에서 뺀다)."""
    return GREED_POTION_SLOT_PENALTY if RELIC_GREED_SEAL in (relics or ()) else 0
