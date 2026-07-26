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

    _ATTACK_SKILL_TYPES = ("physical", "magical", "tank_attack", "counter", "multi_hit")
    _ROGUE_DICE_MULT = {1: 0.75, 2: 0.90, 3: 1.00, 4: 1.15, 5: 1.25, 6: 1.00}

    def _is_attack_action(self, action) -> bool:
        """일반공격 또는 공격형 스킬인지 (전사 카운트/도적 주사위 대상)."""
        if action.action_type == "attack":
            return True
        if action.action_type == "skill":
            meta = SKILL_META.get(action.detail, {})
            return meta.get("type", "") in self._ATTACK_SKILL_TYPES
        return False

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
                    action = player_ai(self.player, self.enemy)

                    # ── 전사 패시브: '적 공격'(일반공격/공격형 스킬) 3회마다 maxhp 10% 회복 ──
                    #    아이템/버프/힐/디버프/도망은 카운트하지 않음 (게임 규칙과 동일 — Digital Twin)
                    if self.player.job == "전사" and self._is_attack_action(action):
                        self._player_action_count += 1
                        if self._player_action_count % 3 == 0:
                            self.player.passive_on_turn_start()  # 메시지는 시뮬에선 무시

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
            # ── 도적 주사위 (플레이어 공격, 게임 규칙과 동일) ──
            dice = None
            if actor == "player" and attacker.job == "도적":
                dice = randint(1, 6)
                attacker._suppress_crit = True
            dmg, is_dodge, is_crit = DamageCalc.physical(
                attacker.effective_stg(), attacker.luc,
                defender.effective_arm(), defender.luc,
                skill_mult=1.0,
                role="player" if actor == "player" else "monster",
                attacker=attacker,
                defender=defender,
            )
            if dice is not None:
                attacker._suppress_crit = False
                if not is_dodge:
                    dmg = int(round(dmg * self._ROGUE_DICE_MULT[dice]))
                    if dice == 6:
                        dmg = int(dmg * 1.5)
                        is_crit = True
                        self.atb.player_pt += 20.0
                    if dice in (3, 6):
                        from .Entity import StatusEffect
                        defender.apply_status_effect(StatusEffect(
                            effect_type="bleed", turns=3, name="출혈"))
            actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
            log.damage_dealt = actual
            log.hp_after = defender.hp
            log.is_dodge = is_dodge
            log.is_crit = is_crit

            # ── 탱커 패시브: 물리 피격 후 MP 회복 ──
            # defender가 탱커이고 회피하지 않고 데미지를 입은 경우 발동
            if not is_dodge and actual > 0:
                defender.passive_on_hit_received("physical")

            # ── 도적 패시브: 회피 시 반격 (몬스터 턴 내 즉시 기본공격, 일반 크리 허용) ──
            if is_dodge and actor == "enemy" and defender.job == "도적" and defender.hp > 0:
                c_dmg, c_dodge, c_crit = DamageCalc.physical(
                    defender.effective_stg(), defender.luc,
                    attacker.effective_arm(), attacker.luc,
                    skill_mult=1.0, role="player",
                    attacker=defender, defender=attacker,
                )
                if not c_dodge:
                    _apply_damage_with_shield(attacker, c_dmg)
                self.atb.player_pt += float(defender.effective_spd())
                self.logs.append(TurnLog(
                    turn=self.action_count, actor="player",
                    action="counter", action_detail="rogue_counter",
                    damage_dealt=0 if c_dodge else int(c_dmg),
                    hp_after=attacker.hp, mp_after=defender.mp,
                    is_dodge=c_dodge, is_crit=c_crit,
                ))

        elif action.action_type == "skill":
            # ── 도적 주사위 (공격형 스킬만) ──
            dice = None
            _meta = SKILL_META.get(action.detail, {})
            if (actor == "player" and attacker.job == "도적"
                    and _meta.get("type", "") in self._ATTACK_SKILL_TYPES):
                dice = randint(1, 6)
                attacker._suppress_crit = True
            # ── 연속공격류(hits>1 physical/magical): 개별 타격 판정 (Digital Twin) ──
            #    각 타격마다 회피/크리/원소반응/실드흡수/HP적용을 독립 수행.
            #    1v1 구조라 재타겟 없음 — defender 사망 시 남은 타격 중단.
            #    MP는 1회만 소모. 주사위 배율/강제크리는 각 타, 출혈/ATB는 1회.
            if (_meta.get("hits", 1) > 1
                    and _meta.get("type") in ("physical", "magical")):
                from .Skills import execute_single_hit, consume_skill_mp
                if consume_skill_mp(action.detail, attacker):
                    dmg, mp_lack, info = 0, True, ""
                else:
                    mp_lack, info = False, ""
                    _total_hp = 0
                    for _hi in range(_meta.get("hits", 1)):
                        if defender.hp <= 0:
                            break
                        _raw, _dodge, _crit = execute_single_hit(
                            action.detail, attacker, defender)
                        if _dodge:
                            continue
                        _d = int(_raw)
                        if dice is not None:
                            _d = int(round(_d * self._ROGUE_DICE_MULT[dice]))
                            if dice == 6 and not _crit:
                                _d = int(_d * 1.5)
                        if getattr(attacker, "_next_skill_bonus", 1.0) > 1.0:
                            _d = int(_d * attacker._next_skill_bonus)
                        _rm: list = []
                        _d = apply_element_and_react(
                            attacker, defender,
                            _meta.get("element", "") or "physical", _d, _rm)
                        _total_hp += _apply_damage_with_shield(defender, _d)
                    # 스킬 전체 1회 효과 (주사위 6 ATB / 출혈, 집중물약 소진)
                    if dice is not None:
                        if dice == 6:
                            self.atb.player_pt += 20.0
                        if dice in (3, 6) and defender.hp > 0:
                            from .Entity import StatusEffect
                            defender.apply_status_effect(StatusEffect(
                                effect_type="bleed", turns=3, name="출혈"))
                        attacker._suppress_crit = False
                        dice = None            # 기존 dice 후처리 블록 스킵
                    if getattr(attacker, "_next_skill_bonus", 1.0) > 1.0:
                        attacker._next_skill_bonus = 1.0
                    log.damage_dealt = _total_hp
                    log.hp_after = defender.hp
                    dmg = 0                    # 기존 공통 적용 경로 스킵 (이미 적용됨)
            else:
                dmg, mp_lack, info = execute_skill(action.detail, attacker, defender)
            if dice is not None:
                attacker._suppress_crit = False
                if not mp_lack and dmg > 0:
                    dmg = int(round(dmg * self._ROGUE_DICE_MULT[dice]))
                    if dice == 6:
                        dmg = int(dmg * 1.5)
                        self.atb.player_pt += 20.0
                    if dice in (3, 6):
                        from .Entity import StatusEffect
                        defender.apply_status_effect(StatusEffect(
                            effect_type="bleed", turns=3, name="출혈"))
            log.mp_after = attacker.mp

            # 집중물약 보너스 (next_skill_bonus)
            if not mp_lack and dmg > 0 and getattr(attacker, "_next_skill_bonus", 1.0) > 1.0:
                dmg = int(dmg * attacker._next_skill_bonus)
                attacker._next_skill_bonus = 1.0

            if not mp_lack:
                _meta = SKILL_META.get(action.detail, {})
                # ── 전사 광역 생존기 실드 (슬래시 계열) — 시뮬은 1v1이라 명중 1명 기준 ──
                _sph = _meta.get("shield_per_hit", 0.0)
                if _sph > 0 and attacker.job == "전사" and actor == "player" and dmg > 0:
                    _cap = _meta.get("shield_cap", 0.0)
                    _r = min(_sph, _cap)
                    attacker.shield = max(attacker.shield, attacker.maxhp * _r)

                # ── 전사 다대일 보정 실드 (연속공격1 계열) — BattleSession과 동일 조건 ──
                #    살아있는 적 2마리 이상일 때만 발동. 데미지/ATB는 변경하지 않는다.
                #    ※ BattleEngine은 현재 1v1(player vs enemy) 구조라 실전에서는
                #      alive_cnt가 1이므로 발동하지 않는다. 다중 적을 지원하게 되면
                #      (self.enemies 도입) 아래 조건이 그대로 동작한다 — Digital Twin 유지.
                _msh = _meta.get("multi_shield", 0.0)
                if _msh > 0 and attacker.job == "전사" and actor == "player":
                    _alive = [e for e in getattr(self, "enemies", [defender]) if e.hp > 0]
                    if len(_alive) >= 2:
                        _cap2 = attacker.maxhp * _meta.get("multi_shield_cap", 0.0)
                        _gained = attacker.maxhp * _msh
                        attacker.shield = min(_cap2, attacker.shield + _gained)
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