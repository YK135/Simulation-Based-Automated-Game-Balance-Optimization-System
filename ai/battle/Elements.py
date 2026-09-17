"""Battle/Elements.py — 원소 큐/반응/상태이상"""
from __future__ import annotations

from random import randint

from .Entity import Debuff, StatusEffect
from .Relics import frost_mark_mult, frost_mark_on_shatter
from .BossKit import finalboss_element_resist
from .EliteKit import (
    ICE_SLIME_ARMOR_REDUCTION, ICE_SLIME_BREAK_SPARM_AMOUNT, ICE_SLIME_BREAK_TURNS,
    LIGHTNING_SLIME_OVERLOAD_SPD_AMOUNT, LIGHTNING_SLIME_OVERLOAD_SPD_TURNS,
)

REACTIONS = {
    ("ice",       "fire"):      "melt",       # 단방향: ice→fire만 융해 발동 (fire→ice는 무반응)
    ("fire",      "lightning"): "overload",
    ("lightning", "fire"):      "overload",
}

# 원소 폭발(9·10장): 대상에 부착된 원소를 읽어 반응이 성립하는 상대 원소를 주입한다 — 전부 위 REACTIONS 조합
REACT_PARTNER = {"ice": "fire", "fire": "lightning", "lightning": "fire"}

REACTION_EFFECTS = {
    "melt":     {"bonus_mult": 1.5, "label": "💧 융해"},
    "shatter":  {"bonus_mult": 1.2, "label": "💎 파쇄"},
    "overload": {"bonus_mult": 1.3, "label": "⚡ 과부하"},
}

# ── 마법사 원소 공명 (Combat Content Brief 6-2 · 11-1 2차 4번) — 기존 패시브의 사전 축적 확장 ──
#   같은 원소를 연속 시전하면 2회차 +10% / 3회차 +20%(최대). 다른 원소로 전환하면 공명은 1단계로
#   초기화되는 대신 그 시전의 반응 보너스가 +5%p → +20%p. 상태는 EntitySnapshot.resonance_*,
#   갱신은 Skills.execute_skill의 훅(mage_resonance_on_cast) 한 곳 — 원소 마법 스킬 시전에만 반응한다.
#   힐·버프 같은 무원소 스킬과 아이템은 단계를 바꾸지 않는다.
RESONANCE_STEP = 0.10
RESONANCE_MAX_STACK = 3
RESONANCE_ELEMENTS = ("fire", "ice", "lightning")
MAGE_REACTION_BONUS = 0.05          # 기존 패시브: 융해·과부하 +5%p
MAGE_SWITCH_REACTION_BONUS = 0.20   # 전환 공명: 그 시전의 반응 보너스 +20%p


def mage_resonance_on_cast(attacker, element: str, stype: str) -> str:
    """마법사의 원소 마법 시전 1회를 공명에 반영. 반환 "stack"(같은 원소) / "switch"(전환) / ""(해당 없음)."""
    if getattr(attacker, "job", "") != "마법사" or stype != "magical" or element not in RESONANCE_ELEMENTS:
        return ""
    if attacker.resonance_element == element:
        attacker.resonance_stack = min(RESONANCE_MAX_STACK, attacker.resonance_stack + 1)
        attacker.resonance_switched = False
        return "stack"
    switched = bool(attacker.resonance_element)
    attacker.resonance_element = element
    attacker.resonance_stack = 1
    attacker.resonance_switched = switched
    return "switch" if switched else "stack"


def mage_resonance_mult(attacker, element: str) -> float:
    """현재 공명 단계의 피해 배율 — 같은 원소 2단계 1.10 / 3단계 1.20, 그 외 1.0."""
    if getattr(attacker, "job", "") != "마법사" or not element:
        return 1.0
    if getattr(attacker, "resonance_element", "") != element:
        return 1.0
    stack = getattr(attacker, "resonance_stack", 0)
    return 1.0 + RESONANCE_STEP * max(0, min(RESONANCE_MAX_STACK, stack) - 1)


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


def _elite_charge_slime_overload(defender, messages: list) -> None:
    """엘리트 화염/번개 슬라임이 상극 원소(과부하 반응)를 맞으면 열기/전하 스택 초기화.
    번개 슬라임은 추가로 1턴 SPD -20%."""
    if not getattr(defender, "elite_leader", False):
        return
    et = getattr(defender, "enemy_type", "")
    if et not in ("화염 슬라임", "번개 슬라임"):
        return
    defender.elite_pattern_turn = 0
    messages.append(f"{defender.name}의 스택이 초기화되었다!")
    if et == "번개 슬라임":
        defender.apply_debuff(Debuff(
            stat="spd", amount=LIGHTNING_SLIME_OVERLOAD_SPD_AMOUNT,
            turns=LIGHTNING_SLIME_OVERLOAD_SPD_TURNS, name="과부하"))


