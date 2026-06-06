"""
battle_session/state.py — 상태 JSON
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


class StateMixin:
    """BattleSession에 상태 JSON 기능을 제공하는 mixin."""

    def _pack_status_list(self, entity) -> dict:
        """
        엔티티의 buffs / debuffs / 원소 상태 를 JSON 직렬화 가능 dict로.
        """
        return {
            "buffs": [
                {"stat": b.stat, "amount": round(b.amount, 3),
                 "turns": b.turns, "name": b.name}
                for b in getattr(entity, "buffs", [])
            ],
            "debuffs": [
                {"stat": d.stat, "amount": round(d.amount, 3),
                 "turns": d.turns, "name": d.name}
                for d in getattr(entity, "debuffs", [])
            ],
            "element_aura": _current_element(entity),
            "element_queue": list(getattr(entity, "element_queue", [])),
            "status_effects": [
                {"type": s.effect_type, "name": s.name, "turns": s.turns}
                for s in getattr(entity, "status_effects", [])
            ],
        }

    def _state(self, messages: list = None,
               next_actor: str = "player",
               acting_enemy_idx: int = -1) -> dict:
        # 첫 번째 살아있는 적 또는 마지막 적 (호환성 — 1대1 UI는 enemy_* 필드 사용)
        e = self.enemy
        diff_raw = getattr(e, "difficulty", "")

        # 플레이어 / 적 상태이상
        p_status = self._pack_status_list(self.player)
        e_status = self._pack_status_list(e)
        # 원소 상태 (UI 연동)
        player_element_aura   = p_status.get("element_aura", "")
        player_status_effects = p_status.get("status_effects", [])
        enemy_element_aura    = e_status.get("element_aura", "")
        enemy_status_effects  = e_status.get("status_effects", [])

        # 모든 적의 정보 — 다대일용 (UI는 이 배열을 받아서 슬롯 3·4·5에 매핑)
        # 각 적도 본인의 effective_* + buffs/debuffs 포함
        enemies_payload = []
        for i, en in enumerate(self.enemies):
            en_diff = getattr(en, "difficulty", "")
            en_status = self._pack_status_list(en)
            enemies_payload.append({
                "slot_index":       i,                        # UI 슬롯 매핑 (0=슬롯3, 1=슬롯4, 2=슬롯5)
                "atb":              round(self.enemy_atbs[i], 1), # 턴 순서 결정용 ATB (실효값)
                "name":             en.name,
                "lv":               en.lv,
                "alive":            en.hp > 0,
                "hp":               max(0.0, round(en.hp, 1)),
                "maxhp":            round(en.maxhp, 1),
                "mp":               round(en.mp, 1),
                "maxmp":            round(en.maxmp, 1),
                # 원본 스탯 (참고용)
                "stg":              round(en.stg, 1),
                "arm":              round(en.arm, 1),
                "sparm":            round(en.sparm, 1),
                "sp":               round(en.sp, 1),
                "spd":              round(en.spd, 1),
                "luc":              round(en.luc, 1),
                # ── 실효 스탯 (버프/디버프 반영) ──
                "effective_stg":    round(en.effective_stg(), 1),
                "effective_arm":    round(en.effective_arm(), 1),
                "effective_sparm":  round(en.effective_sparm(), 1),
                "effective_spd":    round(en.effective_spd(), 1),
                # ── 상태이상 ──
                "buffs":            en_status["buffs"],
                "debuffs":          en_status["debuffs"],
                "element_aura":     en_status["element_aura"],
                "status_effects":   en_status["status_effects"],
                "difficulty":       en_diff,
                "difficulty_label": self._DIFF_LABEL.get(en_diff, en_diff),
            })

        return {
            "turn":       self.turn,
            "is_boss":    self.is_boss,   # UI: 보스전이면 도망 버튼 숨김
            "player_hp":  round(self.player.hp, 1),
            "player_mp":  round(self.player.mp, 1),
            "player_maxhp": self.player.maxhp,
            "player_maxmp": self.player.maxmp,
            "player_atb": round(self.player_atb, 1),
            # ── 플레이어 실효 스탯 (UI 좌측 패널이 전투 중에 이걸로 갱신) ──
            "player_effective_stg":   round(self.player.effective_stg(), 1),
            "player_effective_arm":   round(self.player.effective_arm(), 1),
            "player_effective_sparm": round(self.player.effective_sparm(), 1),
            "player_effective_spd":   round(self.player.effective_spd(), 1),
            # ── 플레이어 상태이상 ──
            "player_buffs":   p_status["buffs"],
            "player_debuffs": p_status["debuffs"],
            "player_element_aura":   player_element_aura,
            "player_status_effects": player_status_effects,
            "enemy_element_aura":    enemy_element_aura,
            "enemy_status_effects":  enemy_status_effects,
            # ── 1대1 호환 (단수) — 기존 UI는 이 필드들 사용 ──
            "enemy_hp":   max(0.0, round(e.hp, 1)),
            "enemy_maxhp": e.maxhp,
            "enemy_name": e.name,
            "enemy_info": {
                "name":             e.name,
                "lv":               e.lv,
                "difficulty":       diff_raw,
                "difficulty_label": self._DIFF_LABEL.get(diff_raw, diff_raw),
                "hp":               max(0.0, round(e.hp, 1)),
                "maxhp":            round(e.maxhp, 1),
                "mp":               round(e.mp, 1),
                "maxmp":            round(e.maxmp, 1),
                "stg":              round(e.stg, 1),
                "arm":              round(e.arm, 1),
                "sparm":            round(e.sparm, 1),
                "sp":               round(e.sp, 1),
                "spd":              round(e.spd, 1),
                "luc":              round(e.luc, 1),
            },
            # ── 적 (단수) 실효 스탯 + 상태이상 ──
            "enemy_effective_stg":   round(e.effective_stg(), 1),
            "enemy_effective_arm":   round(e.effective_arm(), 1),
            "enemy_effective_sparm": round(e.effective_sparm(), 1),
            "enemy_effective_spd":   round(e.effective_spd(), 1),
            "enemy_buffs":           e_status["buffs"],
            "enemy_debuffs":         e_status["debuffs"],
            # ── 다대일 (배열) — UI는 enemies.length > 1 이면 다대일 모드로 전환 ──
            "enemies":          enemies_payload,
            "enemy_count":      len(self.enemies),
            "target_idx":       self._target_idx,  # 현재 선택된 타깃 슬롯
            # ── 공통 ──
            "items":      self.get_items(),
            "skills":     self.get_skills(),
            "done":       self.done,
            "winner":     self.winner,
            "messages":   messages or [],
            # ★ A1 응답 분리 — 다음 행동자 정보
            "next_actor":         next_actor,
            "acting_enemy_idx":   acting_enemy_idx,
        }