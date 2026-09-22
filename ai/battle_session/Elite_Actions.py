"""
battle_session/elite_actions.py — 엘리트 몬스터 패턴 실행
─────────────────────────────────────────────
판단/수치는 ai/battle/EliteKit.py, 실제 상태 변경/로그는 여기서 담당.
호출부: ai/battle_session/Enemy_Actions.py의 _single_enemy_action().
"""
from __future__ import annotations

from ai.battle import Buff, Debuff, EntitySnapshot, TurnLog
from ai.battle.MonsterKit import (
    bat_lifesteal_amount, PRIEST_QUICK_REVIVE_HP_RATIO, PRIEST_QUICK_REVIVE_SKILL,
)
from ai.battle.EliteKit import (
    GOBLIN_START_BUFF_AMOUNT, GOBLIN_START_BUFF_TURNS,
    GOBLIN_RAGE_HP_THRESHOLD, GOBLIN_RAGE_STG_AMOUNT, GOBLIN_RAGE_DEF_AMOUNT,
    GOBLIN_RALLY_INTERVAL, GOBLIN_RALLY_AMOUNT, GOBLIN_RALLY_TURNS,
    BAT_SCREAM_INTERVAL,
    SLIME_SPLIT_COUNT, SLIME_SPLIT_HP_RATIO, SLIME_SPLIT_STAT_RATIO,
    SLIME_SPLIT_TRIGGER_RATIO, SLIME_SPLIT_STUN_ACTIONS,
    ASSASSIN_MARK_INTERVAL, ASSASSIN_MARK_TURNS, ASSASSIN_SPRINT_HP_THRESHOLD,
    GOLEM_PHASE_GUARD, GOLEM_PHASE_CHARGE, GOLEM_PHASE_STRIKE,
    PRIEST_REVIVE_HP_RATIO, PRIEST_PHASE_IDLE, PRIEST_PHASE_PREPARING,
)


