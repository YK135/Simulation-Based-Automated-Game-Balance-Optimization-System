"""
battle_session/atb_flow.py — ATB 흐름
"""
from __future__ import annotations
import copy
from random import randint, random as _random

from ai.battle import (
    apply_element_and_react, check_element_reaction, try_apply_element_aura_and_status,
    ITEM_META, Debuff, Buff, _current_element,
    EntitySnapshot, DamageCalc, execute_skill,
    SKILL_META, BattleEngine, Action, BattleResult, TurnLog,
)


class ATBFlowMixin:
    """BattleSession에 ATB 흐름 기능을 제공하는 mixin."""

    def _build_round_queue(self):
        """
        라운드 시작 — 살아있는 entity를 SPD 내림차순으로 큐 채우기.

        큐 형식: [(actor_type, idx), ...]
          actor_type: "player" 또는 "enemy"
          idx: enemy의 경우 self.enemies 인덱스, player는 -1
        """
        entities = []
        # 플레이어
        if self.player.hp > 0:
            entities.append(("player", -1, self.player.effective_spd()))
        # 적
        for i, e in enumerate(self.enemies):
            if e.hp > 0:
                entities.append(("enemy", i, e.effective_spd()))

        # SPD 내림차순 정렬 (같으면 플레이어 우선, 그 다음 슬롯 번호 빠른 적)
        entities.sort(key=lambda x: (-x[2], 0 if x[0] == "player" else 1, x[1]))

        # 큐에 (actor_type, idx) 형태로 저장
        self.action_queue = [(t, i) for t, i, _ in entities]

    def _cleanup_dead_from_queue(self):
        """죽은 적 큐에서 제거."""
        self.action_queue = [
            (t, i) for t, i in self.action_queue
            if t == "player" or (i < len(self.enemies) and self.enemies[i].hp > 0)
        ]

    def _peek_next_actor(self):
        """
        큐 맨 앞 행동자가 누구인지 반환 (큐 변경 X).
        반환: (next_actor: str, enemy_idx: int)
        """
        # 큐 비면 새 라운드
        if not self.action_queue:
            self._build_round_queue()
            self._cleanup_dead_from_queue()

        if not self.action_queue:
            return ("done", -1)

        actor_type, idx = self.action_queue[0]
        if actor_type == "player":
            return ("player", -1)
        else:
            return ("enemy", idx)

    def _accumulate_atb_all(self):
        """
        모든 살아있는 entity에 자기 SPD 만큼 ATB 누적.
        한 행동이 끝날 때마다 호출. 죽은 적은 누적 안 함.
        """
        # 플레이어
        if self.player.hp > 0:
            self.player_atb += float(self.player.effective_spd())
        # 적
        for i, e in enumerate(self.enemies):
            if e.hp > 0:
                self.enemy_atbs[i] += float(e.effective_spd())