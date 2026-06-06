"""
Battle_Engine.py — 하위 호환 shim

실제 전투 구현은 ai/battle/ 패키지에 있습니다.
기존 from ai.Battle_Engine import ... 경로를 유지하기 위해 재노출합니다.
"""
from __future__ import annotations

from ai.battle import *  # noqa: F401,F403
from ai.battle import (  # noqa: F401
    _apply_damage_with_shield,
    _current_element,
    _escape_chance,
    REACTION_TABLE,
)