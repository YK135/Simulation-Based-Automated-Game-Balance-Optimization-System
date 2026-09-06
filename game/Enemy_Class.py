"""
Enemy_Class.py
─────────────────────────────────────────────
몬스터 클래스 및 생성 모듈.

[밸런스 v5 - 역할 기반 설계]
  하급: HP 낮음 + 공격 낮음 → 1~2방 처치 가능
  중급: 균형형 → 3~5방
  상급: 탱커(HP높고ARM높음) or 유리대포(HP낮고STG높음)

  고블린: 근접 탱커 성향 (HP 높고 ARM 높음)
  박쥐:   유리대포 성향 (HP 낮고 SPD 빠르고 SP 있음)

  경험치: 상45% / 중34% / 하28%
  중간 보스: STG 낮추고 HP/ARM/SPARM으로 난이도
  최종 보스: 동일 원칙 + 저항 50%
"""
from __future__ import annotations
from random import random, choice


class Unit:
    def __init__(self, name, lv, hp, mp, stg, arm, sparm, sp, spd, luc,
                 grade="중", is_boss=False, debuff_resist=0.0,
                 # ── Phase 1: 역할 기반 메커니즘 ──
                 physical_resist=1.0, magical_resist=1.0,
                 dodge_bonus=0.0, dodge_penalty_per_extra_hit=0.10,
                 first_strike=False, first_attack_bonus=1.0,
                 enemy_type="",
                 attack_element="", init_element_queue=None):
        self.name          = name
        self.lv            = lv
        self.hp            = hp
        self.maxhp         = hp
        self.mp            = mp
        self.maxmp         = mp
        self.stg           = stg
        self.arm           = arm
        self.sparm         = sparm
        self.sp            = sp
        self.spd           = spd
        self.luc           = luc
        self.grade         = grade
        self.is_boss       = is_boss
        self.debuff_resist = debuff_resist
        # 역할 기반
        self.physical_resist = physical_resist
        self.magical_resist  = magical_resist
        self.dodge_bonus     = dodge_bonus
        self.dodge_penalty_per_extra_hit = dodge_penalty_per_extra_hit
        self.first_strike    = first_strike
        self.first_attack_bonus = first_attack_bonus
        self.has_attacked    = False
        self.enemy_type      = enemy_type or name
        # 원소 시스템
        self.attack_element      = attack_element        # 기본 공격 원소
        self.init_element_queue  = init_element_queue or []  # 전투 시작 초기 큐

    def exp_reward(self, player_maxexp: int) -> int:
        ratio = {"상": 0.8, "중": 0.55, "하": 0.45}.get(self.grade, 0.34)
        return int(player_maxexp * ratio)

    def decide_action(self, player) -> str:
        roll = random()
        if self.is_boss:
            if roll < 0.45:   return "attack"
            elif roll < 0.85: return "magic"
            else:             return "watch"
        elif self.grade == "상":
            if roll < 0.50:   return "attack"
            elif roll < 0.85: return "magic"
            else:             return "watch"
        else:
            if roll < 0.60:   return "attack"
            elif roll < 0.85: return "magic"
            else:             return "watch"


# ── 등급 배율 ──────────────────────────────
# 하급: 전반적으로 약하게
# 상급: 탱커(HP/ARM) or 유리대포(STG) 성향 공존
GRADE_MULT = {
    "하": {"hp": 0.6, "stg": 0.70, "arm": 0.85, "sparm": 0.7, "sp": 0.2},
    "중": {"hp": 0.90, "stg": 0.90, "arm": 1.00, "sparm": 0.8, "sp": 0.4},
    "상": {"hp": 1.20, "stg": 1.12, "arm": 1.10, "sparm": 0.9, "sp": 0.7},
}


