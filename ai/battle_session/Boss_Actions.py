"""
battle_session/Boss_Actions.py — 보스 패턴 실행 (중간 보스)
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
)


class BossActionsMixin:
    """BattleSession에 중간 보스 패턴 실행 기능을 제공하는 mixin."""

    def _check_boss_phase(self, target, msgs: list) -> None:
        """HP 구간을 넘었으면 페이즈를 올리고 진입 효과를 적용한다 (BossKit이 적용, 여기는 메시지).
        피해 적용 지점과 보스 행동 시작 양쪽에서 부르므로 두 번 불려도 무해하다."""
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
