"""
Enemy_Class.py
─────────────────────────────────────────────
몬스터 클래스 및 생성 모듈.

변경사항:
  - 상/중/하 등급 시스템 (경험치 차등 지급)
  - 몬스터 행동 패턴 (지켜보기 / 일반공격 / 마법공격+디버프)
  - 중간 보스 / 최종 보스 생성 로직
  - 경험치: 플레이어 maxexp의 상50% / 중38% / 하32%
"""

from random import randint, random, choice


# ────────────────────────────────────────────
# 기본 Unit 클래스
# ────────────────────────────────────────────

class Unit:
    def __init__(self, name, lv, hp, mp, stg, arm, sparm, sp, spd, luc,
                 grade="중", is_boss=False):
        self.name   = name
        self.lv     = lv
        self.hp     = hp
        self.mp     = mp
        self.stg    = stg
        self.arm    = arm
        self.sparm  = sparm
        self.sp     = sp
        self.spd    = spd
        self.luc    = luc
        self.grade  = grade    # "상" | "중" | "하"
        self.is_boss = is_boss

    def exp_reward(self, player_maxexp: int) -> int:
        """
        등급별 경험치 보상.
        상: maxexp의 50% / 중: 38% / 하: 32%
        """
        ratio = {"상": 0.50, "중": 0.38, "하": 0.32}.get(self.grade, 0.38)
        return int(player_maxexp * ratio)

    def decide_action(self, player) -> str:
        """
        몬스터 행동 결정.
        반환: "attack" | "magic" | "watch"

        행동 가중치:
          - 기본: attack 60% / magic 25% / watch 15%
          - 상급: attack 50% / magic 35% / watch 15%
          - 보스: attack 45% / magic 40% / watch 15%
        """
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


# ────────────────────────────────────────────
# 등급별 스탯 배율
# ────────────────────────────────────────────

GRADE_MULT = {
    "하": {"hp": 0.75, "stg": 0.80, "arm": 0.80, "sparm": 0.80, "sp": 0.80},
    "중": {"hp": 1.00, "stg": 1.00, "arm": 1.00, "sparm": 1.00, "sp": 1.00},
    "상": {"hp": 1.30, "stg": 1.25, "arm": 1.20, "sparm": 1.20, "sp": 1.25},
}


# ────────────────────────────────────────────
# 몬스터 생성 함수
# ────────────────────────────────────────────

def _apply_grade(unit: Unit, grade: str) -> Unit:
    """등급 배율을 적용한 새 Unit 반환"""
    m = GRADE_MULT[grade]
    unit.hp    = int(unit.hp    * m["hp"])
    unit.stg   = round(unit.stg   * m["stg"],   1)
    unit.arm   = round(unit.arm   * m["arm"],   1)
    unit.sparm = round(unit.sparm * m["sparm"], 1)
    unit.sp    = round(unit.sp    * m["sp"],    1)
    unit.grade = grade
    return unit


def Make_Goblin(player_lv: int, grade: str = "중") -> Unit:
    """
    플레이어 레벨 기반 고블린 생성.
    grade: "상" | "중" | "하"
    """
    base = Unit("고블린", 1, 75, 0, 2, 6, 0, 0, 5, 5)
    lv = max(1, player_lv)

    unit = Unit(
        name="고블린",
        lv=lv,
        hp=int(base.hp + 22 * (lv - 1)),
        mp=0,
        stg=round(base.stg + 2 * (lv - 1), 1),
        arm=round(base.arm + 1.5 * (lv - 1), 1),
        sparm=round(base.sparm + 1.2 * (lv - 1), 1),
        sp=0,
        spd=round(base.spd + 2 * (lv - 1), 1),
        luc=round(base.luc + 1.2 * (lv - 1), 1),
    )
    return _apply_grade(unit, grade)


