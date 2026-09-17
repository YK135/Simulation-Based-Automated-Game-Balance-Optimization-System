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


# ════════════════════════════════════════════════════════════
# 최종 보스 「심연에서 부르는 것」 (Combat Content Brief 4장 · 11-1 2차 8번) — HP 구간 4페이즈
#   1 (100~70%) 원소 순환 — 자기 원소 fire→ice→lightning을 3회 행동마다 순환, 같은 원소 공격 −40%,
#                          반응으로 원소가 벗겨지면 다음 원소를 즉시 부착(순환이 앞당겨짐)
#   2 ( 70~40%) 소환     — 진입 시 심연의 그림자 2마리(보스 maxHP 8% · 스탯 40%, 보상 없음),
#                          그림자가 살아 있는 동안 보스가 받는 피해 −25%, 전멸하면 경감 해제 + 보스 2회 무방비,
#                          5회 행동 뒤 재소환(페이즈 2인 동안만)
#   3 ( 40~15%) 잠식     — 매 행동 플레이어 MP 8% 흡수(흡수량 절반만큼 회복), MP가 0이면 HP 4% 흡수,
#                          3회 행동마다 「심연의 손아귀」 예고 → 다음 행동에 STG 2.5배 + 플레이어 ATB 0
#   4 ( 15~ 0%) 종언     — 진입 즉시 「종언」 카운트다운(플레이어 행동 3회), 보스 ARM·SPARM −40%,
#                          플레이어 회복 −50%. 카운트 종료: 1회차 maxHP 75% 고정 피해, 2회차부터 즉사,
#                          1회차 뒤 카운트는 2로 줄어 다시 시작. 보스는 매 행동 일반공격
#   예고 보장은 중간 보스와 같은 카운터 계약(boss_telegraph_at + 플레이어 행동 횟수)을 쓴다.
#   보스 스탯(Make_FinalBoss)은 건드리지 않는다.
# ════════════════════════════════════════════════════════════

FINALBOSS_TYPE = "최종 보스"
FINALBOSS_PHASE2_HP = 0.70
FINALBOSS_PHASE3_HP = 0.40
FINALBOSS_PHASE4_HP = 0.15
FINALBOSS_PHASE_LABEL = {1: "원소 순환", 2: "소환", 3: "잠식", 4: "종언"}

# 1 — 원소 순환
FINALBOSS_ELEMENTS = ("fire", "ice", "lightning")
FINALBOSS_ELEMENT_KOR = {"fire": "화염", "ice": "빙결", "lightning": "번개"}
FINALBOSS_CYCLE_TURNS = 3
FINALBOSS_SAME_ELEMENT_MULT = 0.60          # 붙은 원소와 같은 원소로 때리면 −40%
FINALBOSS_BOLT = {"fire": "파이어볼1", "ice": "아이스볼릿1", "lightning": "라이트닝1"}
# 행동 확률 (일반공격, 원소탄) — 나머지는 없음(관망 없음). 옛 폴백(공격 55% / 마법 45%)과 같은 비율
FINALBOSS_ACTION_PROBS = {1: (0.55, 0.45), 2: (0.55, 0.45), 3: (0.70, 0.30), 4: (1.00, 0.00)}

# 2 — 소환
SHADOW_TYPE = "심연의 그림자"
SHADOW_COUNT = 2
SHADOW_HP_RATIO = 0.08
SHADOW_STAT_RATIO = 0.40
SHADOW_GUARD = 0.25                          # 그림자 생존 중 보스가 받는 피해 −25%
SHADOW_STUN_TURNS = 2                        # 그림자 전멸 시 보스 무방비 행동 수
SHADOW_RESUMMON_TURNS = 5

# 3 — 잠식
DRAIN_MP_RATIO = 0.08
DRAIN_HP_RATIO = 0.04
DRAIN_HEAL_RATIO = 0.50
GRASP_INTERVAL = 3
GRASP_SKILL = "심연의 손아귀"
GRASP_MULT = 2.5
GRASP_DETAIL = "grasp_telegraph"

# 4 — 종언
DOOM_FIRST_COUNT = 3
DOOM_REPEAT_COUNT = 2
DOOM_FIXED_RATIO = 0.75
DOOM_DEF_DOWN = 0.40
DOOM_HEAL_MULT = 0.50


def is_finalboss(en) -> bool:
    return getattr(en, "enemy_type", "") == FINALBOSS_TYPE


def is_shadow(en) -> bool:
    return getattr(en, "enemy_type", "") == SHADOW_TYPE


