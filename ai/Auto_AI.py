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


# ── 특수 아이템 판단 헬퍼 ──

def _has_item(entity: EntitySnapshot, name: str) -> bool:
    return name in entity.items


def _pick_special_item(attacker: EntitySnapshot, defender: EntitySnapshot,
                       enemy_count: int = 1) -> str | None:
    """
    특수 아이템 사용 판단.
    우선순위:
      1. 적이 ice 큐 보유 + 화염병 → 즉시 융해
      2. 적이 fire/lightning 큐 + 반응 가능한 원소병
      3. 적 2마리+ + 폭탄/거미줄폭탄 → AoE
      4. 강한 적(HP 비율 높음) + 집중물약 → 다음 스킬 강화
      5. 원소병 일반 사용 (큐 비어있을 때 상태이상 노림)
    """
    def_queue = getattr(defender, "element_queue", [])
    cur_elem = def_queue[-1] if def_queue else ""

    # 1. ice 적 → 화염병 (융해)
    if cur_elem == "ice" and _has_item(attacker, "fire_vial"):
        return "fire_vial"
    # 2. fire/lightning 적 → 반대 원소병 (과부하)
    if cur_elem == "fire" and _has_item(attacker, "lightning_crystal"):
        return "lightning_crystal"
    if cur_elem == "lightning" and _has_item(attacker, "fire_vial"):
        return "fire_vial"

    # 3. 다수 적 → AoE 폭탄
    if enemy_count >= 2:
        for bomb in ["web_bomb", "bomb"]:
            if _has_item(attacker, bomb):
                return bomb

    # 4. 적 HP 높음 + 집중물약 → 다음 스킬 강화
    def_hp_ratio = defender.hp / defender.maxhp if defender.maxhp > 0 else 0
    if def_hp_ratio >= 0.6 and _has_item(attacker, "focus_drug"):
        # 강한 공격 스킬이 있을 때만 의미 있음
        if any(SKILL_META.get(s, {}).get("type") in ATTACK_TYPES
               for s in attacker.learned_skills):
            return "focus_drug"

    # 5. 큐 비어있는 적 → 원소병으로 상태이상 노림
    if not cur_elem:
        for vial in ["fire_vial", "ice_vial", "lightning_crystal"]:
            if _has_item(attacker, vial):
                return vial

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

        # ── 특수 아이템 판단 (원소 반응/AoE/버프) ──
        # 위급 상황(회복/실드)이 아닐 때만 — 위는 이미 위에서 처리됨
        special = _pick_special_item(attacker, defender, enemy_count=1)
        if special:
            return Action("item", special)

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

    # unit이 None일 때 사용할 기본 행동 확률.
    # watch는 게임 진행을 늦추므로 제거, SP가 있는 몬스터는 magic 확률 증가.
    DEFAULT_ATTACK_PROB_NO_SP = 1.00  # SP=0 몬스터: 100% 공격
    DEFAULT_ATTACK_PROB_SP    = 0.55  # SP>0 몬스터: 55% 공격, 45% 마법

    def __init__(self, unit=None):
        self.unit = unit

    def _decide_action_type(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> str:
        """
        unit이 있으면 unit.decide_action 사용 (게임 경로).
        없으면 attacker의 SP/MP 상황 기반 기본 확률 (시뮬 경로).
        Digital Twin 원칙을 완벽히 지키진 못하지만, 시뮬 전투가
        기본 공격만 하는 상태보다는 실제 게임에 가깝게 동작.
        """
        if self.unit:
            return self.unit.decide_action(defender)

        # unit 없는 경우: attacker 스펙으로 판단
        from random import random as rr
        has_sp_kit = attacker.sp > 0 and attacker.maxmp > 0
        threshold = self.DEFAULT_ATTACK_PROB_SP if has_sp_kit else self.DEFAULT_ATTACK_PROB_NO_SP
        return "attack" if rr() < threshold else "magic"

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        action_type = self._decide_action_type(attacker, defender)

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