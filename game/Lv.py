"""
Lv.py
─────────────────────────────────────────────
레벨업 및 경험치 시스템.

핵심 기능:
  - 직업별 성장치(JOB_GROWTH) 기반 스탯 상승
  - 레벨업 시 MP 회복: 레벨업 전 MP 비율 유지
  - 레벨업 시 HP 일부 회복
  - 레벨별 스킬 해금
  - 연속 레벨업 처리
  - maxexp 점진 증가

주의:
  - player 객체에 아래 속성이 있다고 가정:
    name, lv, exp, maxexp, hp, maxhp, mp, maxmp,
    stg, sp, arm, sparm, spd, luc, job
  - job 값은 "전사" / "마법사" / "탱커" / "도적" 중 하나
  - player.skill 이 없어도 동작하도록 방어 코드 포함
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import randint
from typing import Dict, List, Optional

try:
    from game.Skill import Ply_Skill
except ModuleNotFoundError:
    try:
        from Skill import Ply_Skill
    except ModuleNotFoundError:
        Ply_Skill = None  # fallback


# ─────────────────────────────────────────────
# 직업별 성장 공식
# ─────────────────────────────────────────────
JOB_GROWTH = {
    "전사": {
        # 기준선 직업 — 거의 유지
        "hp":    lambda lv: 40 + lv * 3,
        "mp":    lambda lv: 4 + lv // 5,
        "stg":   lambda lv: 1.4 + lv // 5,
        "sp":    lambda lv: 0.6 + lv // 8,
        "arm":   lambda lv: 1.6,
        "sparm": lambda lv: 1.0,
        "spd":   lambda lv: 0.8,
        "luc":   lambda lv: lv % 2,
    },
    "마법사": {
        # 후반 과성장 억제: mp 8→7, lv//3→lv//4 / sp 2.2→1.8, lv//4→lv//5 / luc lv%3→lv%4
        "hp":    lambda lv: 30 + lv * 2,
        "mp":    lambda lv: 7 + lv // 4,
        "stg":   lambda lv: 0.7 + lv // 8,
        "sp":    lambda lv: 1.8 + lv // 5,
        "arm":   lambda lv: 0.8,
        "sparm": lambda lv: 1.4,
        "spd":   lambda lv: 0.6,
        "luc":   lambda lv: lv % 4,
    },
    "탱커": {
        # 거의 유지
        "hp":    lambda lv: 50 + lv * 4,
        "mp":    lambda lv: 3 + lv // 6,
        "stg":   lambda lv: 1.0 + lv // 7,
        "sp":    lambda lv: 0.4 + lv // 10,
        "arm":   lambda lv: 2.0,
        "sparm": lambda lv: 1.5,
        "spd":   lambda lv: 0.5,
        "luc":   lambda lv: lv % 4,
    },
    "도적": {
        # 후반 폭주 억제: stg 1.3→1.0, lv//6→lv//7 / spd 1.2→0.9, lv//6→lv//8
        # luc 1.0→0.6, lv//4→lv//6
        "hp":    lambda lv: 40 + lv * 2,
        "mp":    lambda lv: 5 + lv // 4,
        "stg":   lambda lv: 1.0 + lv // 7,
        "sp":    lambda lv: 0.8 + lv // 7,
        "arm":   lambda lv: 1.0,
        "sparm": lambda lv: 0.7,
        "spd":   lambda lv: 0.9 + lv // 8,
        "luc":   lambda lv: 0.6 + lv // 6,
    },
}


# ─────────────────────────────────────────────
# 직업별 스킬 해금 테이블
# ─────────────────────────────────────────────
JOB_SKILL_UNLOCKS: Dict[str, Dict[int, List[str]]] = {
    "전사": {
        1:  ["강타1"],
        3:  ["연속공격1"],
        4:  ["슬래시1"],   # 밸런스 패치: Lv7→Lv4 — 초반 다대일 대응 (MC: Lv5 1대2 27.8%)
        5:  ["강화1"],
        6:  ["약화1"],
        10: ["강타2"],
        12: ["약화2"],
        13: ["연속공격2"],
        16: ["강화2"],
        20: ["슬래시2"],
    },
    "마법사": {
        1:  ["파이어볼1"],
        3:  ["힐1"],
        2:  ["아이스볼릿1"],
        4:  ["마약화1", "라이트닝1"],
        5:  ["효율성1"],
        12: ["마약화2"],
        13: ["파이어볼2"],
        16: ["힐2"],
        19: ["아이스볼릿2"],
        22: ["라이트닝2"],
        25: ["효율성2"],
    },
    "탱커": {
        1:  ["몸통박치기1"],
        3:  ["수비태세1"],
        5:  ["실드"],
        6:  ["저주1"],
        7:  ["되갚기1"],
        10: ["몸통박치기2"],
        12: ["저주2"],
        14: ["수비태세2"],
        18: ["되갚기2"],
    },
    "도적": {
        1:  ["급소찌르기1"],
        3:  ["추진력"],
        5:  ["연속찌르기"],
        6:  ["둔화1"],
        7:  ["난사1"],
        10: ["급소찌르기2"],
        12: ["둔화2"],
        14: ["난사2"],
    },
}

# 상위 스킬이 하위 스킬을 대체할 때의 매핑
SKILL_REPLACEMENTS = {
    "강타2": "강타1",
    "연속공격2": "연속공격1",
    "강화2": "강화1",
    "슬래시2": "슬래시1",
    "약화2": "약화1",

    "파이어볼2": "파이어볼1",
    "아이스볼릿2": "아이스볼릿1",
    "라이트닝2": "라이트닝1",
    "힐2": "힐1",
    "효율성2": "효율성1",
    "마약화2": "마약화1",

    "몸통박치기2": "몸통박치기1",
    "되갚기2": "되갚기1",
    "수비태세2": "수비태세1",
    "저주2": "저주1",

    "급소찌르기2": "급소찌르기1",
    "난사2": "난사1",
    "둔화2": "둔화1",
}


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────
def _get_job(player) -> str:
    """
    player.job / player.job_name / player.cls 중 하나에서 직업명을 찾는다.
    """
    for attr in ("job", "job_name", "cls", "class_name"):
        job = getattr(player, attr, None)
        if job in JOB_GROWTH:
            return job
    raise ValueError(
        "플레이어 직업 정보를 찾을 수 없음. "
        "player.job(또는 job_name/cls)에 '전사/마법사/탱커/도적'이 있어야 함."
    )


def _ensure_skill_container(player) -> None:
    """
    player.skill, player.learned_skills 보정.
    """
    if not hasattr(player, "learned_skills") or player.learned_skills is None:
        player.learned_skills = []

    if not hasattr(player, "skill") or player.skill is None:
        if Ply_Skill is not None:
            try:
                player.skill = Ply_Skill()
            except Exception:
                player.skill = None
        else:
            player.skill = None


def _safe_round_stat(value: float) -> float:
    """
    스탯 표시용 반올림.
    정수면 int처럼 보이게, 아니면 소수 첫째 자리까지.
    """
    if float(value).is_integer():
        return int(value)
    return round(value, 1)


def _remove_old_skill_if_replaced(player, new_skill: str) -> None:
    old_skill = SKILL_REPLACEMENTS.get(new_skill)
    if old_skill and old_skill in player.learned_skills:
        player.learned_skills.remove(old_skill)


def _sync_skill_object(player) -> None:
    """
    Skill 객체가 있다면 가능한 방식으로 동기화.
    프로젝트마다 Skill.py 구현이 다를 수 있어서 방어적으로 처리한다.
    """
    if player.skill is None:
        return

    # 1) learned_skills 속성이 있으면 그대로 반영
    if hasattr(player.skill, "learned_skills"):
        try:
            player.skill.learned_skills = list(player.learned_skills)
            return
        except Exception:
            pass

    # 2) set_skills(skills)
    if hasattr(player.skill, "set_skills"):
        try:
            player.skill.set_skills(list(player.learned_skills))
            return
        except Exception:
            pass

    # 3) update_skills(job, lv, learned)
    if hasattr(player.skill, "update_skills"):
        for args in (
            (_get_job(player), player.lv, list(player.learned_skills)),
            (_get_job(player), player.lv),
            (player.lv,),
            tuple(),
        ):
            try:
                player.skill.update_skills(*args)
                return
            except TypeError:
                continue
            except Exception:
                break

    # 4) skills 속성에 직접 주입
    if hasattr(player.skill, "skills"):
        try:
            player.skill.skills = list(player.learned_skills)
        except Exception:
            pass


def _unlock_skills_for_current_level(player) -> List[str]:
    """
    현재 레벨에서 새로 배우는 스킬 목록 반환.
    """
    job = _get_job(player)
    unlock_table = JOB_SKILL_UNLOCKS.get(job, {})
    new_skills = unlock_table.get(player.lv, [])

    learned_now = []
    for skill_name in new_skills:
        if skill_name not in player.learned_skills:
            _remove_old_skill_if_replaced(player, skill_name)
            player.learned_skills.append(skill_name)
            learned_now.append(skill_name)

    # 배우고 나서 skill 객체에도 반영
    _sync_skill_object(player)
    return learned_now


def _initialize_skills_for_existing_level(player) -> None:
    """
    로드된 세이브나 초기 생성 직후 플레이어의 레벨에 맞춰
    지금까지 배웠어야 할 스킬을 전부 채운다.
    """
    _ensure_skill_container(player)
    if player.learned_skills:
        _sync_skill_object(player)
        return

    job = _get_job(player)
    unlock_table = JOB_SKILL_UNLOCKS.get(job, {})

    for lv in sorted(unlock_table.keys()):
        if lv <= player.lv:
            for skill_name in unlock_table[lv]:
                _remove_old_skill_if_replaced(player, skill_name)
                if skill_name not in player.learned_skills:
                    player.learned_skills.append(skill_name)

    _sync_skill_object(player)


# ─────────────────────────────────────────────
# 레벨업 시스템
# ─────────────────────────────────────────────
class LV_:
    #EXP_GROWTH_RATE = 1.18  # 레벨업 후 필요 경험치 증가율
    GROWTH_RATIO = 0.7          # ★ 자동 성장 비율 (70%)
    POINTS_PER_LEVEL = 3        # ★ 레벨업당 선택 포인트

    def __init__(self, ply):
        self.player = ply
        _initialize_skills_for_existing_level(self.player)

    # ★ 스탯 선택 시스템: 전투 스탯 성장 비율
    # 자동 성장 70% + 선택 포인트 30%. HP/MP는 생존 기반이라 100% 유지.
    GROWTH_RATIO = 0.7

    @staticmethod
    def apply_growth(player) -> None:
        job = _get_job(player)
        growth = JOB_GROWTH[job]
        lv = player.lv

        hp_gain = growth["hp"](lv)
        mp_gain = growth["mp"](lv)
        # 전투 스탯은 70%만 자동 (나머지 30%는 선택 포인트로)
        r = LV_.GROWTH_RATIO
        stg_gain = growth["stg"](lv) * r
        sp_gain = growth["sp"](lv) * r
        arm_gain = growth["arm"](lv) * r
        sparm_gain = growth["sparm"](lv) * r
        spd_gain = growth["spd"](lv) * r
        luc_gain = growth["luc"](lv) * r

        # HP/MP는 100% (생존 기반)
        player.maxhp += hp_gain
        player.maxmp += mp_gain
        # 전투 스탯 70%
        player.stg += stg_gain
        player.sp += sp_gain
        player.arm += arm_gain
        player.sparm += sparm_gain
        player.spd += spd_gain
        player.luc += luc_gain

    @staticmethod
    def Lv_up(player) -> None:
        """
        레벨업 처리:
          - MP는 기존 비율 유지
          - HP는 일부 회복
          - 직업별 성장치 적용
          - 스킬 해금
          - 필요 경험치(maxexp) 증가
        """
        _initialize_skills_for_existing_level(player)

        # 1) 레벨업 전 비율 저장
        mp_ratio = (player.mp / player.maxmp) if getattr(player, "maxmp", 0) > 0 else 1.0
        hp_ratio = (player.hp / player.maxhp) if getattr(player, "maxhp", 0) > 0 else 1.0

        # 2) 이전 스탯 저장
        before = {
            "maxhp": player.maxhp,
            "maxmp": player.maxmp,
            "stg": player.stg,
            "sp": player.sp,
            "arm": player.arm,
            "sparm": player.sparm,
            "spd": getattr(player, "spd", 0),
            "luc": player.luc,
        }

        old_lv = player.lv
        player.lv += 1

        # ★ 스탯 선택 포인트 지급 (레벨업당 3)
        if not hasattr(player, "pending_points"):
            player.pending_points = 0
        player.pending_points += LV_.POINTS_PER_LEVEL

        # 3) 성장 적용 (전투 스탯 70%)
        LV_.apply_growth(player)

        # 4) HP / MP 회복
        # HP: 기존 비율 유지 + 레벨업 보너스 회복
        bonus_heal = max(20, int(before["maxhp"] * 0.15))
        player.hp = int(player.maxhp * hp_ratio) + bonus_heal
        player.hp = min(player.hp, player.maxhp)

        # MP: 기존 비율 유지
        player.mp = int(round(player.maxmp * mp_ratio))
        player.mp = min(player.mp, player.maxmp)

        # 5) 경험치 차감 및 maxexp 증가
        player.exp -= player.maxexp
        #player.maxexp = max(1, int(round(player.maxexp * LV_.EXP_GROWTH_RATE)))

        # 6) 스킬 해금
        unlocked_skills = _unlock_skills_for_current_level(player)

        # 7) 출력
        after = {
            "maxhp": player.maxhp,
            "maxmp": player.maxmp,
            "stg": player.stg,
            "sp": player.sp,
            "arm": player.arm,
            "sparm": player.sparm,
            "spd": getattr(player, "spd", 0),
            "luc": player.luc,
        }

        name_map = {
            "maxhp": "HP",
            "maxmp": "MP",
            "stg": "힘",
            "sp": "마력",
            "arm": "방어력",
            "sparm": "마법방어력",
            "spd": "속도",
            "luc": "행운",
        }

        print(f"\n📈 {player.name} 레벨업! (Lv.{old_lv} → Lv.{player.lv})")
        print(f"   HP 회복: {player.hp}/{player.maxhp}")
        print(f"   MP 회복: {int(mp_ratio * 100)}% 유지 → {player.mp}/{player.maxmp}")

        for stat_key in before:
            b = _safe_round_stat(before[stat_key])
            a = _safe_round_stat(after[stat_key])
            if b != a:
                print(f"   {name_map[stat_key]}: {b} → {a}")

        if unlocked_skills:
            print("   새로 배운 스킬:")
            for skill_name in unlocked_skills:
                print(f"   - {skill_name}")

    def Get_exp(self, player, reward_exp: Optional[int] = None) -> None:
        """
        경험치 획득 처리.
        reward_exp가 없으면 랜덤 45~60.
        연속 레벨업 처리.
        """
        _initialize_skills_for_existing_level(player)

        if reward_exp is None:
            reward_exp = randint(45, 60)

        print(f"{reward_exp}의 경험치를 획득!!\n")
        player.exp += reward_exp

        while player.exp >= player.maxexp:
            print("레벨이 올랐습니다!\n")
            LV_.Lv_up(player)

# ─────────────────────────────────────────────
# 스탯 포인트 분배 적용 (★ 스탯 선택 시스템)
# ─────────────────────────────────────────────

# 스탯별 포인트 효율: SPD만 1포인트 = +0.5, 나머지 1포인트 = +1
STAT_POINT_VALUE = {
    "stg":   1.0,
    "sp":    1.0,
    "arm":   1.0,
    "sparm": 1.0,
    "spd":   0.5,   # ★ SPD는 비싸게 (추가 행동권 직결)
    "luc":   1.0,
}

# 분배 가능한 스탯 목록 (HP/MP는 자동 성장만)
ALLOCATABLE_STATS = ["stg", "sp", "arm", "sparm", "spd", "luc"]


def Allocate_Stat_Points(player, allocation: dict) -> dict:
    """
    선택 포인트를 스탯에 분배.

    allocation: {"stg": 2, "spd": 1, ...} — 각 스탯에 투입할 포인트 수
    반환: {"ok": bool, "msg": str, "remaining": int}

    규칙:
      - 총 투입 포인트 <= player.pending_points
      - SPD는 1포인트당 +0.5, 나머지는 +1
      - 음수 불가
    """
    if not hasattr(player, "pending_points"):
        player.pending_points = 0

    # 유효성 검사
    total_spent = 0
    for stat, pts in allocation.items():
        if stat not in ALLOCATABLE_STATS:
            return {"ok": False, "msg": f"분배 불가 스탯: {stat}",
                    "remaining": player.pending_points}
        if not isinstance(pts, int) or pts < 0:
            return {"ok": False, "msg": "포인트는 0 이상 정수여야 합니다",
                    "remaining": player.pending_points}
        total_spent += pts

    if total_spent > player.pending_points:
        return {"ok": False,
                "msg": f"포인트 부족 (보유 {player.pending_points}, 투입 {total_spent})",
                "remaining": player.pending_points}

    # 분배 적용
    for stat, pts in allocation.items():
        if pts > 0:
            gain = pts * STAT_POINT_VALUE[stat]
            current = getattr(player, stat, 0)
            setattr(player, stat, current + gain)

    player.pending_points -= total_spent

    return {"ok": True,
            "msg": f"{total_spent}포인트 분배 완료",
            "remaining": player.pending_points}