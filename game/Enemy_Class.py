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
from random import randint, random, choice


class Unit:
    def __init__(self, name, lv, hp, mp, stg, arm, sparm, sp, spd, luc,
                 grade="중", is_boss=False, debuff_resist=0.0,
                 # ── Phase 1: 역할 기반 메커니즘 ──
                 physical_resist=1.0, magical_resist=1.0,
                 dodge_bonus=0.0, dodge_penalty_per_extra_hit=0.10,
                 first_strike=False, first_attack_bonus=1.0,
                 enemy_type=""):
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

    def exp_reward(self, player_maxexp: int) -> int:
        ratio = {"상": 0.7, "중": 0.55, "하": 0.45}.get(self.grade, 0.34)
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
    "하": {"hp": 0.6, "stg": 0.70, "arm": 0.85, "sparm": 0.7, "sp": 0.70},
    "중": {"hp": 0.90, "stg": 0.90, "arm": 1.00, "sparm": 0.8, "sp": 0.80},
    "상": {"hp": 1.20, "stg": 1.12, "arm": 1.10, "sparm": 0.9, "sp": 1.0},
}


def _apply_grade(unit: Unit, grade: str) -> Unit:
    m = GRADE_MULT[grade]
    unit.hp    = int(unit.hp    * m["hp"])
    unit.stg   = round(unit.stg   * m["stg"],   1)
    unit.arm   = round(unit.arm   * m["arm"],   1)
    unit.sparm = round(unit.sparm * m["sparm"], 1)
    unit.sp    = round(unit.sp    * m["sp"],    1)
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
        hp    = int(110 + 28 * (lv - 1)),
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
        hp    = int(85  + 18 * (lv - 1)),
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
    특수: 물리 -35% / 마법 +10%
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
        physical_resist = 0.65,
        magical_resist  = 1.10,
        enemy_type = "슬라임",
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
    랜덤 몬스터 + 랜덤 등급. 레벨대별 풀 적용 (Phase 1 통합).
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
    if player_lv >= 5:  pool.append(Make_Golem)
    if player_lv >= 7:  pool.append(Make_Ghost)
    if player_lv >= 8:  pool.append(Make_Assassin)
    if player_lv >= 9:  pool.append(Make_Priest)
    return choice(pool)(player_lv, grade)

def Make_MidBoss(player_lv: int, base_monster_snap=None) -> Unit:
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


def Make_FinalBoss(player_lv: int, base_monster_snap=None) -> Unit:
    """
    최종 보스: HP/저항 위주 (Lv25 전후) — 4차 조정.
    스펙(4차): hp 3000, mp 220, stg 56, arm 44, sparm 36, sp 54,
              spd 34, luc 40, debuff_resist 0.50
    의도: 도전적이지만 가능한 보스.
      - 3차: 도적 100, 전사 100, 마법사 99, 탱커 100 → 너무 쉬움
      - hp 2700→3000 (장기전 강화)
      - stg 50→56 / arm 40→44 / sparm 32→36
      - luc 38→40 (도적 회피·크리 견제)
      - spd 32→34
      - 목표: 모든 직업 50~80% 정도
    """
    lv = max(25, player_lv)
    unit = Unit(
        name  = "최종 보스",
        lv    = lv,
        hp    = 3000,
        mp    = 220,
        stg   = 56,
        arm   = 44,
        sparm = 36,
        sp    = 54,
        spd   = 34,
        luc   = 40,
        grade = "상",
        is_boss      = True,
        debuff_resist = 0.50,
    )
    return unit