"""
battle_session/Boss_Actions.py — 보스 패턴 실행 (중간 보스 · 최종 보스)
─────────────────────────────────────────────
판단/수치는 ai/battle/BossKit.py, 실제 상태 변경·메시지·TurnLog는 여기서 담당
(Elite_Actions.py와 같은 분업).
호출부:
  · Enemy_Actions._single_enemy_action() — 행동 결정 (_midboss_pre_action)
  · Player_Actions._apply_dmg_shielded() — 피해 적용 직후 페이즈 동기화 (_check_boss_phase):
    플레이어가 HP 구간을 넘긴 그 step 안에서 전환 메시지와 배지가 바로 나오게 한다
"""
from __future__ import annotations

from ai.battle import execute_skill, TurnLog
from ai.battle.BossKit import (
    is_midboss, midboss_sync_phase, midboss_frost_tick, midboss_decide,
    BOSS_TELEGRAPH_DETAIL, RIFT_STATUS,
    MIDBOSS_FROST_ARM_AMOUNT, MIDBOSS_COLLAPSE_SPD_AMOUNT, MIDBOSS_COLLAPSE_DEF_AMOUNT,
    is_finalboss, is_shadow, finalboss_sync_phase, finalboss_after_hit, finalboss_cycle_tick,
    finalboss_decide, finalboss_summon, finalboss_sync_guard, finalboss_drain,
    finalboss_current_element, finalboss_next_element,
    FINALBOSS_ELEMENT_KOR, FINALBOSS_PHASE_LABEL, SHADOW_GUARD, SHADOW_STUN_TURNS, SHADOW_RESUMMON_TURNS,
    GRASP_SKILL, GRASP_DETAIL, DOOM_FIRST_COUNT, DOOM_REPEAT_COUNT, DOOM_FIXED_RATIO,
    DOOM_DEF_DOWN, DOOM_HEAL_MULT,
)