def finalboss_phase_for(hp_ratio: float) -> int:
    if hp_ratio <= FINALBOSS_PHASE4_HP:
        return 4
    if hp_ratio <= FINALBOSS_PHASE3_HP:
        return 3
    if hp_ratio <= FINALBOSS_PHASE2_HP:
        return 2
    return 1


def finalboss_current_element(boss) -> str:
    return FINALBOSS_ELEMENTS[boss.boss_element_idx % len(FINALBOSS_ELEMENTS)]


def finalboss_next_element(boss) -> str:
    return FINALBOSS_ELEMENTS[(boss.boss_element_idx + 1) % len(FINALBOSS_ELEMENTS)]


def _finalboss_attach(boss) -> None:
    boss.element_queue = [finalboss_current_element(boss)]


def finalboss_advance_element(boss) -> str:
    """순환을 한 칸 넘기고 새 원소를 부착한다. 반환: 새 원소."""
    boss.boss_element_idx = (boss.boss_element_idx + 1) % len(FINALBOSS_ELEMENTS)
    boss.boss_cycle = 0
    _finalboss_attach(boss)
    return finalboss_current_element(boss)


def finalboss_element_resist(defender, element: str) -> float:
    """페이즈 1: 붙어 있는 원소와 같은 원소 공격은 −40% (Elements.apply_element_and_react가 부른다)."""
    if not is_finalboss(defender) or getattr(defender, "boss_phase", 0) != 1 or not element:
        return 1.0
    q = getattr(defender, "element_queue", None) or []
    return FINALBOSS_SAME_ELEMENT_MULT if q and q[-1] == element else 1.0


def finalboss_after_hit(boss) -> str:
    """피해 적용 직후(페이즈 1): 반응·파쇄로 순환 원소가 벗겨졌으면 다음 원소를 즉시 부착. 반환: 새 원소 또는 ""."""
    if not is_finalboss(boss) or boss.boss_phase != 1 or boss.hp <= 0:
        return ""
    if finalboss_current_element(boss) in (boss.element_queue or []):
        return ""
    return finalboss_advance_element(boss)


def make_shadow(boss):
    """심연의 그림자 — 보스 maxHP 8% · 스탯 40%, MP 0(일반공격만), 보상 없음."""
    from .Entity import EntitySnapshot
    r = SHADOW_STAT_RATIO
    return EntitySnapshot(
        name=SHADOW_TYPE, hp=boss.maxhp * SHADOW_HP_RATIO, maxhp=boss.maxhp * SHADOW_HP_RATIO,
        mp=0, maxmp=0, stg=boss.stg * r, arm=boss.arm * r, sparm=boss.sparm * r, sp=boss.sp * r,
        luc=boss.luc * r, lv=boss.lv, spd=boss.spd * r,
        enemy_type=SHADOW_TYPE, is_summoned=True, reward_eligible=False,
    )


def finalboss_summon(boss, enemies: list) -> list:
    """그림자 2마리를 세운다 — 죽은 그림자 칸이 있으면 되살려 재사용(UI 3칸 한도), 모자라면 새로.
    반환: 새로 enemies에 붙인 개체 목록(호출부가 ATB·원본 칸을 맞춘다)."""
    dead = [e for e in enemies if is_shadow(e) and e.hp <= 0]
    added = []
    for i in range(SHADOW_COUNT):
        fresh = make_shadow(boss)
        if i < len(dead):
            slot = dead[i]
            slot.hp, slot.maxhp = fresh.hp, fresh.maxhp
            slot.status_effects, slot.debuffs, slot.buffs, slot.element_queue = [], [], [], []
            slot.shield = 0.0
        else:
            enemies.append(fresh)
            added.append(fresh)
    boss.boss_guard = SHADOW_GUARD
    boss.boss_summon_cd = -1
    return added


def finalboss_sync_guard(boss, enemies: list) -> bool:
    """그림자 생존 여부로 경감을 맞춘다. 반환 True = 방금 전멸했다(무방비·재소환 대기 시작)."""
    if not is_finalboss(boss):
        return False
    alive = any(is_shadow(e) and e.hp > 0 for e in enemies)
    if alive:
        boss.boss_guard = SHADOW_GUARD
        return False
    if boss.boss_guard > 0:
        boss.boss_guard = 0.0
        boss.boss_stunned = SHADOW_STUN_TURNS
        boss.boss_summon_cd = SHADOW_RESUMMON_TURNS
        return True
    return False


