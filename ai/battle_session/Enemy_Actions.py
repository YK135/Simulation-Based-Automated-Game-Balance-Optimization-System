"""
battle_session/enemy_actions.py — 적 행동
"""
from __future__ import annotations
from random import random as _random

from ai.battle import (
    apply_element_and_react, Buff, DamageCalc,
    execute_skill, SKILL_META, TurnLog,
)


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
            actual = self._apply_dmg_shielded(enemy, actual, msgs)
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

    def _enemy_action(self, msgs: list):
        """
        다대일: 살아있는 모든 적이 SPD 내림차순으로 한 번씩 행동.
        각 적이 행동할 때마다 플레이어 사망 체크 — 죽으면 즉시 종료.
        """
        # SPD 내림차순 정렬 (빠른 적 먼저)
        alive = sorted(
            self._alive_enemies(),
            key=lambda e: e.effective_spd(),
            reverse=True
        )
        for e in alive:
            if self.player.hp <= 0:
                break  # 플레이어 사망 시 남은 적 행동 스킵
            self._single_enemy_action(e, msgs)

    def _single_enemy_action(self, enemy, msgs: list):
        """단일 적의 1회 행동 처리. 기존 _enemy_action 로직을 적 1마리 단위로 분리."""
        # ── 사제 전용 행동 (다른 아군 회복/버프) ──
        # enemy_type이 "사제"면 별도 로직 사용. 일반 EnemyAI 안 거침.
        # ⚠ return 제거 — 메서드 끝의 tick 처리(buff/debuff 1턴 감소)를
        #    사제도 동일하게 거쳐야 함 (Codex 지적 반영).
        if getattr(enemy, "enemy_type", "") == "사제":
            self._priest_action(enemy, msgs)
        else:
            # ── 일반 몬스터 행동 (기존 로직) ──
            chapter = (getattr(self, "battle_meta", {}) or {}).get("chapter", 1)
            action = self._enemy_ai(enemy, self.player, chapter=chapter)

            if action.action_type == "attack":
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
                        dmg = self._apply_dmg_shielded(self.player, dmg, msgs)
                        msgs.append(f"{enemy.name} → {action.detail} | {dmg} 데미지")
                        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")

                        # ── 탱커 패시브: 스킬 피격 시 회복 (스킬 타입 따라) ──
                        skill_meta = SKILL_META.get(action.detail, {})
                        skill_type = skill_meta.get("type", "physical")
                        tanker_msg = self.player.passive_on_hit_received(skill_type)
                        if tanker_msg:
                            msgs.append(tanker_msg)
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


    # ─────────────────────────────────────────────
    # 사제 전용 행동 (서포터형)

    def _priest_action(self, priest, msgs: list):
        """
        사제 행동 우선순위:
          1) 다른 아군 중 HP ≤ 70%면 → 사제힐 (가장 비율 낮은 아군)
          2) 30% 확률로 사제축복 (가장 STG 높은 아군 STG 버프)
          3) 그 외 → 홀리볼트 (마법 공격)
          4) MP 부족 → 기본 물리 공격
        """
        # 자기 제외 살아있는 아군
        allies = [e for e in self.enemies if e is not priest and e.hp > 0]

        # ── 1) 사제힐 우선 ──
        if priest.mp >= 14 and allies:
            wounded = [a for a in allies if a.hp / max(a.maxhp, 1) <= 0.70]
            if wounded:
                target_ally = min(wounded, key=lambda a: a.hp / max(a.maxhp, 1))
                meta = SKILL_META["사제힐"]
                priest.mp -= meta["mp"]
                heal = meta["base_heal"] + priest.sp * meta["sp_mult"]
                heal = min(heal, target_ally.maxhp * meta["cap"])
                before = int(target_ally.hp)
                target_ally.hp = min(target_ally.maxhp, target_ally.hp + int(heal))
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