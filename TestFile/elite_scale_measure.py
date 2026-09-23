# -*- coding: utf-8 -*-
"""
elite_scale_measure.py — 엘리트 노드에 12차와 같은 처방(튜너 우회 + 배율)을 적용할지 측정

12차에서 일반 다대일을 고친 뒤 **엘리트가 게임에서 가장 나쁜 칸**이 됐다 —
전 구간 스윕(N=200/셀)에서 3/18칸만 밴드 안, Lv5~25가 20~37%다.

원인은 일반 다대일과 **같은 범주 오류에 하나가 더 얹힌 것**이다:
  · 리더도 동료도 `hook.get_enemy(difficulty="hard")` — **1v1이 약 55%가 되도록**
    튜닝된 몬스터다.
  · 거기에 **리더는 패턴을 더 갖는다**(EliteKit). 즉 같은 스탯에 능력이 추가된다.
  · 2마리일 때 보정은 `ELITE_STAT_SCALE[2] = 0.90` 할인뿐이다.
  → 단독이어도 "55% 상대 + 패턴"이라 55% 아래로 내려가고, 2마리면 일반 다대일과
    똑같이 무너진다.

이 스크립트는 `_make_elite_encounter()`를 **그대로 쓰되** hook의 `get_enemy`만
등급 팩토리로 바꿔 끼워, 패턴·플래그·빙결 갑옷 같은 엘리트 고유 로직을 하나도
건드리지 않고 "튜너 ON/OFF × 배율"만 비교한다.

실행: python3 TestFile/elite_scale_measure.py   (환경변수 N / LEVELS / JOBS / SCALES / OUT)
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아
회귀 스위트 루프에는 걸리지 않는다.
"""
import os, sys, io, copy, random, contextlib, statistics, tempfile, subprocess
from collections import Counter

ROOT = os.environ.get("AI_RPG_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot
from core.Balance_Hook import BalanceHook
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
import app.Map as M

SEED = 20260926
N = int(os.environ.get("N", "120"))
LEVELS = [int(x) for x in os.environ.get("LEVELS", "5,10,15,20,25").split(",")]
JOBS = [x.strip() for x in os.environ.get("JOBS", "전사,마법사,도적").split(",") if x.strip()]
SCALES = [float(x) for x in os.environ.get("SCALES", "1.0,1.2,1.4,1.6").split(",")]
# HYBRID=1 — 단독은 튜너 유지, 2마리만 등급+배율 (채택 후보의 실제 동작)
HYBRID = os.environ.get("HYBRID", "0") == "1"
MAIN = {"전사": "stg", "마법사": "sp", "도적": "stg"}
MAX_STEPS = 600


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


def build(job, lv):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        l = LV_(p); g = 0
        while p.lv < lv and g < 300:
            l.Get_exp(p, reward_exp=p.maxexp); g += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {MAIN[job]: p.pending_points})
        auto_resolve_skill_choices(p, "new", rng=random.Random(f"{job}|{lv}"))
    return p


class _GradedHook:
    """진짜 hook을 감싸 get_enemy만 등급 팩토리로 바꾼다 — 나머지는 그대로 위임."""
    def __init__(self, hook):
        self._h = hook

    def get_enemy(self, enemy_type, difficulty=None, chapter=1):
        grade = {"easy": "하", "normal": "중"}.get(difficulty, "상")
        return self._h.make_graded_enemy(enemy_type, grade)

    def __getattr__(self, name):
        return getattr(self._h, name)


def run_one(p, hook, chapter, scale, seed, real_hook=None):
    """real_hook을 주면 **하이브리드**로 돈다 — 단독 엘리트는 튜너 그대로, 2마리만
    등급 팩토리 + 배율. 측정 결과 단독은 이미 밴드 안(47.7~69.6%)이라 건드리면 안 된다.
    같은 시드로 두 번 부르면 구성(리더 타입·동료 유무)이 같으므로 되돌려 만들 수 있다."""
    random.seed(seed)
    layer = random.randint(1, 8)
    units, _grades = M._make_elite_encounter(real_hook or hook, chapter, layer=layer)
    n_e = len(units)
    if real_hook is not None and n_e > 1:
        random.seed(seed)
        layer2 = random.randint(1, 8)
        assert layer2 == layer
        units, _grades = M._make_elite_encounter(hook, chapter, layer=layer)
        n_e = len(units)
    # ★ 단독 엘리트에도 배율을 건다 — 엘리트의 배율은 "마릿수 보정"이 아니라
    #   **패턴 보정**이기 때문이다. 단독이어도 "1v1 55% 상대 + 패턴"이라
    #   기준선 아래로 내려간다. 그래서 n=1과 n=2를 나눠 잰다.
    if scale != 1.0 and (real_hook is None or n_e > 1):
        M._apply_stat_scale(units, scale)
    items = items_for(p.lv)
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp, s.items = s.maxhp, s.maxmp, list(items)
    snaps = [u if isinstance(u, EntitySnapshot) else EntitySnapshot.from_enemy(u) for u in units]
    bs = BattleSession(s, enemies=snaps, items=list(items), enemy_origins=units, is_boss=False)
    bs.battle_meta = {"source": "ai", "battle_type": "elite", "chapter": chapter}
    ai = PlayerAI("balanced")
    steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            alive = max(1, len([e for e in bs.enemies if e.hp > 0]))
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            bs.step({"attack": "attack", "skill": f"skill:{a.detail}",
                     "item": f"item:{a.detail}"}.get(a.action_type, "attack"))
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    return bs.winner == "player", n_e


