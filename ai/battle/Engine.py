"""Battle/Engine.py — BattleEngine, BattleResult, TurnLog"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform

from .Entity import EntitySnapshot, Debuff, Buff, StatusEffect
from .ATB import ATBSystem
from .Damage import DamageCalc, _apply_damage_with_shield
from .Skills import SKILL_META, execute_skill
from .Items import ITEM_META, use_item
from .Elements import apply_element_and_react
from .Actions import Action

@dataclass
class TurnLog:
    turn: int
    actor: str
    action: str
    action_detail: str
    damage_dealt: int = 0
    hp_after: float = 0.0
    mp_after: float = 0.0
    is_dodge: bool = False
    is_crit: bool = False
    debuff_applied: str = ""
    escaped: bool = False
    player_pt: float = 0.0
    enemy_pt: float = 0.0


@dataclass
class BattleResult:
    winner: str
    total_turns: int
    logs: list
    final_player_hp: float
    final_enemy_hp: float
    player_name: str
    enemy_name: str
    final_player_items: list = field(default_factory=list)


# ────────────────────────────────────────────
# ATB 시스템
# ────────────────────────────────────────────


def _escape_chance(player_spd: float, enemy_spd: float) -> float:
    ratio = player_spd / max(enemy_spd, 1.0)
    if ratio >= 2.0:
        return 0.95
    elif ratio >= 1.5:
        return 0.80
    elif ratio >= 1.0:
        return 0.60
    elif ratio >= 0.7:
        return 0.35
    else:
        return 0.15


class BattleEngine:
    MAX_TICKS = 500

    def __init__(self, player: EntitySnapshot, enemy: EntitySnapshot, spd_multiplier: float = 1.0):
        self.player = copy.deepcopy(player)
        self.enemy = copy.deepcopy(enemy)
        self.logs: list[TurnLog] = []
        self.atb = ATBSystem(spd_multiplier)
        self.tick_count = 0
        self.action_count = 0
        # 직업 패시브용 카운터
        self._player_action_count = 0   # 전사 패시브 (2번마다 회복)

    def run(self, player_ai, enemy_ai) -> BattleResult:
        # ── first_strike 처리 (암살자) ──
        if getattr(self.enemy, "first_strike", False):
            self.action_count += 1
            action = enemy_ai(self.enemy, self.player)
            self._execute_action(action, self.enemy, self.player, "enemy")
            if self.player.hp <= 0:
                return self._make_result("enemy")

        while self.tick_count < self.MAX_TICKS:
            self.tick_count += 1

            actors = self.atb.tick(
                self.player.effective_spd(),
                self.enemy.effective_spd(),
            )

            if not actors:
                continue

            for actor in actors:
                self.action_count += 1

                if actor == "player":
                    # ── 전사 패시브: 공격 3회마다 maxhp 10% 회복 ──
                    # 변경: 2회→3회로 발동 빈도 ~33% 감소 (과강 +76.5%p 시뮬결과 반영)
                    self._player_action_count += 1
                    if self.player.job == "전사" and self._player_action_count % 3 == 0:
                        self.player.passive_on_turn_start()  # 메시지는 시뮬에선 무시
 
                    action = player_ai(self.player, self.enemy)
                    res = self._execute_action(action, self.player, self.enemy, "player")
                    if res == "escaped":
                        return self._make_result("escaped")
                    if self.enemy.hp <= 0:
                        return self._make_result("player")
                else:
                    action = enemy_ai(self.enemy, self.player)
                    self._execute_action(action, self.enemy, self.player, "enemy")
                    if self.player.hp <= 0:
                        return self._make_result("enemy")

            if "player" in actors:
                self.player.tick_debuffs()
                self.player.tick_buffs()
            if "enemy" in actors:
                self.enemy.tick_debuffs()
                self.enemy.tick_buffs()

        winner = "player" if self.player.hp >= self.enemy.hp else "enemy"
        return self._make_result(winner)

    def _execute_action(self, action, attacker, defender, actor) -> str:
        log = TurnLog(
            turn=self.action_count,
            actor=actor,
            action=action.action_type,
            action_detail=action.detail,
            hp_after=defender.hp,
            mp_after=attacker.mp,
            player_pt=self.atb.player_pt,
            enemy_pt=self.atb.enemy_pt,
        )

        if action.action_type == "attack":
            dmg, is_dodge, is_crit = DamageCalc.physical(
                attacker.effective_stg(), attacker.luc,
                defender.effective_arm(), defender.luc,
                skill_mult=1.0,
                role="player" if actor == "player" else "monster",
                attacker=attacker,
                defender=defender,
            )
            actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
            log.damage_dealt = actual
            log.hp_after = defender.hp
            log.is_dodge = is_dodge
            log.is_crit = is_crit

            # ── 탱커 패시브: 물리 피격 후 MP 회복 ──
            # defender가 탱커이고 회피하지 않고 데미지를 입은 경우 발동
            if not is_dodge and actual > 0:
                defender.passive_on_hit_received("physical")

        elif action.action_type == "skill":
            dmg, mp_lack, info = execute_skill(action.detail, attacker, defender)
            log.mp_after = attacker.mp

            # 집중물약 보너스 (next_skill_bonus)
            if not mp_lack and dmg > 0 and getattr(attacker, "_next_skill_bonus", 1.0) > 1.0:
                dmg = int(dmg * attacker._next_skill_bonus)
                attacker._next_skill_bonus = 1.0

            if not mp_lack:
                if dmg > 0:
                    actual = _apply_damage_with_shield(defender, dmg)
                    log.damage_dealt = actual
                    log.hp_after = defender.hp

                    # ── 탱커 패시브: 스킬 피격 후 회복 (스킬 타입 따라 HP/MP) ──
                    # SKILL_META에서 type 조회 ("physical" or "magical")
                    skill_meta = SKILL_META.get(action.detail, {})
                    skill_type = skill_meta.get("type", "physical")
                    defender.passive_on_hit_received(skill_type)
                else:
                    log.hp_after = defender.hp

                if info:
                    log.debuff_applied = info
            else:
                dmg, is_dodge, is_crit = DamageCalc.physical(
                    attacker.effective_stg(), attacker.luc,
                    defender.effective_arm(), defender.luc,
                    skill_mult=1.0,
                    role="player" if actor == "player" else "monster",
                    attacker=attacker,
                    defender=defender,
                )
                actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
                log.action = "attack"
                log.action_detail = "attack(mp_fallback)"
                log.damage_dealt = actual
                log.hp_after = defender.hp
                log.is_dodge = is_dodge
                log.is_crit = is_crit

        elif action.action_type == "item":
            before_hp = defender.hp
            success = use_item(action.detail, attacker, enemies=[defender])
            log.action_detail = action.detail if success else "item_failed"
            log.damage_dealt = max(0, int(before_hp - defender.hp))
            log.hp_after = defender.hp
            log.mp_after = attacker.mp
            # 신속물약: 행동 후 ATB 추가 (플레이어만)
            if success and actor == "player" and getattr(attacker, "_pending_atb_bonus", 0) > 0:
                self.atb.player_pt += float(attacker._pending_atb_bonus)
                attacker._pending_atb_bonus = 0

        elif action.action_type == "escape":
            chance = _escape_chance(attacker.effective_spd(), defender.effective_spd())
            if random() <= chance:
                log.escaped = True
                self.logs.append(log)
                return "escaped"
            else:
                log.action_detail = "escape_failed"

        elif action.action_type == "watch":
            log.action_detail = "watching"

        elif action.action_type == "pass":
            pass

        self.logs.append(log)
        return "ok"

    def _make_result(self, winner: str) -> BattleResult:
        return BattleResult(
            winner=winner,
            total_turns=self.action_count,
            logs=self.logs,
            final_player_hp=self.player.hp,
            final_enemy_hp=self.enemy.hp,
            player_name=self.player.name,
            enemy_name=self.enemy.name,
            final_player_items=list(self.player.items),
        )


# ────────────────────────────────────────────
# Action
# ────────────────────────────────────────────