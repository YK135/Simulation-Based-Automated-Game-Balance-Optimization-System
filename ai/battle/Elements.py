"""Battle/Elements.py — 원소 큐/반응/상태이상"""
from __future__ import annotations

from random import randint

from .Entity import StatusEffect

REACTIONS = {
    ("ice",       "fire"):      "melt",       # 단방향: ice→fire만 융해 발동 (fire→ice는 무반응)
    ("fire",      "lightning"): "overload",
    ("lightning", "fire"):      "overload",
}

REACTION_EFFECTS = {
    "melt":     {"bonus_mult": 1.5, "label": "💧 융해"},
    "shatter":  {"bonus_mult": 1.2, "label": "💎 파쇄"},
    "overload": {"bonus_mult": 1.3, "label": "⚡ 과부하"},
}

# 원소 → 상태이상
ELEMENT_STATUS = {
    "fire":      ("ignite",    30),
    "ice":       ("frostbite", 35),
    "lightning": ("paralyze",  25),
}
ELEMENT_STATUS_TURNS = {"ignite": 3, "frostbite": 2, "paralyze": 3}
ELEMENT_STATUS_LABEL = {"ignite": "🔥 화상", "frostbite": "❄ 동상", "paralyze": "⚡ 마비"}
SAME_ELEMENT_STATUS_BONUS = {"fire": 15, "ice": 15, "lightning": 15}


def _current_element(entity) -> str:
    """큐의 최신 원소 반환."""
    q = getattr(entity, "element_queue", [])
    return q[-1] if q else ""


# ── 원소 면역 (원소 슬라임은 자기 원소에 완전 면역) ──
ELEMENT_IMMUNITY_BY_ENEMY_TYPE = {
    "화염 슬라임": "fire",
    "빙결 슬라임": "ice",
    "번개 슬라임": "lightning",
}


# 원소 슬라임 고유(innate) 원소 — 면역 매핑과 동일 (화염=fire / 빙결=ice / 번개=lightning)
INNATE_ELEMENT_BY_ENEMY_TYPE = ELEMENT_IMMUNITY_BY_ENEMY_TYPE


def _innate_element(defender) -> str:
    """원소 슬라임의 고유 원소. 일반 몬스터는 ''."""
    et = getattr(defender, "enemy_type", "") or getattr(defender, "name", "")
    innate = INNATE_ELEMENT_BY_ENEMY_TYPE.get(et)
    if innate is None:
        innate = INNATE_ELEMENT_BY_ENEMY_TYPE.get(getattr(defender, "name", ""), "")
    return innate or ""


def _restore_innate_element(defender, messages: list) -> None:
    """원소 반응/파쇄로 큐가 초기화된 뒤, 원소 슬라임은 고유 원소를 다시 부착.
    (일반 몬스터는 빈 큐 유지 — 기존 동작)"""
    innate = _innate_element(defender)
    if innate and innate not in getattr(defender, "element_queue", []):
        defender.element_queue.append(innate)
        messages.append(f"{defender.name}의 고유 원소가 다시 타오른다! ({innate})")


def is_element_immune(defender, attack_element: str) -> bool:
    """defender가 attack_element에 면역인지. physical/무원소는 면역 없음."""
    if not attack_element or attack_element == "physical":
        return False
    enemy_type = getattr(defender, "enemy_type", "") or getattr(defender, "name", "")
    immune = ELEMENT_IMMUNITY_BY_ENEMY_TYPE.get(enemy_type)
    if immune is None:
        # enemy_type이 비어있는 경우 name으로 재시도
        immune = ELEMENT_IMMUNITY_BY_ENEMY_TYPE.get(getattr(defender, "name", ""))
    return immune == attack_element