def main():
    out = []
    say = out.append
    say(f"# 엘리트 배율 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · balanced")
    say("`_make_elite_encounter()`를 그대로 쓰고 hook의 get_enemy만 갈아 끼운다 — 패턴·플래그는 불변.")
    say("튜너 = 현재(하드 튜닝 몬스터). 등급 = 12차 처방(등급 팩토리 「상」).")
    say("배율은 단독에도 적용한다 — 엘리트의 배율은 마릿수 보정이 아니라 **패턴 보정**이다.")
    say("단독/2마리를 나눠 적는다(괄호 안이 표본 수).")
    say("밴드 45~88%, * = 밴드 안." + ("  [HYBRID: 단독은 튜너 유지]" if HYBRID else ""))
    say("")
    say(f"{'Lv':>3} {'직업':<5} {'구성':<5} | {'튜너(현재)':>10} | " +
        " ".join(f"{'등급 x' + format(sc, '.1f'):>10}" for sc in SCALES) + f" | {'표본':>5}")
    band = {("튜너", 0.0): [0, 0]}
    for sc in SCALES:
        band[("등급", sc)] = [0, 0]
    for lv in LEVELS:
        chapter = 1 if lv < 8 else 2
        for job in JOBS:
            p = build(job, lv)
            with contextlib.redirect_stdout(io.StringIO()):
                real = BalanceHook(p, items_for(lv), show_graph=False,
                                   verbose=False, auto_prewarm=False)
                # 폴백을 피해 이 챕터 엘리트 풀 전체를 미리 튜닝해 둔다
                pool = set(M.ELITE_CHAPTER_POOL.get(chapter, [])) | set(
                    sum((M.CHAPTER_TIER_POOL.get((chapter, t), []) for t in ("early", "mid", "late")), []))
                for et in pool:
                    real._start_background_sim(et, chapter)
                for et in pool:
                    ev = real._sim_ready.get((et, chapter))
                    if ev:
                        ev.wait(900)
            graded = _GradedHook(real)

            def _bucket(hook, scale, hybrid=False):
                """(전체, {마릿수: (승률, 표본수)})"""
                res = [run_one(p, hook, chapter, scale, SEED * 1000 + lv * 100 + i,
                               real_hook=real if hybrid else None)
                       for i in range(N)]
                by = {}
                for ne in (1, 2):
                    sub = [w for w, n_ in res if n_ == ne]
                    if sub:
                        by[ne] = (statistics.mean(sub), len(sub))
                return statistics.mean(w for w, _ in res), by

            t_all, t_by = _bucket(real, 1.0)
            g = {sc: _bucket(graded, sc, hybrid=HYBRID) for sc in SCALES}

            for ne, label in ((1, "단독"), (2, "2마리")):
                if ne not in t_by:
                    continue
                tw, tn = t_by[ne]
                band[("튜너", 0.0)][1] += 1
                band[("튜너", 0.0)][0] += 0.45 <= tw <= 0.88
                cells = []
                for sc in SCALES:
                    gw = g[sc][1].get(ne, (float("nan"), 0))[0]
                    cells.append(gw)
                    band[("등급", sc)][1] += 1
                    band[("등급", sc)][0] += 0.45 <= gw <= 0.88
                say(f"{lv:>3} {job:<5} {label:<5} | {100*tw:9.1f}%" +
                    ("*" if 0.45 <= tw <= 0.88 else " ") + "| " +
                    " ".join(f"{100*w:9.1f}%" + ("*" if 0.45 <= w <= 0.88 else " ")
                             for w in cells) + f" | {tn:5d}")
        say("")
    say("밴드 안 칸 수: " + " · ".join(
        f"{k[0]}{'' if k[0]=='튜너' else ' x'+format(k[1],'.1f')} {v[0]}/{v[1]}"
        for k, v in band.items()))
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "elite_scale_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.remove(_db)


if __name__ == "__main__":
    main()