def _elite_ice_slime_break(defender, messages: list) -> None:
    """엘리트 빙결 슬라임의 파쇄 — 갑옷을 2턴간 해제하고 SPARM -20%.
    이미 해제 상태면(elite_phase==1) 같은 턴 중복 파쇄를 무시한다."""
    if not getattr(defender, "elite_leader", False):
        return
    if getattr(defender, "enemy_type", "") != "빙결 슬라임":
        return
    if getattr(defender, "elite_phase", 0) != 0:
        return
    defender.elite_phase = 1
    defender.elite_pattern_turn = ICE_SLIME_BREAK_TURNS
    # 갑옷 활성 상태(스폰 시 physical_resist *= 0.85)에서 그 배율을 되돌려
    # 원래 저항으로 복귀 — 1.0으로 고정하면 이 슬라임의 원래 저항이
    # 1.0이 아닐 때(예: 빙결 슬라임 기본 0.80) 틀린 값이 된다.
    defender.physical_resist = defender.physical_resist / (1 - ICE_SLIME_ARMOR_REDUCTION)
    defender.apply_debuff(Debuff(
        stat="sparm", amount=ICE_SLIME_BREAK_SPARM_AMOUNT,
        turns=ICE_SLIME_BREAK_TURNS, name="파쇄"))
    messages.append(f"{defender.name}의 빙결 갑옷이 깨졌다! 방어력이 약해졌다!")


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


def _stamp(defender, element: str, reaction: str, damage: int) -> None:
    """UI 데미지 숫자 색 구분용 태그를 defender에 남긴다 (표시 전용, 쓰기만).
    피해가 0이면 남기지 않는다 — 원소 부착만 하는 호출
    (try_apply_element_aura_and_status, 면역 무효화)까지 태그를 덮어써 버리면
    같은 step에 뒤따르는 DoT 피해가 엉뚱한 색으로 표시된다."""
    if damage > 0 and hasattr(defender, "_stamp_last_hit"):
        defender._stamp_last_hit(element, reaction)


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
        # 서리 사냥꾼의 각인(유물): ice가 붙은 대상에게 주는 물리 피해 +15% — 파쇄 배율 앞에 곱한다
        fm = frost_mark_mult(attacker, defender)
        if fm > 1.0 and base_damage > 0:
            base_damage = int(base_damage * fm)
            messages.append(f"❄ 서리 사냥꾼의 각인 — 물리 피해 +{int(round((fm - 1) * 100))}%")
        if q and q[-1] == "ice":
            eff = REACTION_EFFECTS["shatter"]
            bonus = int(base_damage * (eff["bonus_mult"] - 1.0))
            defender.element_queue.clear()
            messages.append(f"{eff['label']} 발동! +{bonus} 추가 데미지")
            if frost_mark_on_shatter(attacker) > 0:
                messages.append("❄ 서리 사냥꾼의 각인 — 파쇄! ATB +5")
            messages.append(f"{defender.name}의 원소 큐가 초기화되었다.")
            _restore_innate_element(defender, messages)   # 원소 슬라임 고유 원소 복구
            _elite_ice_slime_break(defender, messages)     # 엘리트 빙결 슬라임: 갑옷 파쇄
            _stamp(defender, "physical", "shatter", base_damage + bonus)
            return base_damage + bonus
        _stamp(defender, "physical", "", base_damage)
        return base_damage

    status_bonus = 0
    reacted = ""          # UI 색 구분용 — 이번 타격에서 실제로 터진 반응명

    # 최종 보스 페이즈 1: 붙어 있는 원소와 같은 원소 공격은 −40% (원소 슬라임 면역의 약화판)
    er = finalboss_element_resist(defender, attack_element)
    if er < 1.0 and base_damage > 0:
        base_damage = int(base_damage * er)
        messages.append(f"{defender.name}의 {attack_element} 갑주가 같은 원소를 흘려낸다! (피해 −{int(round((1 - er) * 100))}%)")

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
                reacted = reaction_name
                eff = REACTION_EFFECTS[reaction_name]
                bonus_mult = eff["bonus_mult"]
                # ── 마법사 패시브: 원소 반응 피해 +5%p — 융해/과부하만 ──
                #    파쇄(shatter)는 physical 분기에서 처리되므로 구조적으로도 제외되지만,
                #    명세(파쇄 제외)를 명시적으로 보장하기 위해 reaction_name 체크.
                is_mage = attacker is not None and getattr(attacker, "job", "") == "마법사"
                if is_mage and reaction_name in ("melt", "overload"):
                    if getattr(attacker, "resonance_switched", False):
                        # 전환 공명(6-2): 원소를 바꾼 그 시전은 +5%p 대신 +20%p
                        bonus_mult += MAGE_SWITCH_REACTION_BONUS
                        messages.append(f"[마법사 패시브] 원소 전환 공명 — 반응 보너스 +{int(MAGE_SWITCH_REACTION_BONUS * 100)}%p")
                    else:
                        bonus_mult += MAGE_REACTION_BONUS
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
                _elite_charge_slime_overload(defender, messages)  # 엘리트 화염/번개 슬라임: 스택 초기화
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

    _stamp(defender, attack_element, reacted, base_damage)
    return base_damage


# 하위 호환 래퍼
def check_element_reaction(defender, attack_element: str, base_damage: int, messages: list) -> int:
    return apply_element_and_react(None, defender, attack_element, base_damage, messages)


def try_apply_element_aura_and_status(attacker, defender, element: str, messages: list) -> None:
    if element:
        apply_element_and_react(attacker, defender, element, 0, messages)


# 구버전 호환
REACTION_TABLE = {}