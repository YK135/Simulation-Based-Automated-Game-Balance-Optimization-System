# -*- coding: utf-8 -*-
"""
rogue_curve_measure.py — 도적의 구조적 우위가 어디서 오는지 분리 측정

진단(코드 확인):
  · `game/Lv.py`의 `JOB_GROWTH`에서 **도적만 2차 성장**을 한다 —
    `spd: 0.9 + lv//8` · `luc: 0.6 + lv//6`. 다른 직업의 spd는 상수(0.8/0.6/0.5)이고
    luc는 `lv % 2` / `lv % 4`로 진동할 뿐 커지지 않는다.
    실측 배수(전사 대비 SPD): Lv1 1.40배 → Lv15 1.59배 → Lv20 1.87배 → Lv25 **2.14배**.
    LUC는 Lv25에서 52.9 대 14.4(3.7배) → 크리 26.4% 대 7.2%, 회피 21.2% 대 5.8%.
  · 자동 튜너의 보정은 **SPD ≥ 14에서 +0.15로 끝나는 계단**이다
    (`ai/Simulator.PlayerPowerIndex.calc`). 도적은 **Lv1에 이미 14**라 보정이 시작부터
    포화돼 있고, SPD가 50이 돼도 같은 +0.15다.
  · 보스는 애초에 튜너를 안 거친다(`Make_MidBoss`/`Make_FinalBoss` 직접 생성).
  → 즉 "도적이 세다"가 아니라 **"도적만 레벨과 함께 벌어지는데, 그걸 따라오는 보정이 없다"**가
    정확한 진술이다. 이 스크립트는 그 두 항(SPD·LUC)을 따로 꺼서 각각 얼마인지 잰다.

팔:
  A 현재
  B SPD 평탄화 — 도적 `spd: 0.9`(lv//8 제거). 다른 직업과 같은 상수 성장.
  C LUC 평탄화 — 도적 `luc: 0.6`(lv//6 제거).
  D 둘 다 평탄화

셀은 **튜너를 거치는 쪽과 안 거치는 쪽을 나란히** 둔다 — 보정이 실제로 흡수하고 있는지 보려면
둘을 비교해야 한다. 보스(튜너 없음)와 등급 팩토리 1v1/1v3(튜너 없음)만 여기서 재고,
튜너를 거치는 전 구간은 `montecarlo.py` 스윕이 맡는다.

실행: python3 TestFile/rogue_curve_measure.py   (환경변수 N / LEVELS / JOBS / ARMS / OUT)
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아
회귀 스위트 루프에는 걸리지 않는다.
"""
import os, sys, io, random, contextlib, statistics, tempfile, subprocess

ROOT = os.environ.get("AI_RPG_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
import game.Lv as LvMod
from game import Enemy_Class as EC

SEED = 20260922
N = int(os.environ.get("N", "150"))
MAX_STEPS = 500
AI_MODE = os.environ.get("AI_MODE", "balanced")
MAIN_STAT = {"전사": "stg", "마법사": "sp", "도적": "stg"}
JOBS = [x.strip() for x in os.environ.get("JOBS", "전사,마법사,도적").split(",") if x.strip()]
ARMS = [x.strip() for x in os.environ.get("ARMS", "A,B,C,D").split(",") if x.strip()]

# 팔별로 도적의 성장식을 바꿔 끼운다 (다른 직업은 어느 팔에서도 그대로 — 대조군).
_ORIG_ROGUE = dict(LvMod.JOB_GROWTH["도적"])
ARM_CURVE = {
    "A": {},
    "B": {"spd": lambda lv: 0.9},
    "C": {"luc": lambda lv: 0.6},
    "D": {"spd": lambda lv: 0.9, "luc": lambda lv: 0.6},
}


def set_arm(arm):
    LvMod.JOB_GROWTH["도적"] = dict(_ORIG_ROGUE, **ARM_CURVE[arm])


def items_for(level):
    if level <= 5:
        return ["HP_S_potion", "HP_S_potion", "MP_S_potion"]
    if level <= 15:
        return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
    return ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


def build_player(job, level, arm):
    """★ 팔마다 새로 만든다 — 성장식이 팔의 변수이므로 캐시하면 안 된다."""
    set_arm(arm)
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: p.pending_points})
        auto_resolve_skill_choices(p, "new", rng=random.Random(f"{job}|{level}"))
    assert p.lv == level, p.lv
    return p