def _level_curve_mult(lv: int) -> float:
    """몬스터 스탯 보정 배율 (밸런스 v6).

    MC 실측 결과 1v1은 Lv1부터 이미 99~100% — 레벨이 오르면서 벌어지는
    문제가 아니라 애초에 단일 몬스터가 전반적으로 약했음. 여기에 더해
    game/Lv.py의 플레이어 성장식(`기본값 + lv // N`, 레벨업당 증가폭 자체가
    커지는 가속 성장)과 몬스터 쪽 선형 성장(`기본값 + 계수*(lv-1)`)의 격차가
    후반으로 갈수록 벌어짐. 그래서 전 구간에 기본 상향을 걸고, 레벨이
    오를수록 추가로 더 올린다. 다대일(1v2/1v3/엘리트)은 이 위에 별도
    STAT_SCALE로 낮추므로 과하게 어려워지지 않음 — 실측하며 조정.
    보스(중간/최종)는 이미 별도로 잘 맞춰져 있어 이 배율을 안 탐
    (Make_MidBoss/Make_FinalBoss는 _apply_grade를 안 씀).

    ★ 다대일 초반 완화(app/Map.py의 _early_game_multi_scale)와 이 함수는
      서로 다른 문제를 겨냥한 별도 배율이라 함께 곱해진다 — 다음에 밸런스를
      다시 만질 땐 이 함수만 보지 말고 그쪽도 같이 봐야 최종 스탯을 제대로
      가늠할 수 있음(GRADE_MULT * 이 배율 * STAT_SCALE * _early_game_multi_scale).
    """
    if lv <= 5:
        return 1.10
    return 1.10 + 0.06 * (lv - 5)


def _apply_grade(unit: Unit, grade: str) -> Unit:
    m = GRADE_MULT[grade]
    lvm = _level_curve_mult(unit.lv)
    unit.hp    = int(unit.hp    * m["hp"]    * lvm)
    unit.stg   = round(unit.stg   * m["stg"]   * lvm, 1)
    unit.arm   = round(unit.arm   * m["arm"]   * lvm, 1)
    unit.sparm = round(unit.sparm * m["sparm"] * lvm, 1)
    unit.sp    = round(unit.sp    * m["sp"]    * lvm, 1)
    unit.grade = grade
    return unit


def Make_Goblin(player_lv: int, grade: str) -> Unit:
    """
    고블린: 표준형 물리 몬스터 (Lv1+ 등장)
    HP 중간, ARM 강함, STG 적정
    스펙: hp 110+28, stg 8+2.8, arm 5+1.4, sparm 3+0.8, spd 8+0.5, luc 5+0.6
    """
    lv = max(1, player_lv)
    base_stg = 8 if lv == 1 else round(8 + 2.8 * (lv - 1), 1)
    unit = Unit(
        name  = "고블린",
        lv    = lv,
        hp    = int(80 + 28 * (lv - 1)),
        mp    = 0,
        stg   = base_stg,
        arm   = round(5   + 1.4 * (lv - 1), 1),
        sparm = round(3   + 0.8 * (lv - 1), 1),
        sp    = 0,
        spd   = round(8   + 0.5 * (lv - 1), 1),
        luc   = round(5   + 0.6 * (lv - 1), 1),
        enemy_type = "고블린",
    )
    return _apply_grade(unit, grade)


def Make_Bat(player_lv: int, grade: str) -> Unit:
    """
    박쥐: 유리대포형 마법/속도 몬스터 (Lv1+ 등장)
    스펙: hp 85+18, mp 34+4, stg Lv1=5/이후 6+1.8,
          arm 3+0.8, sparm 4+0.8, sp 10+2.3, spd 11+0.7, luc 4+0.6
    의도: 빨리 잡지 않으면 아픈 적, 청소몹화 방지
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "박쥐",
        lv    = lv,
        hp    = int(60  + 18 * (lv - 1)),
        mp    = int(34  + 4 * (lv - 1)),
        stg   = 5 if lv == 1 else round(6 + 1.8 * (lv - 1), 1),
        arm   = round(3   + 0.8 * (lv - 1), 1),
        sparm = round(4   + 0.8 * (lv - 1), 1),
        sp    = round(10  + 2.3 * (lv - 1), 1),
        spd   = round(11  + 0.7 * (lv - 1), 1),
        luc   = round(4   + 0.6 * (lv - 1), 1),
        enemy_type = "박쥐",
    )
    return _apply_grade(unit, grade)


# ─────────────────────────────────────────────
# Phase 1: 역할 기반 신규 몬스터 5종
# ─────────────────────────────────────────────

def Make_Slime(player_lv: int, grade: str) -> Unit:
    """
    슬라임: 물리 저항형 초반 특수몹 (Lv3+ 등장)
    스펙: hp 80+18, stg 4+1.5, arm 4+0.9, sparm 5+1.0,
          sp 6+1.2, spd 6+0.4, luc 4+0.4
    특수: 물리 -20% / 마법 +10%
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "슬라임",
        lv    = lv,
        hp    = int(80  + 18 * (lv - 1)),
        mp    = int(20  + lv * 3),
        stg   = round(4   + 1.5 * (lv - 1), 1),
        arm   = round(4   + 0.9 * (lv - 1), 1),
        sparm = round(5   + 1.0 * (lv - 1), 1),
        sp    = round(6   + 1.2 * (lv - 1), 1),
        spd   = round(6   + 0.4 * (lv - 1), 1),
        luc   = round(4   + 0.4 * (lv - 1), 1),
        physical_resist = 0.80,
        magical_resist  = 1.10,
        enemy_type = "슬라임",
    )
    return _apply_grade(unit, grade)



