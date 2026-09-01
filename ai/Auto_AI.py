"""
Auto_AI.py
─────────────────────────────────────────────
규칙 기반 자동 전투 AI.
"""
from __future__ import annotations
from ai.battle import Action, EntitySnapshot, SKILL_META, ITEM_META, MONSTER_SKILL_META, get_monster_kit
from ai.battle.Elements import is_element_immune

ATTACK_TYPES = {"physical", "magical", "multi_hit", "tank_attack", "counter"}
SUPPORT_TYPES = {"buff", "heal", "shield", "debuff"}


def _enemy_has_debuff(defender: EntitySnapshot, stat: str) -> bool:
    return any(d.stat == stat for d in defender.debuffs)


def _self_has_buff(attacker: EntitySnapshot, stat: str) -> bool:
    return any(b.stat == stat for b in attacker.buffs)


def _best_hp_potion(entity: EntitySnapshot) -> str | None:
    for p in ["HP_L_potion", "HP_M_potion", "HP_S_potion"]:
        if p in entity.items:
            return p
    return None


def _best_mp_potion(entity: EntitySnapshot) -> str | None:
    for p in ["MP_L_potion", "MP_M_potion", "MP_S_potion"]:
        if p in entity.items:
            return p
    return None


def _skill_efficiency(skill_name: str, attacker: EntitySnapshot, defender: EntitySnapshot | None = None,
                      enemy_count: int = 1) -> float:
    meta = SKILL_META.get(skill_name)
    if not meta:
        return -1.0

    real_mp_cost = max(1, int(round(meta.get("mp", 0) * attacker.mp_cost_multiplier())))
    if attacker.mp < real_mp_cost:
        return -1.0

    stype = meta.get("type")

    if stype == "debuff":
        avg_amount = sum(meta["debuff_amount"]) / 2
        avg_turns = sum(meta["debuff_turns"]) / 2
        bonus = 1.5 if meta["debuff_stat"] == "spd" else 1.0
        return (avg_amount * avg_turns * 10 * bonus) / real_mp_cost

    if stype == "buff":
        return (meta.get("buff_amount", 0.0) * 100) / real_mp_cost

    if stype == "heal":
        heal = meta.get("base_heal", 0) + attacker.sp * meta.get("sp_mult", 0.0)
        return heal / real_mp_cost

    if stype == "shield":
        shield_val = attacker.maxhp * meta.get("shield_mult", 0.0)
        return shield_val / real_mp_cost

    if stype == "tank_attack":
        dmg = attacker.effective_arm() * meta.get("arm_mult", 0.0) + attacker.maxhp * meta.get("hp_mult", 0.0)
        return dmg / real_mp_cost

    if stype == "counter":
        dmg = attacker.last_damage_taken * meta.get("counter_mult", 0.0) + attacker.effective_arm() * meta.get("arm_mult", 0.0)
        dmg = min(dmg, attacker.maxhp * meta.get("cap", 1.0))
        return dmg / real_mp_cost

    if stype == "multi_hit":
        expected_hits = 2.2
        base = attacker.effective_stg()
        return (base * expected_hits) / real_mp_cost

    # 속성 스킬인데 상대가 그 속성에 완전 면역이면(예: 화염 슬라임에게 화염 스킬)
    # 실제 데미지가 0이 되므로 효율 계산에서 아예 배제 — AI가 계속 헛스킬을 반복해
    # 이기지 못하는 상황(예: 마법사 vs 화염 슬라임 승률 0%)을 막는다.
    element = meta.get("element")
    if element and defender is not None and is_element_immune(defender, element):
        return -1.0

    if stype == "physical":
        dmg = attacker.effective_stg() * meta.get("mult", 1.0) * meta.get("hits", 1)
        # AoE(슬래시 등)는 살아있는 적 수만큼 총피해 — 다대일에서 정당하게 평가
        if meta.get("aoe"):
            dmg *= max(1, enemy_count)
        return dmg / real_mp_cost

    if stype == "magical":
        dmg = attacker.sp * meta.get("mult", 1.0) * meta.get("hits", 1)
        if meta.get("aoe"):
            dmg *= max(1, enemy_count)
        return dmg / real_mp_cost

    return -1.0