def _finalboss_enter(boss, phase: int, player=None) -> None:
    boss.boss_cycle = 0            # 주기만 초기화 — 예약된 손아귀 예고는 유지(중간 보스와 같은 규칙)
    if phase == 1:
        boss.boss_element_idx = 0
        _finalboss_attach(boss)
    elif phase == 2:
        boss.element_queue = []    # 순환 종료
    elif phase == 4:
        boss.arm = boss.arm * (1 - DOOM_DEF_DOWN)
        boss.sparm = boss.sparm * (1 - DOOM_DEF_DOWN)
        boss.boss_doom_count = 0
        if player is not None:
            player.heal_taken_mult = DOOM_HEAL_MULT


def finalboss_sync_phase(boss, player=None, player_action_count: int = 0) -> list:
    """HP에 맞춰 페이즈를 올린다(내려가지 않음). 반환: 새로 진입한 페이즈 번호들.
    소환(2)과 종언 카운트(4)의 시작 시점은 호출부가 반환값을 보고 처리한다 — 여기서는 상태만."""
    if boss.maxhp <= 0:
        return []
    entered = []
    if boss.boss_phase == 0:
        boss.boss_phase = 1
        _finalboss_enter(boss, 1, player)
    target = finalboss_phase_for(boss.hp / boss.maxhp)
    while boss.boss_phase < target:
        boss.boss_phase += 1
        _finalboss_enter(boss, boss.boss_phase, player)
        if boss.boss_phase == 4:
            boss.boss_doom_at = player_action_count + DOOM_FIRST_COUNT
        entered.append(boss.boss_phase)
    return entered


def finalboss_drain(boss, player) -> tuple:
    """페이즈 3 흡수 — 반환 (종류 "mp"/"hp"/"", 흡수량, 보스 회복량). 상태는 여기서 바꾼다."""
    if boss.boss_phase != 3 or player.hp <= 0:
        return "", 0.0, 0.0
    if player.mp > 0:
        amt = min(float(player.mp), player.maxmp * DRAIN_MP_RATIO)
        player.mp -= amt
        kind = "mp"
    else:
        amt = min(float(player.hp) - 1.0, player.maxhp * DRAIN_HP_RATIO)   # 흡수로는 죽지 않는다
        amt = max(0.0, amt)
        before = player.hp
        player.hp -= amt
        player._record_hit("damage", before - player.hp, via="drain", element="", reaction="")
        kind = "hp"
    heal = min(amt * DRAIN_HEAL_RATIO, boss.maxhp - boss.hp)
    if heal > 0:
        boss.hp += heal
        boss._record_hit("heal", heal, via="drain", element="", reaction="")
    return kind, amt, max(0.0, heal)


def finalboss_cycle_tick(boss) -> str:
    """페이즈 1 보스 행동 시작마다 — 3회째에 원소를 넘긴다. 반환: 새 원소 또는 "" (행동은 그대로 한다)."""
    if boss.boss_phase != 1:
        return ""
    if finalboss_current_element(boss) not in (boss.element_queue or []):
        return finalboss_advance_element(boss)          # 행동 사이에 벗겨졌으면(안전망) 바로 부착
    boss.boss_cycle += 1
    if boss.boss_cycle >= FINALBOSS_CYCLE_TURNS:
        return finalboss_advance_element(boss)
    return ""


def finalboss_decide(boss, player_action_count: int, rng=_random) -> Action:
    """최종 보스의 이번 행동. 무방비·종언은 호출부(Boss_Actions)가 먼저 처리한다."""
    phase = boss.boss_phase or 1

    # 예약된 손아귀 — 플레이어가 그 뒤 한 번이라도 행동했으면 발동, 아니면 일반공격으로 보류
    if boss.boss_telegraph_at >= 0:
        if player_action_count > boss.boss_telegraph_at:
            boss.boss_telegraph_at = -1
            return Action("skill", GRASP_SKILL)
        return Action("attack", "attack")

    if phase == 3:
        boss.boss_cycle += 1
        if boss.boss_cycle >= GRASP_INTERVAL:
            boss.boss_cycle = 0
            boss.boss_telegraph_at = player_action_count
            return Action("watch", GRASP_DETAIL)

    atk_p, bolt_p = FINALBOSS_ACTION_PROBS[phase]
    if rng() < atk_p:
        return Action("attack", "attack")
    elem = finalboss_current_element(boss) if phase == 1 else "fire"
    return Action("skill", FINALBOSS_BOLT[elem])