class BossActionsMixin:
    """BattleSession에 중간 보스 패턴 실행 기능을 제공하는 mixin."""

    def _check_boss_phase(self, target, msgs: list) -> None:
        """HP 구간을 넘었으면 페이즈를 올리고 진입 효과를 적용한다 (BossKit이 적용, 여기는 메시지).
        피해 적용 지점과 보스 행동 시작 양쪽에서 부르므로 두 번 불려도 무해하다."""
        if is_finalboss(target) or is_shadow(target):
            self._check_finalboss(target, msgs)
            return
        if not is_midboss(target) or target.hp <= 0:
            return
        for ph in midboss_sync_phase(target):
            if ph == 2:
                msgs.append(f"🧊 {target.name}의 몸에 서리 갑주가 돋아난다! "
                            f"(방어 +{int(MIDBOSS_FROST_ARM_AMOUNT * 100)}%, ice 부착)")
                msgs.append("붙은 ice는 융해(화염)와 파쇄(물리)의 표적이다.")
            elif ph == 3:
                msgs.append(f"💥 {target.name}이(가) 무너지기 시작한다 — 붕괴! "
                            f"(속도 +{int(MIDBOSS_COLLAPSE_SPD_AMOUNT * 100)}%, "
                            f"방어·마법방어 -{int(MIDBOSS_COLLAPSE_DEF_AMOUNT * 100)}%)")

    def _midboss_pre_action(self, boss, msgs: list):
        """중간 보스의 이번 행동을 결정한다.
        반환 None  = 예고 또는 「대지 균열」을 여기서 이미 실행·로그했다.
        반환 Action = 일반공격 / 몸통박치기2 / 관망 — 호출부의 공통 경로가 실행한다."""
        self._check_boss_phase(boss, msgs)
        if midboss_frost_tick(boss):
            msgs.append(f"🧊 {boss.name}의 서리 갑주가 다시 얼어붙는다. (ice 부착)")

        action = midboss_decide(boss, self._player_action_count)

        if action.action_type == "watch" and action.detail == BOSS_TELEGRAPH_DETAIL:
            msgs.append(f"⚠ {boss.name}이(가) 대지를 내리칠 준비를 한다 — 「대지 균열」 예고!")
            msgs.append("다음 공격은 방어력을 절반 무시한다. 실드·회복으로 대비하라!")
            self.logs.append(TurnLog(
                turn=self.turn, actor="enemy", action="watch", action_detail=BOSS_TELEGRAPH_DETAIL,
                hp_after=self.player.hp, mp_after=boss.mp,
            ))
            return None

        if action.action_type == "skill" and action.detail.startswith("대지 균열"):
            self._midboss_rift(boss, action.detail, msgs)
            return None

        return action

    def _midboss_rift(self, boss, skill: str, msgs: list) -> None:
        """「대지 균열」 발동. ARM 관통과 균열 부여는 Skills의 스킬 메타(arm_pen / on_hit_status)가
        execute_skill 안에서 처리하므로 시뮬 경로와 같은 계산이다. 여기는 실드 적용·메시지·로그."""
        dmg, _mp_lack, _info = execute_skill(skill, boss, self.player)
        if dmg > 0:
            dealt = self._apply_dmg_shielded(self.player, dmg, msgs)
            msgs.append(f"{boss.name} → 대지 균열! | {dealt} 데미지")
            msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")
            if any(getattr(e, "effect_type", "") == RIFT_STATUS["effect_type"]
                   for e in self.player.status_effects):
                msgs.append(f"🌑 {self.player.name}에게 「균열」이 새겨졌다! "
                            f"({RIFT_STATUS['turns']}T, 매 행동 maxHP {int(RIFT_STATUS['dot_rate'] * 100)}%)")
            tanker_msg = self.player.passive_on_hit_received("physical")
            if tanker_msg:
                msgs.append(tanker_msg)
        else:
            msgs.append(f"{self.player.name}이(가) {boss.name}의 대지 균열을 회피했다!")
        self.logs.append(TurnLog(
            turn=self.turn, actor="enemy", action="skill", action_detail=skill,
            damage_dealt=int(dmg) if dmg > 0 else 0,
            hp_after=max(0, self.player.hp), mp_after=boss.mp,
            is_dodge=(dmg <= 0),
        ))


    # ═══════════════════════════════════════════════════════
    # 최종 보스 「심연에서 부르는 것」 (BossKit finalboss_*)
    # ═══════════════════════════════════════════════════════

    def _final_boss(self):
        return next((e for e in self.enemies if is_finalboss(e)), None)

    def _check_finalboss(self, target, msgs: list) -> None:
        """최종 보스·그림자가 피해를 받은 직후 — 페이즈 전환, 순환 원소 재부착, 그림자 경감, 보스 사망 정리."""
        boss = target if is_finalboss(target) else self._final_boss()
        if boss is None:
            return
        if boss.hp <= 0:
            # 보스가 쓰러지면 그림자도 흩어진다 — 남은 그림자 때문에 전투가 이어지지 않게
            left = [e for e in self.enemies if is_shadow(e) and e.hp > 0]
            for e in left:
                e.hp = 0.0
            if left:
                msgs.append("심연이 닫히며 그림자들이 흩어졌다.")
            return
        for ph in finalboss_sync_phase(boss, self.player, self._player_action_count):
            msgs.append(f"🌑 {boss.name} — {FINALBOSS_PHASE_LABEL[ph]}!")
            if ph == 2:
                self._finalboss_summon(boss, msgs)
            elif ph == 3:
                msgs.append("매 행동마다 MP를 빨아들이고, 3회 행동마다 「심연의 손아귀」를 예고한다.")
            elif ph == 4:
                msgs.append(f"⏳ 「종언」 — 플레이어 행동 {DOOM_FIRST_COUNT}회 뒤 최대 HP {int(DOOM_FIXED_RATIO * 100)}% 피해, "
                            f"두 번째는 즉사! (보스 방어 −{int(DOOM_DEF_DOWN * 100)}%, 회복 −{int((1 - DOOM_HEAL_MULT) * 100)}%)")
        shifted = finalboss_after_hit(boss)
        if shifted:
            msgs.append(f"🌀 원소가 벗겨지자 {boss.name}이(가) 곧바로 {FINALBOSS_ELEMENT_KOR[shifted]}을(를) 두른다! "
                        f"(다음: {FINALBOSS_ELEMENT_KOR[finalboss_next_element(boss)]})")
        if finalboss_sync_guard(boss, self.enemies):
            msgs.append(f"그림자가 모두 쓰러졌다 — {boss.name}의 경감 해제, {SHADOW_STUN_TURNS}회 무방비! "
                        f"({SHADOW_RESUMMON_TURNS}회 행동 뒤 재소환)")

    def _finalboss_summon(self, boss, msgs: list) -> None:
        added = finalboss_summon(boss, self.enemies)
        for _ in added:
            self.enemy_atbs.append(0.0)
            self._origins.append(None)
        msgs.append(f"👥 {boss.name}이(가) 심연의 그림자 2마리를 불러냈다! "
                    f"(그림자가 있는 동안 보스가 받는 피해 −{int(SHADOW_GUARD * 100)}%)")

    def _finalboss_pre_action(self, boss, msgs: list):
        """최종 보스의 이번 행동. 반환 None = 여기서 처리·로그 완료, Action = 공통 경로(일반공격/원소탄)."""
        self._check_finalboss(boss, msgs)

        # 무방비 (그림자 전멸 직후)
        if boss.boss_stunned > 0:
            boss.boss_stunned -= 1
            msgs.append(f"{boss.name}이(가) 그림자를 잃고 휘청인다 — 무방비! (남은 {boss.boss_stunned}회)")
            self.logs.append(TurnLog(turn=self.turn, actor="enemy", action="watch",
                                     action_detail="boss_stunned", hp_after=self.player.hp, mp_after=boss.mp))
            return None

        # 페이즈 2 재소환 대기
        if boss.boss_phase == 2 and boss.boss_summon_cd > 0:
            boss.boss_summon_cd -= 1
            if boss.boss_summon_cd == 0:
                self._finalboss_summon(boss, msgs)

        # 페이즈 1 원소 순환
        shifted = finalboss_cycle_tick(boss)
        if shifted:
            msgs.append(f"🌀 {boss.name}의 원소가 {FINALBOSS_ELEMENT_KOR[shifted]}(으)로 바뀐다! "
                        f"(다음: {FINALBOSS_ELEMENT_KOR[finalboss_next_element(boss)]})")

        # 페이즈 3 잠식
        kind, amt, heal = finalboss_drain(boss, self.player)
        if kind == "mp" and amt > 0:
            msgs.append(f"🌑 {boss.name}이(가) MP {int(amt)}을(를) 빨아들인다 (보스 HP +{int(heal)})")
        elif kind == "hp" and amt > 0:
            msgs.append(f"🌑 MP가 바닥나 {boss.name}이(가) HP {int(amt)}을(를) 빨아들인다 (보스 HP +{int(heal)})")

        # 페이즈 4 종언
        if boss.boss_phase == 4 and boss.boss_doom_at >= 0 and self._player_action_count >= boss.boss_doom_at:
            self._finalboss_doom(boss, msgs)
            return None

        action = finalboss_decide(boss, self._player_action_count)
        if action.action_type == "watch" and action.detail == GRASP_DETAIL:
            msgs.append(f"⚠ {boss.name}이(가) 심연의 손을 뻗는다 — 「심연의 손아귀」 예고!")
            msgs.append("다음 공격은 매우 강하고, 맞으면 ATB가 0이 된다. 실드·회복으로 대비하라!")
            self.logs.append(TurnLog(turn=self.turn, actor="enemy", action="watch",
                                     action_detail=GRASP_DETAIL, hp_after=self.player.hp, mp_after=boss.mp))
            return None
        if action.action_type == "skill" and action.detail == GRASP_SKILL:
            self._finalboss_grasp(boss, msgs)
            return None
        if action.action_type == "skill":
            from ai.battle.Skills import skill_requirement_error
            if skill_requirement_error(action.detail, boss, self.player):
                from ai.battle import Action
                return Action("attack", "attack")            # MP 부족 — 헛턴 대신 일반공격
        return action

    def _finalboss_grasp(self, boss, msgs: list) -> None:
        dmg, _lack, _info = execute_skill(GRASP_SKILL, boss, self.player)
        if dmg > 0:
            dealt = self._apply_dmg_shielded(self.player, dmg, msgs)
            msgs.append(f"{boss.name} → 심연의 손아귀! | {dealt} 데미지")
            msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")
            if self.player_atb > 0:
                msgs.append(f"⏱ {self.player.name}의 ATB가 0이 되었다! (−{int(self.player_atb)})")
            self.player_atb = 0.0
            tanker_msg = self.player.passive_on_hit_received("physical")
            if tanker_msg:
                msgs.append(tanker_msg)
        else:
            msgs.append(f"{self.player.name}이(가) {boss.name}의 심연의 손아귀를 피했다!")
        self.logs.append(TurnLog(turn=self.turn, actor="enemy", action="skill", action_detail=GRASP_SKILL,
                                 damage_dealt=int(dmg) if dmg > 0 else 0,
                                 hp_after=max(0, self.player.hp), mp_after=boss.mp, is_dodge=(dmg <= 0)))

    def _finalboss_doom(self, boss, msgs: list) -> None:
        first = boss.boss_doom_count == 0
        if first:
            dmg = int(self.player.maxhp * DOOM_FIXED_RATIO)
            self.player._stamp_last_hit("", "")
            dealt = self._apply_dmg_shielded(self.player, dmg, msgs)     # 실드·피해 경감으로 버틸 수 있다
            msgs.append(f"{boss.name} → 「종언」! | {dealt} 데미지 (최대 HP {int(DOOM_FIXED_RATIO * 100)}%)")
        else:
            dealt = int(self.player.hp)
            before = self.player.hp
            self.player.hp = 0.0
            self.player._record_hit("damage", before, via="doom", element="", reaction="")
            msgs.append(f"{boss.name} → 「종언」! 두 번째 종언은 모든 것을 끝낸다 — 즉사!")
        msgs.append(f"{self.player.name} HP: {max(0, int(self.player.hp))}")
        boss.boss_doom_count += 1
        boss.boss_doom_at = self._player_action_count + DOOM_REPEAT_COUNT
        if self.player.hp > 0:
            msgs.append(f"⏳ 「종언」 카운트 재시작 — 플레이어 행동 {DOOM_REPEAT_COUNT}회 뒤 즉사!")
        self.logs.append(TurnLog(turn=self.turn, actor="enemy", action="skill", action_detail="종언",
                                 damage_dealt=int(dealt), hp_after=max(0, self.player.hp), mp_after=boss.mp))