def apply_element_and_react(
    attacker,
    defender,
    attack_element: str,
    base_damage: int,
    messages: list,
) -> int:
    """
    원소 큐 업데이트 + 반응 판정 + 상태이상 처리.
    반환: 최종 데미지
    """
    q = getattr(defender, "element_queue", [])

    # ── 원소 면역: 같은 원소 슬라임에게는 완전 무효 ──
    #    데미지 0 + 큐 중첩 X + 상태이상 X + 반응 X
    if is_element_immune(defender, attack_element):
        messages.append(f"{defender.name}에게 {attack_element} 공격은 효과가 없다!")
        return 0

    # physical: 파쇄 체크만 (큐에 추가 안 함)
    if attack_element == "physical" or not attack_element:
        if q and q[-1] == "ice":
            eff = REACTION_EFFECTS["shatter"]
            bonus = int(base_damage * (eff["bonus_mult"] - 1.0))
            defender.element_queue.clear()
            messages.append(f"{eff['label']} 발동! +{bonus} 추가 데미지")
            messages.append(f"{defender.name}의 원소 큐가 초기화되었다.")
            _restore_innate_element(defender, messages)   # 원소 슬라임 고유 원소 복구
            return base_damage + bonus
        return base_damage

    status_bonus = 0

    if len(q) == 0:
        defender.element_queue.append(attack_element)
        messages.append(f"{defender.name}에게 {attack_element} 원소가 부착되었다.")

    elif len(q) == 1:
        existing = q[0]
        if existing == attack_element:
            status_bonus = SAME_ELEMENT_STATUS_BONUS.get(attack_element, 0)
            messages.append(f"{defender.name}에게 {attack_element} 원소 중첩! 상태이상 확률 ↑")
            defender.element_queue = [attack_element]
        else:
            defender.element_queue.append(attack_element)
            key = (existing, attack_element)
            reaction_name = REACTIONS.get(key)
            if reaction_name:
                eff = REACTION_EFFECTS[reaction_name]
                bonus_mult = eff["bonus_mult"]
                # ── 마법사 패시브: 원소 반응 피해 +5%p — 융해/과부하만 ──
                #    파쇄(shatter)는 physical 분기에서 처리되므로 구조적으로도 제외되지만,
                #    명세(파쇄 제외)를 명시적으로 보장하기 위해 reaction_name 체크.
                is_mage = attacker is not None and getattr(attacker, "job", "") == "마법사"
                if is_mage and reaction_name in ("melt", "overload"):
                    bonus_mult += 0.05
                bonus = int(base_damage * (bonus_mult - 1.0))
                defender.element_queue.clear()
                messages.append(f"{eff['label']} 반응 발동!")
                messages.append(f"{defender.name}에게 추가 {bonus} 피해!")
                messages.append(f"{defender.name}의 원소 큐가 초기화되었다.")
                base_damage += bonus
                # ── 마법사 패시브: 원소 반응 발생 시 MP 8% 회복 ──
                if is_mage:
                    mp_gain = int(attacker.maxmp * 0.08)
                    before = attacker.mp
                    attacker.mp = min(attacker.maxmp, attacker.mp + mp_gain)
                    gained = int(attacker.mp - before)
                    if gained > 0:
                        messages.append(f"[마법사 패시브] 원소 반응 → MP +{gained}")
                _restore_innate_element(defender, messages)   # 원소 슬라임 고유 원소 복구
            else:
                defender.element_queue = [attack_element]
                messages.append(f"{defender.name}에게 {attack_element} 원소가 부착되었다.")

    # 상태이상 부여
    entry = ELEMENT_STATUS.get(attack_element)
    if entry:
        effect_type, base_prob = entry
        prob = min(95, base_prob + status_bonus)
        if randint(1, 100) <= prob:
            turns = ELEMENT_STATUS_TURNS[effect_type]
            eff_obj = StatusEffect(effect_type=effect_type, turns=turns, name=attack_element)
            if hasattr(defender, "apply_status_effect"):
                defender.apply_status_effect(eff_obj)
            label = ELEMENT_STATUS_LABEL[effect_type]
            messages.append(f"{defender.name}에게 {label} 상태가 부여되었다. ({turns}T)")

    return base_damage


# 하위 호환 래퍼
def check_element_reaction(defender, attack_element: str, base_damage: int, messages: list) -> int:
    return apply_element_and_react(None, defender, attack_element, base_damage, messages)


def try_apply_element_aura_and_status(attacker, defender, element: str, messages: list) -> None:
    if element:
        apply_element_and_react(attacker, defender, element, 0, messages)


# 구버전 호환
REACTION_TABLE = {}