class EliteActionsMixin:
    """BattleSession에 엘리트 몬스터 패턴 기능을 제공하는 mixin."""

    def _check_elite_hp(self, target: EntitySnapshot, msgs: list) -> None:
        """엘리트 리더의 HP가 방금 바뀐 뒤 걸리는 문턱 판정 — 분열(살아있을 때/죽었을 때)과
        부활 의식 중단. 직접 피해(_apply_dmg_shielded)와 상태이상 DoT(Battlesession의
        원소 상태이상 틱 처리) 양쪽 경로에서 모두 호출해야 한다 — 한쪽에서만 호출하면
        화상/출혈로 문턱을 넘은 증식 슬라임이 분열하지 않는다."""
        if not getattr(target, "elite_leader", False):
            return
        et = getattr(target, "enemy_type", "")
        if target.hp > 0:
            # 살아있는 채 문턱을 넘은 증식 슬라임 — 본체는 남고 새끼 둘이 붙는다
            if (et == "슬라임" and target.maxhp > 0
                    and target.hp / target.maxhp <= SLIME_SPLIT_TRIGGER_RATIO):
                self._split_slime(target, msgs, alive=True)
            return
        if et == "슬라임":
            self._split_slime(target, msgs)
        elif et == "사제" and getattr(target, "elite_phase", 0) != 0:
            msgs.append(f"{target.name}이(가) 쓰러져 부활 의식이 중단되었다!")

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

        # ── 호령 (브리프 3장) — 격노 이후 대장의 행동 3회마다 살아있는 동료 STG +10%(2턴) ──
        # ① 카운터는 전투 시작부터 돌고 발동만 격노 뒤에 열린다. 격노 뒤부터 세면
        #    대부분의 전투가 그 전에 끝나 발동이 0.0~0.6회/전투로 사문화된다
        #    (실측: 이 방식이 2~5배 자주 터지고 승률 차이는 양쪽 모두 A와 ±0.1%p).
        # ② 대장 자신은 대상이 아니다 — apply_buff는 같은 stat을 덮어쓰므로,
        #    자신에게 걸면 분노(STG +15%, 무기한)가 호령(+10%, 2턴)에 지워져
        #    격노가 오히려 약해진다.
        # ③ 동료가 하나도 없으면 카운터를 소비하지 않는다(대장 단독 전투에서는
        #    아무 일도 일어나지 않고, 사제가 동료를 되살리면 바로 터진다).
        enemy.elite_pattern_turn += 1
        if not enemy.elite_pattern_used or enemy.elite_pattern_turn < GOBLIN_RALLY_INTERVAL:
            return
        allies = [e for e in self.enemies if e is not enemy and e.hp > 0]
        if not allies:
            return
        enemy.elite_pattern_turn = 0
        for a in allies:
            a.apply_buff(Buff(stat="stg", amount=GOBLIN_RALLY_AMOUNT,
                              turns=GOBLIN_RALLY_TURNS, name="호령"))
        msgs.append(f"{enemy.name}이(가) 호령했다! 동료 {len(allies)}마리의 공격력이 올랐다!")

    # ── 흡혈 박쥐 ──
    # elite_phase: 0=평시, 1=이번 행동에 막 예고됨(elite_forced_action이 watch로
    # 소비하며 2로 전환), 2=다음 행동에 초음파비명 발동 대기.
    # 예고(phase 0→1)와 실제 발동(phase 2)이 반드시 서로 다른 행동에서
    # 일어나도록 elite_forced_action이 전환을 전담한다 — 여기서 바로
    # 1을 세팅하고 같은 행동에서 EnemyAI.decide()가 곧장 소비해버리면
    # "예고 후 다음 행동에 발동"이 아니라 예고와 동시에 발동해버린다.
    def _elite_bat_pre(self, enemy: EntitySnapshot, msgs: list) -> None:
        if enemy.elite_phase != 0:
            return  # 예고/발동 대기 중 — elite_forced_action이 처리
        enemy.elite_pattern_turn += 1
        if enemy.elite_pattern_turn >= BAT_SCREAM_INTERVAL:
            enemy.elite_pattern_turn = 0
            enemy.elite_phase = 1
            msgs.append(f"{enemy.name}이(가) 날개를 크게 펼치며 초음파를 모은다.")

    def _bat_lifesteal(self, enemy: EntitySnapshot, hp_damage: int, msgs: list) -> None:
        """박쥐 흡혈 — 일반 박쥐(10%/상한 5%)와 엘리트 흡혈 박쥐(20%/10%)가 같은 경로.
        비율·상한은 MonsterKit.bat_lifesteal_amount()가 elite_leader로 가른다."""
        heal = bat_lifesteal_amount(enemy, hp_damage)
        if heal <= 0:
            return
        before = enemy.hp
        enemy.hp = min(enemy.maxhp, enemy.hp + heal)
        enemy._record_hit("heal", enemy.hp - before)
        gained = int(enemy.hp - before)
        if gained > 0:
            msgs.append(f"{enemy.name}이(가) 피해를 흡수해 HP를 회복했다. (+{gained})")

    # ── 그림자 암살자 ── (박쥐와 동일한 phase 0/1/2 규약 — elite_forced_action 참고)
    def _elite_assassin_pre(self, enemy: EntitySnapshot, msgs: list) -> None:
        if enemy.elite_phase != 0:
            return  # 예고/발동 대기 중 — elite_forced_action이 처리
        enemy.elite_pattern_turn += 1
        if enemy.elite_pattern_turn >= ASSASSIN_MARK_INTERVAL:
            enemy.elite_pattern_turn = 0
            enemy.elite_phase = 1
            self.player.apply_debuff(Debuff(
                stat="assassin_mark", amount=0.0, turns=ASSASSIN_MARK_TURNS, name="암살표식"))
            msgs.append(f"{enemy.name}이(가) 플레이어의 급소를 노린다!")
            msgs.append("암살 표식이 빛나며 급소 공격이 강화되었다!")

        if (not enemy.elite_pattern_used and enemy.maxhp > 0
                and enemy.hp / enemy.maxhp <= ASSASSIN_SPRINT_HP_THRESHOLD):
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

    def _split_slime(self, origin: EntitySnapshot, msgs: list, alive: bool = False) -> None:
        """분열 — 전투당 1회. alive=True면 본체가 살아남고 그 대신
        SLIME_SPLIT_STUN_ACTIONS만큼 행동을 건너뛴다(브리프 3장의 "분열 직후 본체 행동 불가")."""
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
            self.enemies.append(child)
            self.enemy_atbs.append(0.0)
            self._origins.append(None)

        msgs.append(f"{origin.name}이(가) 작은 슬라임 두 마리로 분열했다!")
        if alive:
            origin.split_stun = SLIME_SPLIT_STUN_ACTIONS
            msgs.append(f"{origin.name}은(는) 갈라진 충격으로 {SLIME_SPLIT_STUN_ACTIONS}번의 "
                        f"행동을 잃었다 — 지금이 기회다!")

    # ═══════════════════════════════════════════════════════
    # 사제 — 부활 (Enemy_Actions._priest_action에서 호출)
    #   엘리트(타락한 고위 사제): 2단계 의식(준비 → 발동, maxHP 25%), 준비 중 처치 시 취소
    #   일반 사제: 약식 소생 — 예고 없이 자기 행동으로 즉시 maxHP 10% (2장, 전투당 1회)
    #   둘 다 elite_pattern_used 하나로 "전투당 1회"를 센다.
    # ═══════════════════════════════════════════════════════

    def _revivable_allies(self, priest: EntitySnapshot) -> list:
        """죽은 아군 — 달아난 개체(fled)는 전투에서 빠진 것이라 되살리지 않는다."""
        return [e for e in self.enemies
                if e is not priest and e.hp <= 0 and not getattr(e, "fled", False)]

    def _priest_revival_check(self, priest: EntitySnapshot, msgs: list) -> bool:
        """반환 True면 이번 행동을 부활(의식/약식 소생)이 대신 소비함(다른 행동 스킵)."""
        if priest.elite_pattern_used:
            return False

        if not getattr(priest, "elite_leader", False):
            # ── 일반 사제: 약식 소생 (즉시) ──
            dead_allies = self._revivable_allies(priest)
            if not dead_allies:
                return False
            target = dead_allies[0]
            self._note_fx_target("enemy", self._enemy_slot_of(target))
            before = target.hp
            target.hp = target.maxhp * PRIEST_QUICK_REVIVE_HP_RATIO
            target._record_hit("heal", target.hp - before)
            priest.elite_pattern_used = True
            msgs.append(f"{priest.name} → {PRIEST_QUICK_REVIVE_SKILL}! {target.name}이(가) 되살아났다! "
                        f"(HP {int(PRIEST_QUICK_REVIVE_HP_RATIO * 100)}%)")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="skill",
                action_detail=PRIEST_QUICK_REVIVE_SKILL,
                damage_dealt=-int(target.hp - before),
                hp_after=target.hp, mp_after=priest.mp,
            ))
            self._sync_goblin_pack(msgs)    # 되살아난 것이 고블린이면 무리 수가 다시 는다
            return True

        if priest.elite_phase == PRIEST_PHASE_IDLE:
            dead_allies = self._revivable_allies(priest)
            if not dead_allies:
                return False
            priest.elite_phase = PRIEST_PHASE_PREPARING
            self._note_fx("부활 의식 준비", "ritual")
            self._note_fx_target("enemy", self._enemy_slot_of(dead_allies[0]))
            msgs.append(f"{priest.name}이(가) 부활 의식을 시작했다!")
            msgs.append("의식이 완성되기 전에 사제를 처치해야 한다!")
            return True

        if priest.elite_phase == PRIEST_PHASE_PREPARING:
            dead_allies = self._revivable_allies(priest)
            if not dead_allies:
                priest.elite_phase = PRIEST_PHASE_IDLE
                return False
            target = dead_allies[0]
            self._note_fx("부활 의식 완성", "ritual")
            self._note_fx_target("enemy", self._enemy_slot_of(target))
            revive_before = target.hp
            target.hp = target.maxhp * PRIEST_REVIVE_HP_RATIO
            target._record_hit("heal", target.hp - revive_before)
            # reward_eligible은 건드리지 않는다 — 보상은 전투 종료 시 최종
            # 상태 기준으로 딱 한 번만 계산되므로(_get_defeated_list), 여기서
            # False로 마킹하면 "추가 보상 방지"가 아니라 이 동료를 처치한
            # 정당한 보상까지 통째로 사라진다. 애초에 이중 지급 위험 자체가
            # 없으므로(재처치해도 계산은 여전히 1회) 별도 처리 불필요.
            priest.elite_pattern_used = True
            priest.elite_phase = PRIEST_PHASE_IDLE
            msgs.append(f"{priest.name}의 부활 의식이 완성되어 {target.name}이(가) 되살아났다!")
            self._sync_goblin_pack(msgs)
            return True

        return False