def Make_Bat(player_lv: int, grade: str = "중") -> Unit:
    """
    플레이어 레벨 기반 박쥐 생성.
    박쥐는 스피드가 빠른 대신 체력이 낮음.
    """
    base = Unit("박쥐", 1, 15, 5, 5, 5, 0, 0, 7, 0)
    lv = max(1, player_lv)

    unit = Unit(
        name="박쥐",
        lv=lv,
        hp=int(base.hp + 25 * (lv - 1)),
        mp=int(5 + lv * 2),
        stg=round(base.stg + 2 * (lv - 1), 1),
        arm=round(base.arm + 1.5 * (lv - 1), 1),
        sparm=round(base.sparm + 1.2 * (lv - 1), 1),
        sp=round(3 + lv * 1.5, 1),
        spd=round(base.spd + 2.5 * (lv - 1), 1),   # 박쥐는 스피드 성장 빠름
        luc=round(base.luc + 1.2 * (lv - 1), 1),
    )
    return _apply_grade(unit, grade)


def Make_Random_Monster(player_lv: int) -> Unit:
    """
    랜덤 몬스터 + 랜덤 등급 생성.
    등급 가중치: 하 40% / 중 45% / 상 15%
    """
    roll = random()
    if roll < 0.40:
        grade = "하"
    elif roll < 0.85:
        grade = "중"
    else:
        grade = "상"

    makers = [Make_Goblin, Make_Bat]
    maker  = choice(makers)
    return maker(player_lv, grade)


# ────────────────────────────────────────────
# 보스 생성
# ────────────────────────────────────────────

def Make_MidBoss(player_lv: int, base_monster_snap=None) -> Unit:
    """
    중간 보스 생성.
    - 승률 60% 기준 몬스터 스탯 사용 (시뮬레이터에서 생성된 snap 활용)
    - 체력은 해당 스탯의 1.5배
    - base_monster_snap이 없으면 고블린 기반으로 생성
    """
    lv = max(1, player_lv)

    if base_monster_snap:
        unit = Unit(
            name="중간 보스",
            lv=lv,
            hp=int(base_monster_snap.hp * 1.5),
            mp=int(base_monster_snap.mp),
            stg=base_monster_snap.stg,
            arm=base_monster_snap.arm,
            sparm=base_monster_snap.sparm,
            sp=base_monster_snap.sp,
            spd=base_monster_snap.spd,
            luc=base_monster_snap.luc,
            grade="상",
            is_boss=True,
        )
    else:
        # 폴백: 고블린 상급 기반
        base = Make_Goblin(lv, "상")
        unit = Unit(
            name="중간 보스",
            lv=lv,
            hp=int(base.hp * 1.5),
            mp=int(lv * 5),
            stg=base.stg,
            arm=base.arm,
            sparm=base.sparm,
            sp=round(lv * 2.0, 1),
            spd=base.spd,
            luc=base.luc,
            grade="상",
            is_boss=True,
        )
    return unit


def Make_FinalBoss(player_lv: int, base_monster_snap=None) -> Unit:
    """
    최종 보스 생성.
    - 플레이어 레벨 30 이상 가정
    - 승률 49% 기준 스탯 (시뮬레이터에서 생성된 snap 활용)
    - base_monster_snap이 없으면 고블린 상급 기반
    """
    lv = max(30, player_lv)

    if base_monster_snap:
        unit = Unit(
            name="최종 보스",
            lv=lv,
            hp=int(base_monster_snap.hp),
            mp=int(base_monster_snap.mp),
            stg=base_monster_snap.stg,
            arm=base_monster_snap.arm,
            sparm=base_monster_snap.sparm,
            sp=base_monster_snap.sp,
            spd=base_monster_snap.spd,
            luc=base_monster_snap.luc,
            grade="상",
            is_boss=True,
        )
    else:
        base = Make_Goblin(lv, "상")
        unit = Unit(
            name="최종 보스",
            lv=lv,
            hp=int(base.hp * 2.0),
            mp=int(lv * 8),
            stg=round(base.stg * 1.3, 1),
            arm=round(base.arm * 1.2, 1),
            sparm=round(base.sparm * 1.2, 1),
            sp=round(lv * 3.0, 1),
            spd=base.spd,
            luc=base.luc,
            grade="상",
            is_boss=True,
        )
    return unit