def Make_FireSlime(player_lv: int, grade: str) -> Unit:
    """
    화염 슬라임: 화염 원소 특화 (Lv4+ 등장)
    - 기본 공격: fire 원소 부여
    - 전투 시작 시 fire 큐 보유 → 빙결 공격에 즉시 융해 반응
    - 물리 저항 / 빙결 약점
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "화염 슬라임",
        lv    = lv,
        hp    = int(75  + 16 * (lv - 1)),
        mp    = int(20  + lv * 3),
        stg   = round(4   + 1.4 * (lv - 1), 1),
        arm   = round(3   + 0.8 * (lv - 1), 1),
        sparm = round(4   + 0.9 * (lv - 1), 1),
        sp    = round(8   + 1.5 * (lv - 1), 1),
        spd   = round(7   + 0.5 * (lv - 1), 1),
        luc   = round(4   + 0.4 * (lv - 1), 1),
        physical_resist     = 0.80,
        magical_resist      = 1.10,
        enemy_type          = "화염 슬라임",
        attack_element      = "fire",
        init_element_queue  = ["fire"],
    )
    return _apply_grade(unit, grade)


def Make_IceSlime(player_lv: int, grade: str) -> Unit:
    """
    빙결 슬라임: 빙결 원소 특화 (Lv4+ 등장)
    - 기본 공격: ice 원소 부여
    - 전투 시작 시 ice 큐 보유 → 화염 공격에 즉시 융해 / 물리 공격에 파쇄
    - 물리 저항 / 화염 약점
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "빙결 슬라임",
        lv    = lv,
        hp    = int(85  + 19 * (lv - 1)),
        mp    = int(20  + lv * 3),
        stg   = round(3   + 1.3 * (lv - 1), 1),
        arm   = round(4   + 0.9 * (lv - 1), 1),
        sparm = round(7   + 1.2 * (lv - 1), 1),
        sp    = round(6   + 1.1 * (lv - 1), 1),
        spd   = round(5   + 0.3 * (lv - 1), 1),
        luc   = round(3   + 0.3 * (lv - 1), 1),
        physical_resist     = 0.80,
        magical_resist      = 1.10,
        enemy_type          = "빙결 슬라임",
        attack_element      = "ice",
        init_element_queue  = ["ice"],
    )
    return _apply_grade(unit, grade)


def Make_LightningSlime(player_lv: int, grade: str) -> Unit:
    """
    번개 슬라임: 번개 원소 특화 (Lv4+ 등장)
    - 기본 공격: lightning 원소 부여
    - 전투 시작 시 lightning 큐 보유 → 화염 공격에 즉시 과부하
    - 물리 저항 / 화염 약점
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "번개 슬라임",
        lv    = lv,
        hp    = int(70  + 15 * (lv - 1)),
        mp    = int(20  + lv * 3),
        stg   = round(5   + 1.6 * (lv - 1), 1),
        arm   = round(3   + 0.7 * (lv - 1), 1),
        sparm = round(4   + 0.8 * (lv - 1), 1),
        sp    = round(7   + 1.3 * (lv - 1), 1),
        spd   = round(9   + 0.6 * (lv - 1), 1),
        luc   = round(5   + 0.5 * (lv - 1), 1),
        physical_resist     = 0.80,
        magical_resist      = 1.10,
        enemy_type          = "번개 슬라임",
        attack_element      = "lightning",
        init_element_queue  = ["lightning"],
    )
    return _apply_grade(unit, grade)


def Make_Golem(player_lv: int, grade: str) -> Unit:
    """
    골렘: 물리 강타형 탱커 몬스터 (Lv6+ 등장)
    스펙: hp 120+24, stg 9+1.8, arm 9+1.3, sparm 6+0.9,
          spd 4+0.2, luc 5+0.3
    특수: 마법 -35% / 물리 +10%
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "골렘",
        lv    = lv,
        hp    = int(120 + 24 * (lv - 1)),
        mp    = 0,
        stg   = round(9   + 1.8 * (lv - 1), 1),
        arm   = round(9   + 1.3 * (lv - 1), 1),
        sparm = round(6   + 0.9 * (lv - 1), 1),
        sp    = 0,
        spd   = round(4   + 0.2 * (lv - 1), 1),
        luc   = round(5   + 0.3 * (lv - 1), 1),
        physical_resist = 1.10,
        magical_resist  = 0.65,
        enemy_type = "골렘",
    )
    return _apply_grade(unit, grade)