def _best_attack_skill(attacker: EntitySnapshot, defender: EntitySnapshot,
                       enemy_count: int = 1) -> str | None:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta.get("type") not in ATTACK_TYPES:
            continue
        score = _skill_efficiency(skill, attacker, defender, enemy_count=enemy_count)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_debuff_skill(attacker: EntitySnapshot, stat: str | None = None) -> str | None:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta.get("type") != "debuff":
            continue
        if stat and meta.get("debuff_stat") != stat:
            continue
        score = _skill_efficiency(skill, attacker)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_heal_skill(attacker: EntitySnapshot) -> str | None:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta.get("type") != "heal":
            continue
        score = _skill_efficiency(skill, attacker)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_buff_skill(attacker: EntitySnapshot, stat: str | None = None) -> str | None:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta.get("type") != "buff":
            continue
        if stat and meta.get("buff_stat") != stat:
            continue
        score = _skill_efficiency(skill, attacker)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_shield_skill(attacker: EntitySnapshot) -> str | None:
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if meta and meta.get("type") == "shield" and attacker.mp >= meta.get("mp", 0):
            return skill
    return None

def _has_item(entity: EntitySnapshot, name: str) -> bool:
    return name in entity.items


def _pick_special_item(attacker: EntitySnapshot, defender: EntitySnapshot,
                       enemy_count: int = 1) -> str | None:
    def_queue = getattr(defender, "element_queue", [])
    cur_elem = def_queue[-1] if def_queue else ""

    # ice 적이면 화염병으로 융해 노림
    if cur_elem == "ice" and _has_item(attacker, "fire_vial"):
        return "fire_vial"

    # fire/lightning 적이면 과부하 노림
    if cur_elem == "fire" and _has_item(attacker, "lightning_crystal"):
        return "lightning_crystal"

    if cur_elem == "lightning" and _has_item(attacker, "fire_vial"):
        return "fire_vial"

    # 다수 적이면 폭탄 우선
    if enemy_count >= 2:
        for bomb in ["web_bomb", "bomb"]:
            if _has_item(attacker, bomb):
                return bomb

    # 적 HP가 높고 공격 스킬이 있으면 집중 물약
    def_hp_ratio = defender.hp / defender.maxhp if defender.maxhp > 0 else 0
    if def_hp_ratio >= 0.6 and _has_item(attacker, "focus_drug"):
        if any(SKILL_META.get(s, {}).get("type") in ATTACK_TYPES for s in attacker.learned_skills):
            return "focus_drug"

    # 원소 큐가 비어 있으면 원소병으로 상태이상/반응 준비
    if not cur_elem:
        for vial in ["fire_vial", "ice_vial", "lightning_crystal"]:
            if _has_item(attacker, vial):
                return vial

    return None

