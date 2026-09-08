"""
battle_session/rewards.py — 보상/결과
"""
from __future__ import annotations

from ai.battle import (
    BattleResult,
)


class RewardsMixin:
    """BattleSession에 보상/결과 기능을 제공하는 mixin."""

    def to_battle_result(self) -> BattleResult:
        """
        전투 종료 후 BattleResult로 변환.
        BalanceHook.after_battle()이 이 타입을 요구함 →
        LOG_Manager.save_player_log()가 data/Player_LOG/에 JSON 저장.

        self.logs에는 매 행동마다 추가된 TurnLog가 들어있음:
          - 플레이어: attack, skill, item, escape, *_failed
          - 적: attack, skill, watch, *_failed
        BehaviorAnalyzer가 이 데이터로 행동 패턴 분석.
        """
        winner = self.winner or "unknown"
        return BattleResult(
            winner=winner,
            total_turns=self.turn,
            logs=list(self.logs),
            final_player_hp=self.player.hp,
            final_enemy_hp=self.enemy.hp,
            player_name=self.player.name,
            enemy_name=self.enemy.name,
            final_player_items=list(self.items),
        )

    # ── 내부: 플레이어 행동 처리 ─────────────