def Make_Ghost(player_lv: int, grade: str) -> Unit:
    """
    유령: 회피형 상성 몬스터 (Lv7+ 등장)
    스펙: hp 70+14, stg 6+1.6, arm 2+0.5, sparm 4+0.8,
          sp 5+1.1, spd 9+0.7, luc 8+0.6
    특수: 회피 +20%, 다단히트 피해 보정 감소
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "유령",
        lv    = lv,
        hp    = int(70  + 14 * (lv - 1)),
        mp    = int(20  + lv * 2),
        stg   = round(6   + 1.6 * (lv - 1), 1),
        arm   = round(2   + 0.5 * (lv - 1), 1),
        sparm = round(4   + 0.8 * (lv - 1), 1),
        sp    = round(5   + 1.1 * (lv - 1), 1),
        spd   = round(9   + 0.7 * (lv - 1), 1),
        luc   = round(8   + 0.6 * (lv - 1), 1),
        dodge_bonus = 0.20,
        dodge_penalty_per_extra_hit = 0.10,
        enemy_type = "유령",
    )
    return _apply_grade(unit, grade)


def Make_Assassin(player_lv: int, grade: str) -> Unit:
    """
    암살자: 선공/첫타 강화형 고위험 몬스터 (Lv10+ 등장)
    스펙: hp 50+12, stg 10+2.0, arm 4+0.7, sparm 3+0.6,
          spd 10+0.8, luc 10+0.7
    특수: 선공 + 첫 공격 +15%
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "암살자",
        lv    = lv,
        hp    = int(50  + 12 * (lv - 1)),
        mp    = 0,
        stg   = round(10  + 2.0 * (lv - 1), 1),
        arm   = round(4   + 0.7 * (lv - 1), 1),
        sparm = round(3   + 0.6 * (lv - 1), 1),
        sp    = 0,
        spd   = round(10  + 0.8 * (lv - 1), 1),
        luc   = round(10  + 0.7 * (lv - 1), 1),
        first_strike       = True,
        first_attack_bonus = 1.15,
        enemy_type = "암살자",
    )
    return _apply_grade(unit, grade)

