"""
battle_session/elite_actions.py — 엘리트 몬스터 패턴 실행
─────────────────────────────────────────────
판단/수치는 ai/battle/EliteKit.py, 실제 상태 변경/로그는 여기서 담당.
호출부: ai/battle_session/Enemy_Actions.py의 _single_enemy_action().
"""
from __future__ import annotations

from ai.battle import Buff, Debuff, EntitySnapshot
from ai.battle.EliteKit import (
    GOBLIN_START_BUFF_AMOUNT, GOBLIN_START_BUFF_TURNS,
    GOBLIN_RAGE_HP_THRESHOLD, GOBLIN_RAGE_STG_AMOUNT, GOBLIN_RAGE_DEF_AMOUNT,
    BAT_LIFESTEAL_RATIO, BAT_LIFESTEAL_CAP_RATIO, BAT_SCREAM_INTERVAL,
    SLIME_SPLIT_COUNT, SLIME_SPLIT_HP_RATIO, SLIME_SPLIT_STAT_RATIO,
    ASSASSIN_MARK_INTERVAL, ASSASSIN_MARK_TURNS, ASSASSIN_RETREAT_HP_THRESHOLD,
    GOLEM_PHASE_GUARD, GOLEM_PHASE_CHARGE, GOLEM_PHASE_STRIKE,
    PRIEST_REVIVE_HP_RATIO, PRIEST_PHASE_IDLE, PRIEST_PHASE_PREPARING,
)


