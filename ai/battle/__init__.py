"""
Battle 패키지 — 전투 시스템 (Battle_Engine.py 분리본)

의존성 계층:
  Entity / ATB / Actions  (의존 없음)
  Elements / Damage       → Entity
  Skills                  → Entity, Damage, Elements
  Items                   → Entity, Elements
  Engine                  → 전부
"""
from .Entity import EntitySnapshot, Debuff, Buff, StatusEffect
from .ATB import ATBSystem
from .Actions import Action
from .Damage import DamageCalc, _apply_damage_with_shield
from .Elements import (
    REACTIONS, REACTION_EFFECTS, ELEMENT_STATUS,
    ELEMENT_STATUS_TURNS, ELEMENT_STATUS_LABEL, SAME_ELEMENT_STATUS_BONUS,
    REACTION_TABLE,
    _current_element, apply_element_and_react,
    check_element_reaction, try_apply_element_aura_and_status,
)
from .Skills import SKILL_META, execute_skill
from .Items import ITEM_META, use_item
from .Engine import TurnLog, BattleResult, BattleEngine, _escape_chance

__all__ = [
    "EntitySnapshot", "Debuff", "Buff", "StatusEffect",
    "ATBSystem", "Action", "DamageCalc", "_apply_damage_with_shield",
    "REACTIONS", "REACTION_EFFECTS", "ELEMENT_STATUS",
    "ELEMENT_STATUS_TURNS", "ELEMENT_STATUS_LABEL", "SAME_ELEMENT_STATUS_BONUS",
    "REACTION_TABLE", "_current_element", "apply_element_and_react",
    "check_element_reaction", "try_apply_element_aura_and_status",
    "SKILL_META", "execute_skill", "ITEM_META", "use_item",
    "TurnLog", "BattleResult", "BattleEngine", "_escape_chance",
]