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
                 grade="중", is_boss=False, debuff_resist=0.0):
        self.name          = name
        self.lv            = lv
        self.hp            = hp
        self.mp            = mp
        self.stg           = stg
        self.arm           = arm
        self.sparm         = sparm
        self.sp            = sp
        self.spd           = spd
        self.luc           = luc
        self.grade         = grade
        self.is_boss       = is_boss
        self.debuff_resist = debuff_resist

    def exp_reward(self, player_maxexp: int) -> int:
        ratio = {"상": 0.45, "중": 0.34, "하": 0.28}.get(self.grade, 0.34)
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
    "하": {"hp": 0.70, "stg": 0.80, "arm": 0.85, "sparm": 0.85, "sp": 0.80},
    "중": {"hp": 1.00, "stg": 1.00, "arm": 1.00, "sparm": 1.00, "sp": 1.00},
    "상": {"hp": 1.30, "stg": 1.20, "arm": 1.15, "sparm": 1.15, "sp": 1.20},
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
    고블린: 근접 탱커 성향
    HP 중간, ARM 강함, STG 적정
    하급: 플레이어 2~3방 처치 / 중급: 4~6방 / 상급: 7~9방
    (v3: HP 85→120, 레벨당 24→26 — DamageCalc v2 공식과 밸런스 재정렬)
    """
    lv = max(1, player_lv)
    # Lv1 STG=7 고정, 이후 레벨부터 성장
    base_stg = 7 if lv == 1 else round(8 + 2.5 * (lv - 1), 1)
    unit = Unit(
        name  = "고블린",
        lv    = lv,
        hp    = int(120 + 26 * (lv - 1)),
        mp    = 0,
        stg   = base_stg,
        arm   = round(5   + 1.2 * (lv - 1), 1),
        sparm = round(3   + 0.8 * (lv - 1), 1),
        sp    = 0,
        spd   = round(8   + 0.5 * (lv - 1), 1),
        luc   = round(5   + 0.6 * (lv - 1), 1),
    )
    return _apply_grade(unit, grade)


def Make_Bat(player_lv: int, grade: str) -> Unit:
    """
    박쥐: 유리대포 성향
    HP 낮음, SPD 빠름, SP 있음 (마법 공격)
    하급: 플레이어 1~2방 처치 / 중급: 3~5방 / 상급: HP 낮고 SP 높음
    (v3: HP 55→80, 레벨당 14→16 — DamageCalc v2 공식과 밸런스 재정렬)
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "박쥐",
        lv    = lv,
        hp    = int(80  + 16 * (lv - 1)),
        mp    = int(15  + lv * 2),
        stg   = 5 if lv == 1 else round(6 + 1.8 * (lv - 1), 1),  # Lv1=5 고정
        arm   = round(3   + 0.8 * (lv - 1), 1),
        sparm = round(2   + 0.6 * (lv - 1), 1),
        sp    = round(8   + 2.0 * (lv - 1), 1),
        spd   = round(12  + 0.8 * (lv - 1), 1),
        luc   = round(4   + 0.6 * (lv - 1), 1),
    )
    return _apply_grade(unit, grade)


def Make_Random_Monster(player_lv: int) -> Unit:
    """
    랜덤 몬스터 + 랜덤 등급
    하40% / 중45% / 상15%
    """
    roll = random()
    if   roll < 0.40: grade = "하"
    elif roll < 0.85: grade = "중"
    else:             grade = "상"
    return choice([Make_Goblin, Make_Bat])(player_lv, grade)


def Make_MidBoss(player_lv: int, base_monster_snap=None) -> Unit:
    """
    중간 보스: 오래 버티는 적
    STG 낮추고 HP/ARM/SPARM/저항으로 난이도 부여
    Lv14 기준 승률 ~50%, 평균 8~10턴
    """
    lv = max(1, player_lv)
    unit = Unit(
        name  = "중간 보스",
        lv    = lv,
        hp    = 950,
        mp    = 80,
        stg   = 35,
        arm   = 35,
        sparm = 28,
        sp    = 20,
        spd   = 22,
        luc   = 10,
        grade = "상",
        is_boss      = True,
        debuff_resist = 0.30,
    )
    return unit


def Make_FinalBoss(player_lv: int, base_monster_snap=None) -> Unit:
    """
    최종 보스: HP/ARM/SPARM/저항 위주
    STG는 적정 수준 유지
    """
    lv = max(25, player_lv)
    unit = Unit(
        name  = "최종 보스",
        lv    = lv,
        hp    = 2950,
        mp    = 200,
        stg   = 72,
        arm   = 60,
        sparm = 36,
        sp    = 50,
        spd   = 35,
        luc   = 20,
        grade = "상",
        is_boss      = True,
        debuff_resist = 0.50,
    )
    return unit