# 튜너를 거치지 않는 셀만 — 등급 팩토리와 보스 팩토리를 직접 부른다(결정적).
CELLS = [
    ("최종 보스", 2, lambda lv: [EC.Make_FinalBoss(lv)], True),
    ("중간 보스", 1, lambda lv: [EC.Make_MidBoss(lv)], True),
    ("골렘상", 2, lambda lv: [EC.Make_Golem(lv, "상")], False),
    ("유령상", 2, lambda lv: [EC.Make_Ghost(lv, "상")], False),
    ("고블린상x3", 1, lambda lv: [EC.Make_Goblin(lv, "상") for _ in range(3)], False),
]


def run_one(p, make_units, chapter, is_boss, seed):
    random.seed(seed)
    units = make_units(p.lv)
    items = items_for(p.lv)
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp, s.items = s.maxhp, s.maxmp, list(items)
    bs = BattleSession(s, enemies=[EntitySnapshot.from_enemy(u) for u in units],
                       items=list(items), enemy_origins=units, is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI(AI_MODE)
    p_acts = e_acts = steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            p_acts += 1
            alive = max(1, len([e for e in bs.enemies if e.hp > 0]))
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            act = {"attack": "attack", "skill": f"skill:{a.detail}",
                   "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            bs.step(act)
            bs.player.items = list(bs.items)
        else:
            e_acts += 1
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    return {
        "win": bs.winner == "player", "turns": bs.turn,
        "p_acts": p_acts, "e_acts": e_acts,
        # 행동 경제 — 적 1행동당 내 행동 수. SPD가 사는 자리가 정확히 여기다.
        "econ": p_acts / e_acts if e_acts else 0.0,
    }


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    levels = [int(x) for x in os.environ.get("LEVELS", "10,15,20,25").split(",")]
    out = []
    say = out.append
    say(f"# 도적 성장 곡선 분리 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · AI={AI_MODE}")
    say("팔 A 현재 · B SPD 평탄화(0.9) · C LUC 평탄화(0.6) · D 둘 다. 도적 외 직업은 어느 팔에서도 동일(대조군).")
    say("상대는 등급/보스 팩토리 직접 생성 — **튜너를 거치지 않는다**(도적 우위가 보정 없이 그대로 보이는 쪽).")
    say("행동경제 = 적 1행동당 플레이어 행동 수.")
    say("")

    # 스탯 표
    say("[스탯] 팔별 도적 스탯 (선택 포인트 STG 몰빵 후)")
    say(f"{'Lv':>3} {'팔':<3} {'maxHP':>6} {'STG':>6} {'SPD':>6} {'LUC':>6} {'크리%':>6} {'회피%':>6}")
    for lv in levels:
        for arm in ARMS:
            p = build_player("도적", lv, arm)
            say(f"{lv:>3} {arm:<3} {p.maxhp:>6.0f} {p.stg:>6.1f} {p.spd:>6.1f} {p.luc:>6.1f} "
                f"{min(p.luc * 0.5, 40):>5.1f}% {min(p.luc * 0.4, 25):>5.1f}%")
    say("")

    say("[본표] 승률 / 행동경제")
    say(f"{'Lv':>3} {'직업':<5} {'셀':<12} | " + " ".join(f"{a}승률 " for a in ARMS)
        + "| " + " ".join(f"{a}경제" for a in ARMS) + " | " + " ".join(f"{a}턴  " for a in ARMS))
    totals = {a: [] for a in ARMS}
    for lv in levels:
        for job in JOBS:
            players = {arm: build_player(job, lv, arm) for arm in ARMS}
            for cname, chapter, mk, is_boss in CELLS:
                res = {}
                for arm in ARMS:
                    set_arm(arm)
                    res[arm] = [run_one(players[arm], mk, chapter, is_boss,
                                        SEED * 1000 + lv * 100 + i) for i in range(N)]
                w = {a: statistics.mean(r["win"] for r in res[a]) for a in ARMS}
                if job == "도적":
                    for a in ARMS:
                        totals[a].append(w[a])
                say(f"{lv:>3} {job:<5} {cname:<12} | "
                    + " ".join(pct(w[a]) + " " for a in ARMS) + "| "
                    + " ".join(f"{statistics.mean(r['econ'] for r in res[a]):5.2f}" for a in ARMS)
                    + " | "
                    + " ".join(f"{statistics.mean(r['turns'] for r in res[a]):5.1f}" for a in ARMS))
            say("")
    say("도적 평균 승률: " + " · ".join(f"{a} {pct(statistics.mean(totals[a]))}" for a in ARMS))
    set_arm("A")
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "rogue_curve_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.remove(_db)


if __name__ == "__main__":
    main()
