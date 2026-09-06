"""
battle_session/targeting.py — 타겟 선택
"""
from __future__ import annotations



class TargetingMixin:
    """BattleSession에 타겟 선택 기능을 제공하는 mixin."""

    def _alive_enemies(self) -> list:
        """살아있는 적 리스트"""
        return [e for e in self.enemies if e.hp > 0]

    def _current_target(self):
        """플레이어 공격 대상 — 인덱스가 죽었으면 살아있는 첫 번째로 자동 변경"""
        if 0 <= self._target_idx < len(self.enemies):
            t = self.enemies[self._target_idx]
            if t.hp > 0:
                return t
        # 자동 폴백
        for e in self.enemies:
            if e.hp > 0:
                return e
        return None

    # ── 외부에서 호출하는 메서드 ─────────────