def Make_Priest(player_lv: int, grade: str) -> Unit:
    """
    사제: 서포터형 몬스터 (Lv9+ 등장)

    역할 정체성:
      - 본인 공격력은 약함. 다른 아군 몬스터를 회복/버프하는 게 핵심.
      - 다대일에서 등장 시 가장 위협적 — 먼저 잡아야 하는 우선순위 타깃.
      - 단독 등장 시에는 약한 마법 몬스터로 동작.

    스펙:
      hp 70+15, mp 50+5, stg 4+0.8, arm 4+0.8, sparm 7+1.2,
      sp 10+1.8, spd 7+0.4, luc 6+0.5

    특수 동작 (Battlesession._priest_action):
      1) 다른 아군 중 HP ≤ 70%면 → 사제힐 (가장 비율 낮은 아군)
      2) 30% 확률로 사제축복 (가장 STG 높은 아군에게 STG 버프)
      3) 그 외 → 홀리볼트 (마법 공격)
      4) MP 부족 시 → 기본 물리 공격
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "사제",
        lv    = lv,
        hp    = int(70  + 15 * (lv - 1)),
        mp    = int(50  + 5  * (lv - 1)),
        stg   = round(4   + 0.8 * (lv - 1), 1),
        arm   = round(4   + 0.8 * (lv - 1), 1),
        sparm = round(7   + 1.2 * (lv - 1), 1),
        sp    = round(10  + 1.8 * (lv - 1), 1),
        spd   = round(7   + 0.4 * (lv - 1), 1),
        luc   = round(6   + 0.5 * (lv - 1), 1),
        enemy_type = "사제",
    )
    return _apply_grade(unit, grade)

def Make_Random_Monster(player_lv: int) -> Unit:
    """
    [구 콘솔/테스트용] 랜덤 몬스터 + 랜덤 등급 — 레벨대별 풀.
    ⚠ 메인 노드맵에서는 사용하지 않음. 실제 게임의 몬스터 출현은
      app/Map.py의 CHAPTER_TIER_POOL(챕터+노드 구간 기준)이 단일 기준.
      Lv1+:  고블린, 박쥐
      Lv3+:  + 슬라임
      Lv5+:  + 골렘
      Lv7+:  + 유령
      Lv8+:  + 암살자
      Lv9+:  + 사제          ← 신규
    등급: 하40% / 중45% / 상15%

    Balance_Hook의 _ENEMY_POOL과 동일한 규칙 — 콘솔/웹 풀 일치.
    """
    roll = random()
    if   roll < 0.40: grade = "하"
    elif roll < 0.85: grade = "중"
    else:             grade = "상"

    pool = [Make_Goblin, Make_Bat]
    if player_lv >= 3:  pool.append(Make_Slime)
    if player_lv >= 4:  pool.extend([Make_FireSlime, Make_IceSlime, Make_LightningSlime])
    if player_lv >= 5:  pool.append(Make_Golem)
    if player_lv >= 6:  pool.append(Make_Ghost)
    if player_lv >= 6:  pool.append(Make_Assassin)
    if player_lv >= 8:  pool.append(Make_Priest)
    return choice(pool)(player_lv, grade)

def Make_MidBoss(player_lv: int) -> Unit:
    # TODO(밸런스): MC 실측상 중간보스는 Lv15 근처 권장 (Lv10 승률: 마법사 62.8%,
    #   전사 7.8%, 탱커 0%, 도적 1%). 추후 UI/로그에 "권장 레벨 Lv15" 안내 예정.
    #   보스 수치 자체는 조정하지 않는다 (Lv15 이후 난이도 유지 목적).
    """
    중간 보스: 오래 버티는 적 (Lv14 전후) — 5차 조정.
    ...
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "중간 보스",
        lv    = lv,
        hp    = 1200,
        mp    = 100,
        stg   = 36,
        arm   = 27,
        sparm = 24,
        sp    = 28,
        spd   = 24,
        luc   = 22,
        grade = "상",
        is_boss      = True,
        debuff_resist = 0.30,
    )

    # ── 중간 보스 전용 경험치 보상 ──
    # 일반 상급 (0.45 × maxexp) 대신 1.5 × maxexp → 약 1.5레벨업.
    # 메서드 동적 부여로 Unit 클래스 자체는 안 건드림.
    unit.exp_reward = lambda player_maxexp: int(player_maxexp * 1.5)

    return unit


def Make_FinalBoss(player_lv: int) -> Unit:
    """
    최종 보스: HP/저항 위주 (Lv25 전후) — 5차 조정.
    스펙(5차): hp 3450, mp 220, stg 64, arm 51, sparm 58, sp 62,
              spd 34, luc 40, debuff_resist 0.50
    의도: 도전적이지만 가능한 보스.
      - 4차 실측(BattleSession 시뮬, 각 80판): 전사 87.5% / 마법사 100% /
        탱커 100% / 도적 95% → 전 직업 목표(50~80%) 초과, 특히 마법사가
        압도적으로 쉬움.
      - hp/stg/arm/sp를 공통으로 ×1.15 (4000 threat 상승), sparm만 별도로
        더 올려(36→58) 마법 데미지만 선별적으로 억제 — stg/arm을 더 올리면
        이미 하한에 가까운 전사/도적이 먼저 무너지기 때문에 물리 계열은
        건드리지 않고 마법사만 겨냥.
      - 5차 실측(2개 시드 × 각 60판): 전사 60~67% / 마법사 72~82% /
        도적 80~85% / 탱커 97~100%.
      - 탱커는 방어형 직업 설계상 보스전에서 구조적으로 유리(고ARM+피격
        회복 패시브로 장기전에 절대적으로 강함) — 100% 근접 승률은
        아웃라이어로 받아들이고 이번 조정 대상에서 제외.
    """
    lv = max(25, player_lv)
    unit = Unit(
        name  = "최종 보스",
        lv    = lv,
        hp    = 3450,
        mp    = 220,
        stg   = 64,
        arm   = 51,
        sparm = 58,
        sp    = 62,
        spd   = 34,
        luc   = 40,
        grade = "상",
        is_boss      = True,
        debuff_resist = 0.50,
    )
    return unit