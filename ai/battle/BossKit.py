"""
Battle/BossKit.py — 보스 패턴 수치/판단 (Combat Content Brief 4장 · 중간 보스)
─────────────────────────────────────────────
EliteKit.py와 같은 계층 — 수치 상수와 "이번 행동에 무엇을 할지" 판단만 담고,
피해 적용·메시지·TurnLog는 ai/battle_session/Boss_Actions.py가 담당한다.

실전(BattleSession)과 보스 평가 시뮬이 같은 판단 함수를 쓰도록 여기 한 곳에 둔다
(CLAUDE.md "실전/시뮬 경로를 포크하지 말 것"). 지금 호출부는 BattleSession뿐이고,
BattleEngine(자동 튜닝 1v1)은 보스를 다루지 않는다 — 나중에 연결하더라도 이 함수를
그대로 호출하면 된다. 보스 스탯(game/Enemy_Class.Make_MidBoss)은 건드리지 않는다.

중간 보스 「무너진 성문의 수문장」 — HP 구간으로 3페이즈:
  1 (100~60%) 시험     — 일반공격 70% / 몸통박치기2 20% / 관망 10%,
                         3회 행동마다 「대지 균열」 예고(관망) → 다음 행동에 발동
  2 ( 60~25%) 서리 갑주 — 진입 시 ARM +20%(영구) + 자기 자신에게 ice 부착.
                         ice가 반응으로 소모되면 2턴 뒤 재부착. 균열 주기 4, 계수 2.1
  3 ( 25~ 0%) 붕괴     — SPD +30%, 관망 없음(매 행동 공격), 예고 중단,
                         ARM·SPARM −25%. 전환 직전에 세워진 예고는 한 번 발동한 뒤 멈춘다

예고 보장(4장 카운터 계약): 예고를 세울 때 그 시점의 플레이어 행동 횟수를
boss_telegraph_at에 적고, 그 값보다 커진 뒤에만 발동한다. 보류 중 보스 차례가 오면
관망이 아니라 일반공격(계약 ②) — 무효 요청·마비로 예고를 무해하게 묶어둘 수 없게.
"""
from __future__ import annotations

from random import random as _random

from .Actions import Action

MIDBOSS_TYPE = "중간 보스"        # Make_MidBoss의 name — Unit.enemy_type 기본값이 name이라 그대로 식별자

# ── 페이즈 경계 (HP 비율이 이 값 이하가 되면 다음 페이즈) ──
MIDBOSS_PHASE2_HP = 0.60
MIDBOSS_PHASE3_HP = 0.25
MIDBOSS_PHASE_LABEL = {1: "시험", 2: "서리 갑주", 3: "붕괴"}

# ── 행동 확률 (일반공격, 몸통박치기2) — 나머지가 관망. 페이즈 3은 관망 없음 ──
MIDBOSS_ACTION_PROBS = {1: (0.70, 0.20), 2: (0.70, 0.20), 3: (0.80, 0.20)}
MIDBOSS_BODY_SKILL = "몸통박치기2"   # 골렘과 같은 몬스터 계수판 (Skills.MONSTER_SKILL_META)

# ── 「대지 균열」 ──
MIDBOSS_RIFT_INTERVAL = {1: 3, 2: 4}                 # n회 정규 행동마다 예고. 페이즈 3은 없음
MIDBOSS_RIFT_SKILL = {1: "대지 균열", 2: "대지 균열_강화", 3: "대지 균열_강화"}
MIDBOSS_RIFT_MULT = {1: 1.8, 2: 2.1}                 # STG 계수 (Skills가 이 값을 읽는다)
MIDBOSS_RIFT_ARM_PEN = 0.50                          # 플레이어 ARM 50% 관통
RIFT_STATUS = {"effect_type": "rift", "turns": 2, "name": "균열", "dot_rate": 0.04}
BOSS_TELEGRAPH_DETAIL = "boss_telegraph"             # 예고 행동의 TurnLog.action_detail

# ── 페이즈 2 「서리 갑주」 ──
MIDBOSS_FROST_ARM_AMOUNT = 0.20
MIDBOSS_FROST_ELEMENT = "ice"
MIDBOSS_FROST_REGROW_TURNS = 2

# ── 페이즈 3 「붕괴」 ──
MIDBOSS_COLLAPSE_SPD_AMOUNT = 0.30
MIDBOSS_COLLAPSE_DEF_AMOUNT = 0.25


def is_midboss(en) -> bool:
    return getattr(en, "enemy_type", "") == MIDBOSS_TYPE


BOSS_TYPES = (MIDBOSS_TYPE, "최종 보스")


def is_boss_or_elite(en) -> bool:
    """보스(중간·최종) 또는 엘리트 리더 — 10-4의 비율 피해 반감(피의 수확 3%/스택)과
    6-1의 방패치기 ATB 감소 반감(−12, 전투당 3회)이 적용되는 대상."""
    return getattr(en, "enemy_type", "") in BOSS_TYPES or bool(getattr(en, "elite_leader", False))


def midboss_phase_for(hp_ratio: float) -> int:
    if hp_ratio <= MIDBOSS_PHASE3_HP:
        return 3
    if hp_ratio <= MIDBOSS_PHASE2_HP:
        return 2
    return 1


