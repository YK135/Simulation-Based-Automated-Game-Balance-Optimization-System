"""
Auto_AI.py
─────────────────────────────────────────────
규칙 기반 자동 전투 AI.

ATB 시스템 반영 변경사항:
  - 적 스피드가 플레이어보다 1.5배 이상 빠르면 둔화 스킬 최우선 사용
    (ATB에서 스피드 차이가 클수록 연속 행동 빈도 차이 → 둔화가 핵심 전략)
  - 디버프 스킬 판단 시 적의 현재 ATB 포인트 차이 고려
"""

from typing import Optional
from Battle_Engine import Action, EntitySnapshot, SKILL_META, ITEM_META


# ────────────────────────────────────────────
# 유틸
# ────────────────────────────────────────────

def _skill_efficiency(skill_name: str, attacker: EntitySnapshot) -> float:
    meta = SKILL_META.get(skill_name)
    if not meta or attacker.mp < meta.get("mp", 0):
        return -1.0

    if meta["type"] == "debuff":
        avg_amount = sum(meta["debuff_amount"]) / 2
        avg_turns  = sum(meta["debuff_turns"])  / 2
        mp_cost    = meta["mp"] if meta["mp"] > 0 else 0.1
        # 스피드 디버프는 ATB 시스템에서 더 가치 있으므로 보너스
        bonus = 1.5 if meta["debuff_stat"] == "spd" else 1.0
        return (avg_amount * avg_turns * 10 * bonus) / mp_cost

    base_stat = attacker.stg if meta["type"] == "physical" else attacker.sp
    mp_cost   = meta["mp"] if meta["mp"] > 0 else 0.1
    return (base_stat * meta["mult"] * meta.get("hits", 1)) / mp_cost


def _best_attack_skill(attacker: EntitySnapshot) -> Optional[str]:
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta["type"] == "debuff":
            continue
        score = _skill_efficiency(skill, attacker)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_debuff_skill(attacker: EntitySnapshot, stat: str = None) -> Optional[str]:
    """stat 지정 시 해당 stat 디버프 스킬만 반환"""
    best, best_score = None, -1.0
    for skill in attacker.learned_skills:
        meta = SKILL_META.get(skill)
        if not meta or meta["type"] != "debuff":
            continue
        if stat and meta["debuff_stat"] != stat:
            continue
        score = _skill_efficiency(skill, attacker)
        if score > best_score:
            best_score, best = score, skill
    return best if best_score > 0 else None


def _best_hp_potion(entity: EntitySnapshot) -> Optional[str]:
    for p in ["HP_L_potion", "HP_M_potion", "HP_S_potion"]:
        if p in entity.items:
            return p
    return None


def _best_mp_potion(entity: EntitySnapshot) -> Optional[str]:
    for p in ["MP_L_potion", "MP_M_potion", "MP_S_potion"]:
        if p in entity.items:
            return p
    return None


def _enemy_has_debuff(defender: EntitySnapshot, stat: str) -> bool:
    return any(d.stat == stat for d in defender.debuffs)


# ────────────────────────────────────────────
# 플레이어 AI
# ────────────────────────────────────────────

class PlayerAI:
    """
    규칙 기반 플레이어 AI.

    ATB 전략 추가:
      - 적 스피드가 나보다 1.5배 이상 빠르면 둔화 최우선 (ATB 연속행동 차단)
      - 디버프 중 없을 때 → 둔화 → 저주(공격력 감소) → 공격 순
    """

    HP_DANGER_RATIO   = 0.30
    HP_CAUTION_RATIO  = 0.50
    MP_LOW_RATIO      = 0.20
    SKILL_MP_RESERVE  = 0.30
    DEBUFF_MP_RESERVE = 0.40

    def __init__(self, aggression: str = "balanced"):
        self.aggression = aggression

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        hp_ratio = attacker.hp / attacker.maxhp if attacker.maxhp > 0 else 1.0
        mp_ratio = attacker.mp / attacker.maxmp if attacker.maxmp > 0 else 0.0

        # ── 규칙 1: HP 위험 → 포션 ──
        danger = (self.HP_CAUTION_RATIO
                  if self.aggression == "defensive"
                  else self.HP_DANGER_RATIO)
        if hp_ratio <= danger:
            potion = _best_hp_potion(attacker)
            if potion:
                return Action("item", potion)

        # ── 규칙 2: ATB 핵심 — 적 스피드가 1.5배 이상 빠르면 둔화 최우선 ──
        spd_ratio = defender.effective_spd() / max(attacker.effective_spd(), 1.0)
        if (spd_ratio >= 1.5
                and not _enemy_has_debuff(defender, "spd")
                and mp_ratio >= self.DEBUFF_MP_RESERVE):
            slow_skill = _best_debuff_skill(attacker, stat="spd")
            if slow_skill:
                return Action("skill", slow_skill)

        # ── 규칙 3: 공격 스킬 ──
        mp_threshold = {
            "aggressive": 0.0,
            "balanced":   self.SKILL_MP_RESERVE,
            "defensive":  0.5,
        }.get(self.aggression, self.SKILL_MP_RESERVE)

        if mp_ratio >= mp_threshold or self.aggression == "aggressive":
            skill = _best_attack_skill(attacker)
            if skill:
                return Action("skill", skill)

        # ── 규칙 4: 기타 디버프 (공격력 감소) ──
        if (self.aggression in ("balanced", "aggressive")
                and mp_ratio >= self.DEBUFF_MP_RESERVE
                and not _enemy_has_debuff(defender, "stg")):
            curse = _best_debuff_skill(attacker, stat="stg")
            if curse:
                return Action("skill", curse)

        # ── 규칙 5: MP 부족 → MP 포션 ──
        if mp_ratio <= self.MP_LOW_RATIO and attacker.learned_skills:
            potion = _best_mp_potion(attacker)
            if potion:
                return Action("item", potion)

        # ── 규칙 6: 기본 공격 ──
        return Action("attack", "attack")

    def __call__(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        return self.decide(attacker, defender)


# ────────────────────────────────────────────
# 적 AI
# ────────────────────────────────────────────

class EnemyAI:
    """
    몬스터 행동 패턴 AI.
    Unit.decide_action() 결과 기반으로 Action 반환.
    """

    ENEMY_DEBUFF_SKILLS = ["약화 1", "마약화 1", "저주 1", "둔화 1"]
    ENEMY_MAGIC_SKILLS  = ["파이어볼 1", "아이스 볼릿 1"]

    def __init__(self, unit=None):
        self.unit = unit

    def decide(self, attacker: EntitySnapshot, defender: EntitySnapshot) -> Action:
        action_type = "attack"
        if self.unit:
            action_type = self.unit.decide_action(defender)

        if action_type == "watch":
            return Action("watch", "watching")

        elif action_type == "magic" and attacker.mp > 0:
            from random import random
            if random() < 0.3:
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