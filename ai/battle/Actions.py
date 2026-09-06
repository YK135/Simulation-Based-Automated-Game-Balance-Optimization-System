"""Battle/Actions.py — Action"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Action:
    """
    action_type: "attack"|"skill"|"item"|"escape"|"watch"|"pass"
    detail:      스킬명 / 아이템명 / ""
    """
    action_type: str
    detail: str = ""