def _enter_phase(boss, phase: int) -> None:
    """페이즈 진입 효과. 스탯 변화는 버프/디버프 목록이 아니라 기본 스탯에 직접 곱한다 —
    apply_debuff()는 같은 stat의 항목을 덮어쓰므로, 플레이어의 미약화(arm)·저주류가
    보스의 '영구' 변화를 덮었다가 만료되면 원래 값으로 되돌려 버린다."""
    boss.boss_cycle = 0     # 주기만 초기화 — 예약된 예고(boss_telegraph_at)는 유지
    if phase == 2:
        boss.arm = boss.arm * (1 + MIDBOSS_FROST_ARM_AMOUNT)
        boss.element_queue = [MIDBOSS_FROST_ELEMENT]
        boss.boss_frost_regrow = 0
    elif phase == 3:
        boss.spd = boss.spd * (1 + MIDBOSS_COLLAPSE_SPD_AMOUNT)
        boss.arm = boss.arm * (1 - MIDBOSS_COLLAPSE_DEF_AMOUNT)
        boss.sparm = boss.sparm * (1 - MIDBOSS_COLLAPSE_DEF_AMOUNT)


def midboss_sync_phase(boss) -> list:
    """HP에 맞춰 페이즈를 올리고 새로 진입한 페이즈의 효과를 적용한다.
    반환: 이번 호출에서 새로 진입한 페이즈 번호들 — 보통 [] 또는 [2]. 한 번에 두 구간을
    넘으면 [2, 3]이고 진입 효과는 순서대로 전부 적용된다. 페이즈는 내려가지 않는다."""
    if boss.maxhp <= 0:
        return []
    if boss.boss_phase == 0:
        boss.boss_phase = 1          # 페이즈 1은 진입 효과 없음
    target = midboss_phase_for(boss.hp / boss.maxhp)
    entered = []
    while boss.boss_phase < target:
        boss.boss_phase += 1
        _enter_phase(boss, boss.boss_phase)
        entered.append(boss.boss_phase)
    return entered


def midboss_frost_tick(boss) -> bool:
    """보스 행동 시작마다 호출. 서리 갑주(ice)가 반응으로 소모됐으면
    MIDBOSS_FROST_REGROW_TURNS번째 행동에 다시 부착한다. 반환 True = 이번에 재부착됨.
    Elements._restore_innate_element()는 반응 직후 같은 호출 안에서 즉시 되붙이므로
    쓰지 않는다 — 그러면 보스가 매 턴 융해·파쇄 대상이 된다(4장)."""
    if boss.boss_phase < 2:
        return False
    if MIDBOSS_FROST_ELEMENT in boss.element_queue:
        boss.boss_frost_regrow = 0
        return False
    if boss.boss_frost_regrow <= 0:
        boss.boss_frost_regrow = MIDBOSS_FROST_REGROW_TURNS
    boss.boss_frost_regrow -= 1
    if boss.boss_frost_regrow <= 0:
        boss.element_queue = [MIDBOSS_FROST_ELEMENT]
        return True
    return False


def midboss_decide(boss, player_action_count: int, rng=_random) -> Action:
    """이번 행동 결정. 호출 전에 midboss_sync_phase()로 페이즈가 맞춰져 있어야 한다.
    player_action_count: 세션이 세는 플레이어 행동 횟수 (Battlesession._player_action_count —
      _player_action()이 실제로 호출된 차례만 센다. 상태 조회·마비 실패는 세지 않고,
      MP 부족·무효 요청은 엔진이 차례를 소비하므로 센다)."""
    phase = boss.boss_phase or 1

    # 1) 예약된 예고 — 플레이어가 그 뒤 한 번이라도 행동했으면 발동, 아니면 일반공격으로 보류
    if boss.boss_telegraph_at >= 0:
        if player_action_count > boss.boss_telegraph_at:
            boss.boss_telegraph_at = -1
            return Action("skill", MIDBOSS_RIFT_SKILL[phase])
        return Action("attack", "attack")

    # 2) 주기 — 예고·발동 행동은 세지 않는다 (엘리트 박쥐·암살자와 같은 규약)
    interval = MIDBOSS_RIFT_INTERVAL.get(phase)
    if interval:
        boss.boss_cycle += 1
        if boss.boss_cycle >= interval:
            boss.boss_cycle = 0
            boss.boss_telegraph_at = player_action_count
            return Action("watch", BOSS_TELEGRAPH_DETAIL)

    # 3) 정규 행동
    atk_p, skill_p = MIDBOSS_ACTION_PROBS[phase]
    r = rng()
    if r < atk_p:
        return Action("attack", "attack")
    if r < atk_p + skill_p:
        from .Skills import MONSTER_SKILL_META   # 지연 import — Skills가 이 모듈의 상수를 읽는다
        cost = MONSTER_SKILL_META[MIDBOSS_BODY_SKILL]["mp"] * boss.mp_cost_multiplier()
        if boss.mp >= cost:
            return Action("skill", MIDBOSS_BODY_SKILL)
        return Action("attack", "attack")          # MP 부족 — 헛턴 대신 일반공격 (EnemyAI 킷과 동일)
    return Action("watch", "watching")