class EliteActionsMixin:
    """BattleSession에 엘리트 몬스터 패턴 기능을 제공하는 mixin."""

    # ═══════════════════════════════════════════════════════
    # 사전 처리 (버프/스택/즉시효과) — 골렘/사제 제외한 엘리트 리더가
    # 정상 결정(EnemyAI.decide) 전에 거친다.
    # ═══════════════════════════════════════════════════════

    def _elite_pre_action(self, enemy: EntitySnapshot, msgs: list) -> None:
        et = enemy.enemy_type
        if et == "고블린":
            self._elite_goblin_pre(enemy, msgs)
        elif et == "박쥐":
            self._elite_bat_pre(enemy, msgs)
        elif et == "암살자":
            self._elite_assassin_pre(enemy, msgs)
        elif et in ("화염 슬라임", "번개 슬라임"):
            enemy.elite_pattern_turn += 1

    # ── 고블린 대장 ──
    def _elite_goblin_pre(self, enemy: EntitySnapshot, msgs: list) -> None:
        # elite_phase 0=버프 전, 1=버프 완료 — 전투 시작 1회만 (골렘의 phase와는 무관한 값)
        if enemy.elite_phase == 0:
            enemy.elite_phase = 1
            allies = [enemy] + [e for e in self.enemies if e is not enemy and e.hp > 0]
            for a in allies:
                a.apply_buff(Buff(stat="stg", amount=GOBLIN_START_BUFF_AMOUNT,
                                   turns=GOBLIN_START_BUFF_TURNS, name="전투 함성"))
            msgs.append(f"{enemy.name}이(가) 전투 함성을 내질렀다!")

        if (not enemy.elite_pattern_used
                and enemy.maxhp > 0 and enemy.hp / enemy.maxhp <= GOBLIN_RAGE_HP_THRESHOLD):
            enemy.elite_pattern_used = True
            enemy.apply_buff(Buff(stat="stg", amount=GOBLIN_RAGE_STG_AMOUNT,
                                   turns=9999, name="분노"))
            enemy.apply_debuff(Debuff(stat="arm", amount=GOBLIN_RAGE_DEF_AMOUNT,
                                       turns=9999, name="분노"))
            enemy.apply_debuff(Debuff(stat="sparm", amount=GOBLIN_RAGE_DEF_AMOUNT,
                                       turns=9999, name="분노"))
            msgs.append(f"{enemy.name}이(가) 분노하여 방어를 포기했다!")

    # ── 흡혈 박쥐 ──
    def _elite_bat_pre(self, enemy: EntitySnapshot, msgs: list) -> None:
        if enemy.elite_phase == 1:
            return  # 이번 행동은 예고된 비명이 강제됨 (EliteKit.elite_forced_action)
        enemy.elite_pattern_turn += 1
        if enemy.elite_pattern_turn >= BAT_SCREAM_INTERVAL:
            enemy.elite_pattern_turn = 0
            enemy.elite_phase = 1
            msgs.append(f"{enemy.name}이(가) 날개를 크게 펼치며 초음파를 모은다.")

    def _elite_bat_lifesteal(self, enemy: EntitySnapshot, hp_damage: int, msgs: list) -> None:
        if hp_damage <= 0:
            return
        heal_cap = enemy.maxhp * BAT_LIFESTEAL_CAP_RATIO
        heal = min(hp_damage * BAT_LIFESTEAL_RATIO, heal_cap)
        before = enemy.hp
        enemy.hp = min(enemy.maxhp, enemy.hp + heal)
        gained = int(enemy.hp - before)
        if gained > 0:
            msgs.append(f"{enemy.name}이(가) 피해를 흡수해 HP를 회복했다. (+{gained})")

    # ── 그림자 암살자 ──
    def _elite_assassin_pre(self, enemy: EntitySnapshot, msgs: list) -> None:
        if enemy.elite_phase == 1:
            return  # 이번 행동은 급소찌르기가 강제됨
        enemy.elite_pattern_turn += 1
        if enemy.elite_pattern_turn >= ASSASSIN_MARK_INTERVAL:
            enemy.elite_pattern_turn = 0
            enemy.elite_phase = 1
            self.player.apply_debuff(Debuff(
                stat="assassin_mark", amount=0.0, turns=ASSASSIN_MARK_TURNS, name="암살표식"))
            msgs.append(f"{enemy.name}이(가) 플레이어의 급소를 노린다!")
            msgs.append("암살 표식이 빛나며 급소 공격이 강화되었다!")

        if (not enemy.elite_pattern_used and enemy.maxhp > 0
                and enemy.hp / enemy.maxhp <= ASSASSIN_RETREAT_HP_THRESHOLD):
            enemy.elite_pattern_used = True
            enemy.apply_buff(Buff(stat="spd", amount=0.10, turns=2, name="추진력"))
            msgs.append(f"{enemy.name}이(가) 추진력을 사용해 거리를 벌린다!")

    def _has_assassin_mark(self) -> bool:
        return any(d.stat == "assassin_mark" for d in self.player.debuffs)

    def _clear_assassin_mark(self, msgs: list) -> None:
        before = len(self.player.debuffs)
        self.player.debuffs = [d for d in self.player.debuffs if d.stat != "assassin_mark"]
        if len(self.player.debuffs) < before:
            msgs.append("🛡 실드가 급소 공격을 완전히 막아 암살 표식이 사라졌다!")

    # ═══════════════════════════════════════════════════════
    # 고대 수호 골렘 — 전용 3단계 사이클 (EnemyAI를 거치지 않음)
    # ═══════════════════════════════════════════════════════

    def _elite_golem_action(self, enemy: EntitySnapshot, msgs: list) -> None:
        from ai.battle import execute_skill, TurnLog

        phase = enemy.elite_phase

        if phase == GOLEM_PHASE_GUARD:
            enemy.physical_hit_streak = 0
            execute_skill("수비태세2", enemy, self.player)
            msgs.append(f"{enemy.name}이(가) 수비 태세를 취한다!")
            enemy.elite_phase = GOLEM_PHASE_CHARGE
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="skill", action_detail="수비태세2",
                damage_dealt=0, hp_after=enemy.hp, mp_after=enemy.mp,
            ))
            return

        if phase == GOLEM_PHASE_CHARGE:
            enemy.physical_hit_streak = 0   # 충전 중 맞은 것만 그로기 판정에 반영
            msgs.append(f"{enemy.name}의 몸이 무겁게 떨린다 — 강타를 준비한다!")
            enemy.elite_phase = GOLEM_PHASE_STRIKE
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="watch", action_detail="elite_charge",
                hp_after=enemy.hp, mp_after=enemy.mp,
            ))
            return

        # phase == GOLEM_PHASE_STRIKE
        dmg, mp_lack, _ = execute_skill("몸통박치기_강화", enemy, self.player)
        if not mp_lack and dmg > 0:
            dmg = self._apply_dmg_shielded(self.player, dmg, msgs)
            msgs.append(f"{enemy.name} → 강화 몸통박치기! | {dmg} 데미지")
            msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")
        self.logs.append(TurnLog(
            turn=self.turn, actor="enemy", action="skill", action_detail="몸통박치기_강화",
            damage_dealt=int(dmg) if dmg > 0 else 0,
            hp_after=max(0, self.player.hp), mp_after=enemy.mp,
        ))
        enemy.elite_phase = GOLEM_PHASE_GUARD   # 성공 시 수비태세부터 재시작

    # ═══════════════════════════════════════════════════════
    # 증식 슬라임 — 분열
    # ═══════════════════════════════════════════════════════

    def _split_slime(self, origin: EntitySnapshot, msgs: list) -> None:
        if origin.elite_pattern_used:
            return
        origin.elite_pattern_used = True
        msgs.append(f"{origin.name}의 몸이 크게 흔들린다!")

        for _ in range(SLIME_SPLIT_COUNT):
            child = EntitySnapshot(
                name="작은 슬라임",
                hp=origin.maxhp * SLIME_SPLIT_HP_RATIO,
                maxhp=origin.maxhp * SLIME_SPLIT_HP_RATIO,
                mp=0, maxmp=0,
                stg=origin.stg * SLIME_SPLIT_STAT_RATIO,
                arm=origin.arm * SLIME_SPLIT_STAT_RATIO,
                sparm=origin.sparm * SLIME_SPLIT_STAT_RATIO,
                sp=origin.sp * SLIME_SPLIT_STAT_RATIO,
                luc=origin.luc * SLIME_SPLIT_STAT_RATIO,
                lv=origin.lv,
                spd=origin.spd * SLIME_SPLIT_STAT_RATIO,
                enemy_type="작은 슬라임",
                is_summoned=True,
                reward_eligible=False,
            )
            child._slot_index = len(self.enemies)
            self.enemies.append(child)
            self.enemy_atbs.append(0.0)
            self._origins.append(None)

        msgs.append(f"{origin.name}이(가) 작은 슬라임 두 마리로 분열했다!")

    # ═══════════════════════════════════════════════════════
    # 타락한 고위 사제 — 부활 의식 (Enemy_Actions._priest_action에서 호출)
    # ═══════════════════════════════════════════════════════

    def _priest_elite_revival_check(self, priest: EntitySnapshot, msgs: list) -> bool:
        """반환 True면 이번 행동을 부활 의식이 대신 소비함(다른 행동 스킵)."""
        if not getattr(priest, "elite_leader", False) or priest.elite_pattern_used:
            return False

        if priest.elite_phase == PRIEST_PHASE_IDLE:
            dead_allies = [e for e in self.enemies if e is not priest and e.hp <= 0]
            if not dead_allies:
                return False
            priest.elite_phase = PRIEST_PHASE_PREPARING
            msgs.append(f"{priest.name}이(가) 부활 의식을 시작했다!")
            msgs.append("의식이 완성되기 전에 사제를 처치해야 한다!")
            return True

        if priest.elite_phase == PRIEST_PHASE_PREPARING:
            dead_allies = [e for e in self.enemies if e is not priest and e.hp <= 0]
            if not dead_allies:
                priest.elite_phase = PRIEST_PHASE_IDLE
                return False
            target = dead_allies[0]
            target.hp = target.maxhp * PRIEST_REVIVE_HP_RATIO
            target.reward_eligible = False
            priest.elite_pattern_used = True
            priest.elite_phase = PRIEST_PHASE_IDLE
            msgs.append(f"{priest.name}의 부활 의식이 완성되어 {target.name}이(가) 되살아났다!")
            return True

        return False