class PlayerAI:
    HP_DANGER_RATIO = 0.30
    HP_CAUTION_RATIO = 0.50
    MP_LOW_RATIO = 0.20
    SKILL_MP_RESERVE = 0.30
    DEBUFF_MP_RESERVE = 0.40

    def __init__(self, aggression: str = "balanced"):
        self.aggression = aggression

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot,
               enemy_count: int = 1) -> Action:
        hp_ratio = attacker.hp / attacker.maxhp if attacker.maxhp > 0 else 1.0
        mp_ratio = attacker.mp / attacker.maxmp if attacker.maxmp > 0 else 0.0

        # Lv5 이하: 공격 스킬 우선, 버프/운영 최소화
        early_game = attacker.lv <= 5

        if hp_ratio <= 0.35:
            heal_skill = _best_heal_skill(attacker)
            if heal_skill:
                return Action("skill", heal_skill)

        danger = self.HP_CAUTION_RATIO if self.aggression == "defensive" else self.HP_DANGER_RATIO
        if hp_ratio <= danger:
            potion = _best_hp_potion(attacker)
            if potion:
                return Action("item", potion)

        # 실드: 초반엔 HP 35% 이하 위기일 때만 (기존 50% → 35%)
        shield_threshold = 0.35 if early_game else 0.50
        if hp_ratio <= shield_threshold and attacker.shield <= 0:
            shield_skill = _best_shield_skill(attacker)
            if shield_skill:
                return Action("skill", shield_skill)

        spd_ratio = defender.effective_spd() / max(attacker.effective_spd(), 1.0)
        if spd_ratio >= 1.5 and not _enemy_has_debuff(defender, "spd") and mp_ratio >= self.DEBUFF_MP_RESERVE:
            slow_skill = _best_debuff_skill(attacker, stat="spd")
            if slow_skill:
                return Action("skill", slow_skill)

        # 버프: 초반엔 mp_ratio >= 0.65 이상일 때만 (기존 0.4/0.35 → 0.65)
        buff_threshold = 0.65 if early_game else 0.40
        buff_arm_threshold = 0.65 if early_game else 0.35

        if attacker.effective_stg() > attacker.sp and not _self_has_buff(attacker, "stg"):
            stg_buff = _best_buff_skill(attacker, stat="stg")
            if stg_buff and mp_ratio >= buff_threshold:
                return Action("skill", stg_buff)

        if attacker.effective_arm() >= attacker.stg and not _self_has_buff(attacker, "arm"):
            arm_buff = _best_buff_skill(attacker, stat="arm")
            if arm_buff and mp_ratio >= buff_arm_threshold:
                return Action("skill", arm_buff)

        if attacker.effective_spd() >= max(defender.effective_spd(), 1.0) and not _self_has_buff(attacker, "spd"):
            spd_buff = _best_buff_skill(attacker, stat="spd")
            if spd_buff and mp_ratio >= buff_arm_threshold:
                return Action("skill", spd_buff)

        # 저주(디버프): 초반엔 생략
        if not early_game and not _enemy_has_debuff(defender, "stg") and mp_ratio >= self.DEBUFF_MP_RESERVE:
            curse = _best_debuff_skill(attacker, stat="stg")
            if curse:
                return Action("skill", curse)

        special = _pick_special_item(attacker, defender, enemy_count=1)
        if special:
            return Action("item", special)
        
        mp_threshold = {
            "aggressive": 0.0,
            "balanced": self.SKILL_MP_RESERVE,
            "defensive": 0.5,
        }.get(self.aggression, self.SKILL_MP_RESERVE)

        if mp_ratio >= mp_threshold or self.aggression == "aggressive":
            # ── 탱커: 피격 직후 되갚기 고려 (밸런스 패치) ──
            #    MP당 효율로는 몸통박치기에 항상 밀리므로(MC 실측: 되갚기 선택 0회),
            #    '절대 피해'가 몸통박치기의 90% 이상이면 되갚기를 우선 선택한다.
            #    되갚기 계수는 무변경 — AI 선택 로직만 개선.
            if attacker.job == "탱커" and getattr(attacker, "last_damage_taken", 0) > 0:
                best_counter, counter_dmg, tank_dmg = None, 0.0, 0.0
                for sk in attacker.learned_skills:
                    meta = SKILL_META.get(sk, {})
                    cost = meta.get("mp", 0) * attacker.mp_cost_multiplier()
                    if attacker.mp < cost:
                        continue
                    stype = meta.get("type", "")
                    if stype == "counter":
                        d = attacker.last_damage_taken * meta.get("counter_mult", 0.0) \
                            + attacker.effective_arm() * meta.get("arm_mult", 0.0)
                        d = min(d, attacker.maxhp * meta.get("cap", 1.0))
                        if d > counter_dmg:
                            counter_dmg, best_counter = d, sk
                    elif stype == "tank_attack":
                        d = attacker.effective_arm() * meta.get("arm_mult", 0.0) \
                            + attacker.maxhp * meta.get("hp_mult", 0.0)
                        tank_dmg = max(tank_dmg, d)
                if best_counter and counter_dmg >= tank_dmg * 0.9:
                    return Action("skill", best_counter)

            skill = _best_attack_skill(attacker, defender, enemy_count=enemy_count)
            if skill:
                return Action("skill", skill)

        if mp_ratio <= self.MP_LOW_RATIO and attacker.learned_skills:
            potion = _best_mp_potion(attacker)
            if potion:
                return Action("item", potion)

        return Action("attack", "attack")

    def __call__(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        return self.decide(attacker, defender)


class EnemyAI:
    """
    몬스터 행동 결정.
    attacker.enemy_type에 대응하는 몬스터 킷(MonsterKit.MONSTER_KITS)이 있으면
    그 확률/스킬 세트를 그대로 따른다(챕터별 명세 반영).
    킷이 없는 타입(보스 등)은 기존 SP/MP 기반 휴리스틱으로 폴백한다 —
    보스 패턴은 이번 작업 범위 밖이라 그대로 유지.
    """

    # 폴백 전용(MONSTER_KITS에 없는 타입 — 보스 등) — 기존 전역 스킬 목록.
    ENEMY_DEBUFF_SKILLS = ["약화1", "미약화1", "저주1", "둔화1"]
    ENEMY_MAGIC_SKILLS = ["파이어볼1", "아이스볼릿1"]

    # unit도 킷도 없을 때 사용할 기본 행동 확률.
    DEFAULT_ATTACK_PROB_NO_SP = 1.00  # SP=0 몬스터: 100% 공격
    DEFAULT_ATTACK_PROB_SP    = 0.55  # SP>0 몬스터: 55% 공격, 45% 마법

    def __init__(self, unit=None):
        self.unit = unit

    def _pick_kit_skill(self, attacker: EntitySnapshot, skills: list) -> str | None:
        """킷의 스킬 후보 중 MP가 감당되는 것만 걸러 균등 랜덤 선택."""
        from random import choice as rc
        affordable = []
        for name in skills:
            meta = MONSTER_SKILL_META.get(name) or SKILL_META.get(name)
            if not meta:
                continue
            cost = meta.get("mp", 0) * attacker.mp_cost_multiplier()
            if attacker.mp >= cost:
                affordable.append(name)
        return rc(affordable) if affordable else None

    def _decide_with_kit(self, attacker: EntitySnapshot, kit: dict) -> Action:
        from random import random as rr
        roll = rr()
        attack_p = kit.get("attack_prob", 1.0)
        skill_p  = kit.get("skill_prob", 0.0)

        if roll < attack_p:
            return Action("attack", "attack")

        if roll < attack_p + skill_p:
            skill = self._pick_kit_skill(attacker, kit.get("skills", []))
            if skill:
                return Action("skill", skill)
            return Action("attack", "attack")

        return Action("watch", "watching")

    def _decide_fallback(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        """
        킷이 정의되지 않은 타입(보스 등)의 기존 동작.
        unit이 있으면 unit.decide_action 사용 (게임 경로).
        없으면 attacker의 SP/MP 상황 기반 기본 확률 (시뮬 경로).
        """
        from random import random as rr

        if self.unit:
            action_type = self.unit.decide_action(defender)
        else:
            has_sp_kit = attacker.sp > 0 and attacker.maxmp > 0
            threshold = self.DEFAULT_ATTACK_PROB_SP if has_sp_kit else self.DEFAULT_ATTACK_PROB_NO_SP
            action_type = "attack" if rr() < threshold else "magic"

        if action_type == "watch":
            return Action("watch", "watching")

        if action_type == "magic" and attacker.mp > 0:
            if rr() < 0.3:
                for skill in self.ENEMY_DEBUFF_SKILLS:
                    meta = SKILL_META.get(skill)
                    if meta and attacker.mp >= meta.get("mp", 0):
                        return Action("skill", skill)
            for skill in self.ENEMY_MAGIC_SKILLS:
                meta = SKILL_META.get(skill)
                if meta and attacker.mp >= meta.get("mp", 0):
                    return Action("skill", skill)

        return Action("attack", "attack")

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot,
               enemy_count: int = 1, chapter: int = 1) -> Action:
        kit = get_monster_kit(getattr(attacker, "enemy_type", ""), chapter)
        if kit is not None:
            return self._decide_with_kit(attacker, kit)
        return self._decide_fallback(attacker, defender)

    def __call__(self, attacker: EntitySnapshot, defender: EntitySnapshot,
                 chapter: int = 1) -> Action:
        return self.decide(attacker, defender, chapter=chapter)