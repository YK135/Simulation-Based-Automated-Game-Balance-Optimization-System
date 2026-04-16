"""
Auto_AI.py
─────────────────────────────────────────────
규칙 기반 자동 전투 AI.
"""
from __future__ import annotations

try:
    from ai.Battle_Engine import Action, EntitySnapshot, SKILL_META, ITEM_META
except ModuleNotFoundError:
    from Battle_Engine import Action, EntitySnapshot, SKILL_META, ITEM_META


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


def _skill_efficiency(skill_name: str, attacker: EntitySnapshot, defender: EntitySnapshot | None = None) -> float:
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

    if stype == "physical":
        return (attacker.effective_stg() * meta.get("mult", 1.0) * meta.get("hits", 1)) / real_mp_cost

    if stype == "magical":
        return (attacker.sp * meta.get("mult", 1.0) * meta.get("hits", 1)) / real_mp_cost

    return -1.0


def _best_attack_skill(attacker: EntitySnapshot, defender: EntitySnapshot) -> str | None:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta.get("type") not in ATTACK_TYPES:
            continue
        score = _skill_efficiency(skill, attacker, defender)
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


class PlayerAI:
    HP_DANGER_RATIO = 0.30
    HP_CAUTION_RATIO = 0.50
    MP_LOW_RATIO = 0.20
    SKILL_MP_RESERVE = 0.30
    DEBUFF_MP_RESERVE = 0.40

    def __init__(self, aggression: str = "balanced"):
        self.aggression = aggression

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
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

        mp_threshold = {
            "aggressive": 0.0,
            "balanced": self.SKILL_MP_RESERVE,
            "defensive": 0.5,
        }.get(self.aggression, self.SKILL_MP_RESERVE)

        if mp_ratio >= mp_threshold or self.aggression == "aggressive":
            skill = _best_attack_skill(attacker, defender)
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
    ENEMY_DEBUFF_SKILLS = ["약화1", "마약화1", "저주1", "둔화1"]
    ENEMY_MAGIC_SKILLS = ["파이어볼1", "아이스볼릿1"]

    def __init__(self, unit=None):
        self.unit = unit

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        action_type = "attack"
        if self.unit:
            action_type = self.unit.decide_action(defender)

        if action_type == "watch":
            return Action("watch", "watching")

        if action_type == "magic" and attacker.mp > 0:
            from random import random as rr
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

    def __call__(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        return self.decide(attacker, defender)