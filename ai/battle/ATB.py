"""Battle/ATB.py — ATBSystem"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform


class ATBSystem:
    THRESHOLD = 100
    SPD_MULTIPLIER: float = 1.0

    def __init__(self, spd_multiplier: float = 1.0):
        self.player_pt: float = 0.0
        self.enemy_pt: float = 0.0
        self.x = spd_multiplier

    def tick(self, player_spd: float, enemy_spd: float) -> list[str]:
        self.player_pt += max(1.0, player_spd * self.x)
        self.enemy_pt += max(1.0, enemy_spd * self.x)

        candidates = []
        if self.player_pt >= self.THRESHOLD:
            candidates.append(("player", self.player_pt))
        if self.enemy_pt >= self.THRESHOLD:
            candidates.append(("enemy", self.enemy_pt))

        candidates.sort(key=lambda x: (x[1], 1 if x[0] == "player" else 0), reverse=True)
        actors = [c[0] for c in candidates]

        if "player" in actors:
            self.player_pt = 0.0
        if "enemy" in actors:
            self.enemy_pt = 0.0

        return actors

    def reset(self):
        self.player_pt = 0.0
        self.enemy_pt = 0.0


# ────────────────────────────────────────────
# 데미지 계산
# ────────────────────────────────────────────