"""
battle_session/enemy_actions.py — 적 행동
"""
from __future__ import annotations
from random import random as _random

from ai.battle import (
    apply_element_and_react, Buff, DamageCalc,
    execute_skill, SKILL_META, TurnLog, _escape_chance,
)
from ai.battle.Skills import skill_atb_drain, frost_ward_retaliate, _resolve_meta
from ai.battle.EliteKit import (
    ASSASSIN_MARK_BONUS, ICE_SLIME_ARMOR_REDUCTION,
)
from ai.battle.BossKit import is_midboss, is_finalboss
from ai.battle.MonsterKit import (
    is_goblin, goblin_pack_bonus, goblin_wants_to_flee, BAT_TYPE,
)


class _EnemyProbe:
    """_resolve_meta가 몬스터 표(MONSTER_SKILL_META)를 먼저 보게 하는 표식 — enemy_type만 있으면 된다."""
    enemy_type = "몬스터"


class EnemyActionsMixin:
    """BattleSession에 적 행동 기능을 제공하는 mixin."""

    def _rogue_counter(self, enemy, msgs: list):
        """
        도적 패시브 — 적 공격 회피 시 반격.
        · 공격한 몬스터의 턴 안에서 즉시 기본 공격 (내 턴 소비 X)
        · 주사위 미적용 — 일반 luc 크리 가능 (_suppress_crit 미설정 상태)
        · ATB 획득 (행동으로 취급)
        """
        if getattr(self.player, "job", "") != "도적":
            return
        if self.player.hp <= 0 or enemy.hp <= 0:
            return
        # 연막(버프 dodge) 중 회피 성공 → 패 고치기 무료 재굴림 1회 (배운 경우만)
        if self.player.buff_amount("dodge") > 0 and "패 고치기" in self.player.learned_skills:
            self.player.free_rerolls += 1
            msgs.append("🌫 연막 속 회피 — 패 고치기 무료 재굴림 +1")
        dmg, dodge, crit = DamageCalc.physical(
            self.player.effective_stg(), self.player.luc,
            enemy.effective_arm(),        enemy.luc,
            skill_mult=1.0,
            role="player",
            attacker=self.player,
            defender=enemy,
        )
        msgs.append(f"⚔ [도적 반격] {self.player.name}의 반격!")
        actual = 0 if dodge else int(dmg)
        if dodge:
            msgs.append(f"  └ {enemy.name}이(가) 반격을 회피했다!")
        else:
            actual = apply_element_and_react(self.player, enemy, "physical", actual, msgs)
            self._new_lifesteal_cast()          # 반격도 공격 1회 — 자기 흡혈 예산
            actual = self._player_hit(enemy, actual, msgs)
            tag = " (치명타!)" if crit else ""
            msgs.append(f"  └ {enemy.name}에게{tag} {actual} 데미지")
            msgs.append(f"     {enemy.name} HP: {max(0, int(enemy.hp))}")
        # 반격도 행동 — ATB 획득
        self.player_atb += float(self.player.effective_spd())
        self.logs.append(TurnLog(
            turn=self.turn,
            actor="player",
            action="counter",
            action_detail="rogue_counter",
            damage_dealt=actual,
            hp_after=max(0, enemy.hp),
            mp_after=self.player.mp,
            is_dodge=dodge,
            is_crit=crit,
        ))

    # ─────────────────────────────────────────────
    # 고블린 — 무리 전술 / 겁쟁이 (ai/battle/MonsterKit.py 「일반 몬스터 정체성 규칙」)
    # ─────────────────────────────────────────────

    def _sync_goblin_pack(self, msgs: list | None = None) -> float:
        """살아있는 고블린 수로 각 고블린의 pack_bonus를 다시 맞춘다.
        전투 시작·고블린 사망/도주·소생 직후에 부른다 — "한 마리를 처치하면 즉시 사라짐".
        msgs가 있으면 값이 바뀔 때만 한 줄 남긴다. 반환: 새 가산 비율."""
        goblins = [e for e in self.enemies if is_goblin(e)]
        if not goblins:
            return 0.0
        alive = [g for g in goblins if g.hp > 0]
        bonus = goblin_pack_bonus(len(alive))
        changed = any(abs(g.pack_bonus - (bonus if g.hp > 0 else 0.0)) > 1e-9 for g in goblins)
        for g in goblins:
            g.pack_bonus = bonus if g.hp > 0 else 0.0
        if msgs is None:
            return bonus
        # 전투 시작(__init__)은 조용히 맞추므로, 첫 고블린 행동에서 한 번은 발동 중임을 알린다
        announced = getattr(self, "_goblin_pack_announced", False)
        if bonus > 0 and (changed or not announced):
            self._goblin_pack_announced = True
            msgs.append(f"🗡 고블린 무리 전술! 살아있는 고블린 {len(alive)}마리 — "
                        f"각자 공격력 +{int(round(bonus * 100))}%")
        elif bonus <= 0 and changed:
            msgs.append("고블린 무리가 흩어졌다 — 무리 전술 해제")
        return bonus

    def _goblin_flee_attempt(self, goblin, msgs: list) -> bool:
        """겁쟁이 — 조건이 맞으면 이번 행동으로 도주를 시도한다(전투당 1회, 성공·실패 모두 차례 소비).
        반환 True면 이번 행동을 여기서 소비했다. 판정은 플레이어 도주와 같은 _escape_chance."""
        if not goblin_wants_to_flee(goblin, self.enemies):
            return False
        goblin.flee_attempted = True
        chance = _escape_chance(goblin.effective_spd(), self.player.effective_spd())
        if _random() <= chance:
            goblin.fled = True
            goblin.hp = 0.0
            goblin.reward_eligible = False      # 놓친 개체 — 경험치·골드 대상에서 빠진다 (_get_defeated_list)
            msgs.append(f"{goblin.name} → 도주! 겁을 먹고 달아났다... (이 개체의 보상 소멸)")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="escape", action_detail="goblin_flee",
                hp_after=self.player.hp, mp_after=goblin.mp, escaped=True,
            ))
            self._sync_goblin_pack(msgs)
        else:
            msgs.append(f"{goblin.name} → 도주 시도! 하지만 도주에 실패했다!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="escape_failed", action_detail="goblin_flee",
                hp_after=self.player.hp, mp_after=goblin.mp,
            ))
        return True

    _ENEMY_ATTACK_TYPES = ("physical", "magical", "tank_attack", "counter", "multi_hit")

    def _enemy_attacked_player(self, new_logs) -> bool:
        """이번 적 행동이 플레이어를 노린 공격이었나 (회피 포함) — 서리 결계 반격 판정용."""
        for lg in new_logs:
            if lg.actor != "enemy" or lg.action not in ("attack", "skill"):
                continue
            if lg.action == "attack":
                return True
            name = (lg.action_detail or "").split("(", 1)[0]
            meta = _resolve_meta(name, _EnemyProbe) or {}
            if meta.get("type") in self._ENEMY_ATTACK_TYPES:
                return True
        return False

    def _single_enemy_action(self, enemy, msgs: list):
        """단일 적의 1회 행동 처리. ATB 큐가 적 1마리씩 액터 단위로 넘겨준다
        (다대일이어도 한 번에 한 마리) — Battlesession._step_core 참고."""
        n_logs = len(self.logs)
        self._single_enemy_action_core(enemy, msgs)
        # 서리 결계(마법사 버프): 나를 공격한 적에게 ice + SPD 감소 — 엔진도 같은 함수
        if enemy.hp > 0 and self.player.hp > 0 and self._enemy_attacked_player(self.logs[n_logs:]):
            frost_ward_retaliate(self.player, enemy, msgs)

    def _single_enemy_action_core(self, enemy, msgs: list):
        # ── 사제 전용 행동 (다른 아군 회복/버프) ──
        # enemy_type이 "사제"면 별도 로직 사용. 일반 EnemyAI 안 거침.
        # ⚠ return 제거 — 메서드 끝의 tick 처리(buff/debuff 1턴 감소)를
        #    사제도 동일하게 거쳐야 함 (Codex 지적 반영).
        if is_goblin(enemy):
            # 무리 전술은 행동 직전에 한 번 더 맞춘다(첫 행동에서 발동 안내). 겁쟁이 도주는
            # 정상 행동보다 앞서며, 시도했으면(성공/실패 모두) 이번 행동은 그것으로 끝.
            self._sync_goblin_pack(msgs)
            if self._goblin_flee_attempt(enemy, msgs):
                enemy.tick_buffs()
                enemy.tick_debuffs()
                self.player.tick_debuffs()
                return

        if getattr(enemy, "enemy_type", "") == "사제":
            self._priest_action(enemy, msgs)
        elif getattr(enemy, "elite_leader", False) and enemy.enemy_type == "골렘":
            # 골렘 3단계 고정 사이클(수비태세→충전예고→강화공격)은 확률 기반
            # EnemyAI를 거치지 않는 전용 분기.
            self._elite_golem_action(enemy, msgs)
        else:
            if is_midboss(enemy):
                # 중간 보스 — 페이즈·예고·「대지 균열」은 Boss_Actions가 결정한다.
                # None이면 예고/균열을 이미 처리·로그한 것이고, 나머지 행동
                # (일반공격/몸통박치기2/관망)은 아래 공통 경로를 그대로 탄다.
                action = self._midboss_pre_action(enemy, msgs)
            elif is_finalboss(enemy):
                # 최종 보스 — 4페이즈(원소 순환·소환·잠식·종언)는 Boss_Actions가 결정·실행한다
                action = self._finalboss_pre_action(enemy, msgs)
            else:
                # ── 엘리트 사전 처리 (버프/스택/즉시효과) — 결정 전에 실행 ──
                if getattr(enemy, "elite_leader", False):
                    self._elite_pre_action(enemy, msgs)

                # ── 일반 몬스터 행동 (기존 로직) ──
                chapter = (getattr(self, "battle_meta", {}) or {}).get("chapter", 1)
                action = self._enemy_ai(enemy, self.player, chapter=chapter)

            if action is None:
                pass
            elif action.action_type == "attack":
                dmg, dodge, crit = DamageCalc.physical(
                    enemy.effective_stg(), enemy.luc,
                    self.player.effective_arm(), self.player.luc,
                    skill_mult=1.0,
                    role="monster",
                    attacker=enemy,
                    defender=self.player,
                )
                actual = 0 if dodge else int(dmg)
                if dodge:
                    msgs.append(f"{self.player.name}이(가) {enemy.name}의 공격을 회피했다!")
                    self._rogue_counter(enemy, msgs)   # 도적: 회피 시 반격
                else:
                    # ── 물리 원소 반응 (적 기본공격) ──
                    atk_elem = getattr(enemy, "attack_element", "")
                    actual = apply_element_and_react(enemy, self.player, atk_elem or "physical", actual, msgs)
                    dmg = self._apply_dmg_shielded(self.player, actual, msgs)
                    tag = " (치명타!)" if crit else ""
                    msgs.append(f"{enemy.name} → 공격{tag} | {dmg} 데미지")
                    msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

                    # ── 탱커 패시브: 물리 피격 시 MP 회복 ──
                    tanker_msg = self.player.passive_on_hit_received("physical")
                    if tanker_msg:
                        msgs.append(tanker_msg)

                    if enemy.enemy_type == BAT_TYPE:
                        self._bat_lifesteal(enemy, dmg, msgs)   # 일반 10%/5% · 엘리트 20%/10%
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="enemy",
                    action="attack",
                    action_detail="basic_attack",
                    damage_dealt=actual,
                    hp_after=max(0, self.player.hp),
                    mp_after=enemy.mp,
                    is_dodge=dodge,
                    is_crit=crit,
                ))

            elif action.action_type == "skill":
                dmg, mp_lack, debuff_name = execute_skill(
                    action.detail, enemy, self.player
                )
                if mp_lack:
                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="enemy",
                        action="skill_failed",
                        action_detail=f"{action.detail}(mp_lack)",
                        damage_dealt=0,
                        hp_after=self.player.hp,
                        mp_after=enemy.mp,
                    ))
                else:
                    if dmg > 0:
                        is_elite = getattr(enemy, "elite_leader", False)
                        is_assassin_finisher = (is_elite and enemy.enemy_type == "암살자"
                                                 and action.detail == "급소찌르기1")
                        if is_assassin_finisher and self._has_assassin_mark():
                            dmg = int(dmg * (1 + ASSASSIN_MARK_BONUS))
                            msgs.append("🎯 암살 표식 — 급소찌르기 피해 증가!")

                        dmg = self._apply_dmg_shielded(self.player, dmg, msgs)
                        msgs.append(f"{enemy.name} → {action.detail} | {dmg} 데미지")
                        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

                        # ── 탱커 패시브: 스킬 피격 시 회복 (스킬 타입 따라) ──
                        skill_meta = SKILL_META.get(action.detail, {})
                        skill_type = skill_meta.get("type", "physical")
                        tanker_msg = self.player.passive_on_hit_received(skill_type)
                        if tanker_msg:
                            msgs.append(tanker_msg)

                        if enemy.enemy_type == BAT_TYPE:
                            self._bat_lifesteal(enemy, dmg, msgs)
                        if is_assassin_finisher and dmg == 0:
                            self._clear_assassin_mark(msgs)
                    elif skill_atb_drain(action.detail, enemy) > 0:
                        # 날갯소리 — 피해 없이 플레이어 ATB를 깎는다 (Engine과 같은 skill_atb_drain 값)
                        drain = skill_atb_drain(action.detail, enemy)
                        before_atb = self.player_atb
                        self.player_atb = max(0.0, self.player_atb - drain)
                        msgs.append(f"{enemy.name} → {action.detail}! {self.player.name}의 ATB "
                                    f"−{int(before_atb - self.player_atb)}")
                    elif debuff_name:
                        msgs.append(f"{enemy.name} → {action.detail} 사용!")

                    self.logs.append(TurnLog(
                        turn=self.turn,
                        actor="enemy",
                        action="skill",
                        action_detail=action.detail,
                        damage_dealt=int(dmg) if dmg > 0 else 0,
                        hp_after=max(0, self.player.hp),
                        mp_after=enemy.mp,
                        debuff_applied=debuff_name or "",
                    ))

            elif action.action_type == "watch":
                if action.detail != "elite_telegraph":
                    # elite_telegraph는 _elite_*_pre()가 이미 예고 메시지를
                    # 출력했으므로 여기서 또 "기회를 엿보고 있다"를 덧붙이지 않는다.
                    msgs.append(f"{enemy.name}이(가) 기회를 엿보고 있다...")
                self.logs.append(TurnLog(
                    turn=self.turn,
                    actor="enemy",
                    action="watch",
                    action_detail="watching",
                    hp_after=self.player.hp,
                    mp_after=enemy.mp,
                ))

        # ── 이 적의 행동 1회 처리 후 turn 감소 ──
        # · 적 본인의 버프/디버프 1턴 소진
        # · 플레이어 디버프도 적 행동 단위로 1턴 소진
        #   (다대일이면 적 N마리가 행동 → 디버프가 N번 빨리 풀림 — 의도된 동작)
        # ⚠ 이 블록은 사제/일반 모든 경로에서 반드시 실행됨 (위 if/else 밖에 있음).
        enemy.tick_buffs()
        enemy.tick_debuffs()
        self.player.tick_debuffs()

        # ── 엘리트 빙결 슬라임: 파쇄로 해제된 빙결 갑옷 복구 카운트다운 ──
        # (반응형 패턴이라 사전/전용 분기 없이 여기서만 처리)
        if (getattr(enemy, "elite_leader", False) and enemy.enemy_type == "빙결 슬라임"
                and enemy.elite_phase == 1):
            enemy.elite_pattern_turn -= 1
            if enemy.elite_pattern_turn <= 0:
                enemy.elite_phase = 0
                # 파쇄로 되돌려놓은 원래 저항(Elements._elite_ice_slime_break가
                # / (1-ICE_SLIME_ARMOR_REDUCTION)로 복원한 값) 위에 다시 곱해
                # 갑옷 활성 상태로 — 1.0 기준 고정값이면 원래 저항이 1.0이
                # 아닌 몬스터(빙결 슬라임 기본 0.80 등)에서 틀린 값이 된다.
                enemy.physical_resist = enemy.physical_resist * (1 - ICE_SLIME_ARMOR_REDUCTION)
                msgs.append(f"{enemy.name}의 빙결 갑옷이 복구되었다!")


    # ─────────────────────────────────────────────
    # 사제 전용 행동 (서포터형)

    def _enemy_slot_of(self, unit) -> int:
        """적 개체의 슬롯 번호 (동일 객체 기준 — 이름이 같은 개체가 여럿일 수 있다)."""
        return next((i for i, e in enumerate(self.enemies) if e is unit), -1)

    def _priest_action(self, priest, msgs: list):
        """
        사제 행동 우선순위:
          1) 다른 아군 중 HP ≤ 70%면 → 사제힐 (가장 비율 낮은 아군)
          2) 30% 확률로 사제축복 (가장 STG 높은 아군 STG 버프)
          3) 그 외 → 홀리볼트 (마법 공격)
          4) MP 부족 → 기본 물리 공격
        """
        # ── 부활 (최우선 — 정상 우선순위보다 앞섬): 엘리트는 2단계 의식, 일반은 약식 소생 ──
        if self._priest_revival_check(priest, msgs):
            return

        # 자기 제외 살아있는 아군
        allies = [e for e in self.enemies if e is not priest and e.hp > 0]

        # ── 1) 사제힐 우선 ──
        if priest.mp >= 14 and allies:
            wounded = [a for a in allies if a.hp / max(a.maxhp, 1) <= 0.70]
            if wounded:
                target_ally = min(wounded, key=lambda a: a.hp / max(a.maxhp, 1))
                self._note_fx_target("enemy", self._enemy_slot_of(target_ally))
                meta = SKILL_META["사제힐"]
                priest.mp -= meta["mp"]
                heal = meta["base_heal"] + priest.sp * meta["sp_mult"]
                heal = min(heal, target_ally.maxhp * meta["cap"])
                before = int(target_ally.hp)
                hp_before = target_ally.hp
                target_ally.hp = min(target_ally.maxhp, target_ally.hp + int(heal))
                target_ally._record_hit("heal", target_ally.hp - hp_before)
                gained = int(target_ally.hp) - before
                msgs.append(f"{priest.name} → 사제힐! {target_ally.name} HP +{gained}")
                self.logs.append(TurnLog(
                    turn=self.turn, actor="enemy",
                    action="skill", action_detail="사제힐",
                    damage_dealt=-gained,
                    hp_after=target_ally.hp,
                    mp_after=priest.mp,
                ))
                return

        # ── 2) 사제축복 (30% 확률) ──
        if priest.mp >= 12 and allies and _random() < 0.30:
            target_ally = max(allies, key=lambda a: a.effective_stg())
            self._note_fx_target("enemy", self._enemy_slot_of(target_ally))
            meta = SKILL_META["사제축복"]
            priest.mp -= meta["mp"]
            target_ally.apply_buff(Buff(
                stat=meta["buff_stat"],
                amount=meta["buff_amount"],
                turns=meta["buff_turns"],
                name="사제축복",
            ))
            msgs.append(f"{priest.name} → 사제축복! {target_ally.name}의 공격력 강화!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="skill", action_detail="사제축복",
                damage_dealt=0,
                hp_after=target_ally.hp,
                mp_after=priest.mp,
            ))
            return

        # ── 3) 홀리볼트 (마법 공격) ──
        if priest.mp >= 8:
            meta = SKILL_META["홀리볼트"]
            priest.mp -= meta["mp"]
            dmg, dodge, crit = DamageCalc.magical(
                priest.sp, priest.luc,
                self.player.effective_sparm(), self.player.luc,
                skill_mult=meta["mult"],
                role="monster",
                attacker=priest,
                defender=self.player,
            )
            if dodge:
                msgs.append(f"{self.player.name}이(가) {priest.name}의 홀리볼트를 회피!")
                self._rogue_counter(priest, msgs)   # 도적: 회피 시 반격
                self.logs.append(TurnLog(
                    turn=self.turn, actor="enemy",
                    action="skill", action_detail="홀리볼트",
                    damage_dealt=0,
                    hp_after=self.player.hp,
                    mp_after=priest.mp,
                    is_dodge=True,
                ))
                return

            actual = self._apply_dmg_shielded(self.player, int(dmg), msgs)
            tag = " (치명타!)" if crit else ""
            msgs.append(f"{priest.name} → 홀리볼트{tag} | {actual} 데미지")
            msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

            # 탱커 패시브: 마법 피격 시 HP 회복
            tanker_msg = self.player.passive_on_hit_received("magical")
            if tanker_msg:
                msgs.append(tanker_msg)

            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="skill", action_detail="홀리볼트",
                damage_dealt=actual,
                hp_after=max(0, self.player.hp),
                mp_after=priest.mp,
                is_crit=crit,
            ))
            return

        # ── 4) MP 부족 → 기본 물리 공격 ──
        dmg, dodge, crit = DamageCalc.physical(
            priest.effective_stg(), priest.luc,
            self.player.effective_arm(), self.player.luc,
            skill_mult=1.0,
            role="monster",
            attacker=priest,
            defender=self.player,
        )
        if dodge:
            msgs.append(f"{self.player.name}이(가) {priest.name}의 공격을 회피!")
            self._rogue_counter(priest, msgs)   # 도적: 회피 시 반격
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy",
                action="attack", action_detail="basic_attack",
                damage_dealt=0,
                hp_after=self.player.hp,
                mp_after=priest.mp,
                is_dodge=True,
            ))
            return

        actual = self._apply_dmg_shielded(self.player, int(dmg), msgs)
        tag = " (치명타!)" if crit else ""
        msgs.append(f"{priest.name} → 공격{tag} | {actual} 데미지")
        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

        # 탱커 패시브: 물리 피격 시 MP 회복
        tanker_msg = self.player.passive_on_hit_received("physical")
        if tanker_msg:
            msgs.append(tanker_msg)

        self.logs.append(TurnLog(
            turn=self.turn, actor="enemy",
            action="attack", action_detail="basic_attack",
            damage_dealt=actual,
            hp_after=max(0, self.player.hp),
            mp_after=priest.mp,
            is_crit=crit,
        ))
    # ── 내부: 현재 상태 dict 반환 ────────────

    _DIFF_LABEL = {
        "hard":   "강함",
        "normal": "중간",
        "easy":   "약함",
        "":       "",
    }