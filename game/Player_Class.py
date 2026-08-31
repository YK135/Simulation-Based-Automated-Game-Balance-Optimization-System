"""
Player_Class.py
─────────────────────────────────────────────
플레이어 클래스 + 직업별 초기 스탯
"""


# ────────────────────────────────────────────
# 직업별 초기 스탯 (Lv1 기준)
# ────────────────────────────────────────────

JOB_BASE_STATS = {
    "전사": {
        "hp": 350, "mp": 30,
        "stg": 15, "sp": 4,
        "arm": 8, "sparm": 5,
        "spd": 10, "luc": 6,
    },
    "마법사": {
        "hp": 300, "mp": 65,
        "stg": 8, "sp": 14,
        "arm": 5, "sparm": 8,
        "spd": 9, "luc": 8,
    },
    "탱커": {
        "hp": 400, "mp": 25,
        "stg": 8, "sp": 2,
        "arm": 12, "sparm": 7,
        "spd": 8, "luc": 6,
    },
    "도적": {
        "hp": 290, "mp": 30,
        "stg": 11, "sp": 6,
        "arm": 4, "sparm": 3,
        "spd": 14, "luc": 12,
    },
}


class Player:
    def __init__(self, name, lv, maxexp, exp, maxhp, hp, maxmp, mp, 
                 stg, arm, sparm, sp, spd, luc, job="전사"):
        self.name = name
        self.lv = lv
        self.maxexp = maxexp
        self.exp = exp
        self.maxhp = maxhp
        self.hp = hp
        self.maxmp = maxmp
        self.mp = mp
        self.stg = stg
        self.arm = arm
        self.sparm = sparm
        self.sp = sp
        self.spd = spd
        self.luc = luc
        self.job = job
        self.skill = None
        self.atb_remainder = 0.0
        # ★ 스탯 선택 시스템: 미분배 선택 포인트
        # 레벨업 시 +3씩 쌓임. allocate_stat_points()로 소비.
        self.pending_points = 0

    # ─────────────────────────────────────────
    # 직렬화 (세션 영속화용 — Redis/DB 저장/복구)
    # ─────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name, "lv": self.lv,
            "maxexp": self.maxexp, "exp": self.exp,
            "maxhp": self.maxhp, "hp": self.hp,
            "maxmp": self.maxmp, "mp": self.mp,
            "stg": self.stg, "arm": self.arm, "sparm": self.sparm,
            "sp": self.sp, "spd": self.spd, "luc": self.luc,
            "job": self.job,
            "atb_remainder": self.atb_remainder,
            "pending_points": self.pending_points,
            "learned_skills": list(self.skill.learned_skills) if self.skill else [],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Player":
        p = cls(
            name=data["name"], lv=data["lv"],
            maxexp=data["maxexp"], exp=data["exp"],
            maxhp=data["maxhp"], hp=data["hp"],
            maxmp=data["maxmp"], mp=data["mp"],
            stg=data["stg"], arm=data["arm"], sparm=data["sparm"],
            sp=data["sp"], spd=data["spd"], luc=data["luc"],
            job=data.get("job", "전사"),
        )
        p.atb_remainder = data.get("atb_remainder", 0.0)
        p.pending_points = data.get("pending_points", 0)

        from game.Skill import Ply_Skill
        skill_sys = Ply_Skill(p.job)
        skill_sys.learned_skills = list(data.get("learned_skills", []))
        p.skill = skill_sys
        p.learned_skills = list(skill_sys.learned_skills)
        return p

    def Show_Staters(self):
        print(f"\n이  름 : {self.name}  ({self.job})")
        print(f"LV : {self.lv}         경험치 : {self.exp}/{self.maxexp}")
        print(f"HP : {int(self.hp)}/{int(self.maxhp)}")
        print(f"MP : {int(self.mp)}/{int(self.maxmp)}")
        print(f"힘   : {round(self.stg, 1)}")
        print(f"방어력 : {round(self.arm, 1)}")
        print(f"마법 방어력 : {round(self.sparm, 1)}")
        print(f"마력 : {round(self.sp, 1)}")
        print(f"스피드 : {round(self.spd, 1)}")
        print(f"행운 : {round(self.luc, 1)}\n")


def create_player_by_job(name: str, job: str) -> Player:
    """직업별 초기 스탯으로 플레이어 생성"""
    stats = JOB_BASE_STATS.get(job, JOB_BASE_STATS["전사"])
    
    return Player(
        name=name,
        lv=1,
        maxexp=100,
        exp=0,
        maxhp=stats["hp"],
        hp=stats["hp"],
        maxmp=stats["mp"],
        mp=stats["mp"],
        stg=stats["stg"],
        arm=stats["arm"],
        sparm=stats["sparm"],
        sp=stats["sp"],
        spd=stats["spd"],
        luc=stats["luc"],
        job=job,
    )