"""
Battle 패키지 — 전투 시스템 (Battle_Engine.py 분리본)

의존성 계층:
  Entity / ATB / Actions / EliteKit (→ Actions만)  (의존 없음/최소)
  Elements / Damage       → Entity
  Elements                → EliteKit (엘리트 원소 반응 후처리)
  BossKit                 → Actions (Skills는 함수 안에서 지연 import — 상수는 Skills가 읽는다)
  Skills                  → Entity, Damage, Elements, EliteKit, BossKit
  Items                   → Entity, Elements
  Engine                  → 전부
"""
from .Entity import EntitySnapshot, Debuff, Buff, StatusEffect, BLEED_STACK_MAX, BLEED_RATE_PER_STACK
from .ATB import ATBSystem
from .Actions import Action
from .Damage import DamageCalc, _apply_damage_with_shield, LifestealCast, lifesteal_heal
from .Elements import (
    REACTIONS, REACTION_EFFECTS, ELEMENT_STATUS,
    ELEMENT_STATUS_TURNS, ELEMENT_STATUS_LABEL, SAME_ELEMENT_STATUS_BONUS,
    REACTION_TABLE,
    _current_element, apply_element_and_react,
    check_element_reaction, try_apply_element_aura_and_status,
    mage_resonance_on_cast, mage_resonance_mult, REACT_PARTNER,
)
from .Skills import (
    SKILL_META, MONSTER_SKILL_META, execute_skill, execute_single_hit,
    consume_skill_mp, roll_multi_hit_count, physical_skill_mult, skill_atb_drain,
    consume_atb_drain, skill_effective_element, skill_requirement_error, SKILL_REQUIREMENT_LABEL,
    harvest_damage,
)
from .Items import ITEM_META, use_item
from .Engine import TurnLog, BattleResult, BattleEngine, _escape_chance
from .MonsterKit import MONSTER_KITS, get_monster_kit
from .EliteKit import elite_forced_action

__all__ = [
    "EntitySnapshot", "Debuff", "Buff", "StatusEffect", "BLEED_STACK_MAX", "BLEED_RATE_PER_STACK",
    "ATBSystem", "Action", "DamageCalc", "_apply_damage_with_shield", "LifestealCast", "lifesteal_heal",
    "REACTIONS", "REACTION_EFFECTS", "ELEMENT_STATUS",
    "ELEMENT_STATUS_TURNS", "ELEMENT_STATUS_LABEL", "SAME_ELEMENT_STATUS_BONUS",
    "REACTION_TABLE", "_current_element", "apply_element_and_react",
    "check_element_reaction", "try_apply_element_aura_and_status",
    "mage_resonance_on_cast", "mage_resonance_mult", "REACT_PARTNER",
    "SKILL_META", "MONSTER_SKILL_META", "execute_skill", "execute_single_hit", "consume_skill_mp",
    "roll_multi_hit_count", "physical_skill_mult", "skill_atb_drain",
    "consume_atb_drain", "skill_effective_element", "skill_requirement_error", "SKILL_REQUIREMENT_LABEL",
    "harvest_damage",
    "ITEM_META", "use_item",
    "TurnLog", "BattleResult", "BattleEngine", "_escape_chance",
    "MONSTER_KITS", "get_monster_kit",
    "elite_forced_action",
]
