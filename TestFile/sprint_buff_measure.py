# -*- coding: utf-8 -*-
"""
sprint_buff_measure.py — 도적 「추진력」의 재시전 트레드밀 측정

"도적의 구조적 우위"를 성장 곡선에서 찾다가 나온 결과다. 실제로 일어나는 일:

  · `PlayerAI.decide`는 **`내 실효 SPD ≥ 상대 실효 SPD`일 때** SPD 버프를 건다
    (`ai/Auto_AI.py`의 버프 분기). 즉 **빠를수록 더 확실하게** 이 분기에 들어간다.
  · 「추진력」은 `buff_turns: 2`인데, 버프는 **시전 행동에서 1턴이 줄기 때문에**
    실제로 덮는 행동이 **1회뿐**이다. 걸고 → 한 번 쓰고 → 끝. 그래서 도적은
    "걸고 한 대 치고 다시 걸고"를 반복한다.
  · 실측(Lv20 balanced): 골렘상 전투에서 11.1행동 중 **4.87행동이 추진력**(44%),
    최종 보스에서 19.1행동 중 5.46행동. 이 행동들은 피해가 0이다.

성장 곡선이 범인이 아니라는 것도 같은 측정에서 나왔다 — SPD 성장을 평탄화한 팔보다
**곡선은 그대로 두고 추진력만 뺀 팔이 더 세다**(Lv20 최종 보스 90.7% vs **94.0%**).
평탄화가 이겨 보였던 이유는 도적의 SPD가 최종 보스(34) 아래로 내려가 위 조건이
꺼졌기 때문이지, 느려서가 아니다.

그래서 이 스크립트는 **AI를 건드리지 않고**(기본 balanced 점수는 불변 규칙) 6차에서
흡혈 버프에 썼던 것과 같은 레버, **지속**을 시험한다.

팔: 2턴(현재) · 4턴 · 6턴 · 8턴 · 제거(상한 — 이 스킬이 없는 도적)

실행: python3 TestFile/sprint_buff_measure.py   (환경변수 N / LEVELS / OUT)
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
from ai.battle import EntitySnapshot, SKILL_META
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
from game import Enemy_Class as EC

SEED = 20260922
N = int(os.environ.get("N", "150"))
MAX_STEPS = 600
SKILL = "추진력"
ARMS = [x.strip() for x in os.environ.get("ARMS", "2,4,6,8,off").split(",") if x.strip()]
LEVELS = [int(x) for x in os.environ.get("LEVELS", "10,15,20,25").split(",")]

CELLS = [
    ("최종 보스", 2, lambda lv: [EC.Make_FinalBoss(lv)], True),
    ("중간 보스", 1, lambda lv: [EC.Make_MidBoss(lv)], True),
    ("골렘상", 2, lambda lv: [EC.Make_Golem(lv, "상")], False),
    ("유령상", 2, lambda lv: [EC.Make_Ghost(lv, "상")], False),
    ("고블린상x3", 1, lambda lv: [EC.Make_Goblin(lv, "상") for _ in range(3)], False),
]


def items_for(level):
    if level <= 15:
        return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
    return ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


_PLAYERS = {}
def build_player(level):
    if level in _PLAYERS:
        return _PLAYERS[level]
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", "도적")
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {"stg": p.pending_points})
        auto_resolve_skill_choices(p, "new", rng=random.Random(f"도적|{level}"))
    assert p.lv == level, p.lv
    _PLAYERS[level] = p
    return p


def run_one(p, arm, mk, chapter, is_boss, seed):
    # 지속은 이 프로세스의 SKILL_META만 덮어쓴다(측정 전용). "off"는 스킬 자체를 뺀다.
    if arm != "off":
        SKILL_META[SKILL]["buff_turns"] = int(arm)
    random.seed(seed)
    units = mk(p.lv)
    items = items_for(p.lv)
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp, s.items = s.maxhp, s.maxmp, list(items)
    if arm == "off":
        s.learned_skills = [k for k in s.learned_skills if k != SKILL]
    bs = BattleSession(s, enemies=[EntitySnapshot.from_enemy(u) for u in units],
                       items=list(items), enemy_origins=units, is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI("balanced")
    pa = steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            pa += 1
            alive = max(1, len([e for e in bs.enemies if e.hp > 0]))
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            act = {"attack": "attack", "skill": f"skill:{a.detail}",
                   "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            bs.step(act)
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    casts = sum(1 for lg in bs.logs
                if lg.actor == "player" and (lg.action_detail or "").startswith(SKILL))
    return {"win": bs.winner == "player", "turns": bs.turn, "acts": pa, "casts": casts,
            "waste": casts / pa if pa else 0.0}


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    orig_turns = SKILL_META[SKILL]["buff_turns"]
    out = []
    say = out.append
    say(f"# 「추진력」 지속 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · AI=balanced(기본)")
    say(f"현재 지속 {orig_turns}턴 — 버프는 시전 행동에서 1턴이 줄므로 실제로 덮는 행동은 {orig_turns - 1}회다.")
    say("팔: 지속 2(현재)/4/6/8턴 · off(스킬 제거 = 낭비 0의 상한).")
    say("낭비 = 추진력 시전 / 전체 플레이어 행동. 이 행동들의 피해는 0이다.")
    say("")
    say(f"{'Lv':>3} {'셀':<12} | " + " ".join(f"{a:>4}승률" for a in ARMS)
        + " | " + " ".join(f"{a:>4}시전" for a in ARMS)
        + " | " + " ".join(f"{a:>4}낭비" for a in ARMS)
        + " | " + " ".join(f"{a:>4}행동" for a in ARMS))
    totals = {a: [] for a in ARMS}
    try:
        for lv in LEVELS:
            p = build_player(lv)
            if SKILL not in EntitySnapshot.from_player(p).learned_skills:
                say(f"{lv:>3}  (미보유)")
                continue
            for cname, chapter, mk, is_boss in CELLS:
                res = {a: [run_one(p, a, mk, chapter, is_boss, SEED * 1000 + lv * 100 + i)
                           for i in range(N)] for a in ARMS}
                w = {a: statistics.mean(r["win"] for r in res[a]) for a in ARMS}
                for a in ARMS:
                    totals[a].append(w[a])
                say(f"{lv:>3} {cname:<12} | " + " ".join(pct(w[a]) for a in ARMS) + " | "
                    + " ".join(f"{statistics.mean(r['casts'] for r in res[a]):8.2f}" for a in ARMS)
                    + " | "
                    + " ".join(f"{100 * statistics.mean(r['waste'] for r in res[a]):7.1f}%" for a in ARMS)
                    + " | "
                    + " ".join(f"{statistics.mean(r['acts'] for r in res[a]):8.1f}" for a in ARMS))
            say("")
        say("평균 승률: " + " · ".join(f"{a}턴 {pct(statistics.mean(totals[a]))}" for a in ARMS))
    finally:
        SKILL_META[SKILL]["buff_turns"] = orig_turns
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "sprint_buff_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.remove(_db)


if __name__ == "__main__":
    main()
