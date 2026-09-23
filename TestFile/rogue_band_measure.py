# -*- coding: utf-8 -*-
"""
rogue_band_measure.py — 도적 고레벨 구간을 밴드 안으로 되돌릴 레버 비교

전제(후속 4단계 `c40ee91` 이후):
  「추진력」의 0딜 재시전을 걷어내고 나니 도적의 실제 위치가 처음으로 보였다. **Lv20 최종 보스
  90.0~96.5%** (전사 32~64% · 마법사 54.5~77.5%) — 보스 밴드 상한 90%를 넘는다.
  반면 같은 레벨의 1v2 38.3% · elite 40.8%는 이미 하한(45%) 아래다. **깎을 곳과 깎으면 안 될 곳이
  한 직업 안에 같이 있다.**

진단(이 스크립트를 쓰기 전에 실측으로 확인한 것):
  · Lv20 보스전 피해 분해 — 도적은 2480피해를 **12.9행동**에, 전사는 2364피해를 **19.4행동**에 넣는다.
    총피해는 거의 같다. 도적이 이기는 이유는 화력이 아니라 **전투를 2/3로 압축**하기 때문이다.
  · 그 압축의 63%가 스킬 하나다 — **「연속찌르기」 5.50시전 / 1562피해**.
  · 「연속찌르기」는 게임에서 **유일한 `multi_hit`** 스킬이고(도적 Lv5 해금), 타수가
    `max(5, min(85, luc*3 - i*20))`로 **LUC가 정한다**(`ai/battle/Skills.py:roll_multi_hit_count`).
    기대 배율 Lv5 1.07 → Lv15 1.73 → **Lv20 2.20** → Lv25 2.24(포화). 레벨만으로 2배가 된다.
  · LUC는 **도적만 자란다**(`0.6 + lv//6`; 전사 `lv%2` · 마법사 `lv%4`는 진동만 한다).
  · 그리고 `PlayerPowerIndex.calc`의 **지수는 LUC로 움직이지 않는다** — `_skill_expected_dmg`가
    `multi_hit` 기대 타수를 `min(2.0 + luc*0.05, max_hits)`로 추정하긴 하는데, `calc()`가 그 값을
    `skill_power > 0` 한 줄로만 써서 크기를 버린다(LUC 38.9와 30.5의 지수가 똑같이 1.79).
    ※ 다만 **튜너 자체는 측정 승률로 이진탐색을 돌아** 도적이 약해지면 몬스터도 내려간다 —
      실측 폭은 LUC −22%에 몬스터 HP 0 ~ −4.6%로 작다. 보스는 튜너를 아예 안 거친다.
  → 즉 도적의 미보정 성장축은 SPD가 아니라 **LUC → 연속찌르기 타수**다.

레버가 갈리는 지점: 「연속찌르기」는 **단일 대상**이다. 다대일에서는 balanced가 `aoe`인 「난사1」을
고른다. 그래서 이 스킬을 깎으면 **보스·1v1(밴드 위)만 내려가고 1v2/1v3/elite(밴드 아래)는 거의
안 건드린다.** 곡선(LUC/SPD)을 깎으면 전부 같이 내려간다. 이 스크립트는 그 차이를 실측한다.

팔:
  A 현재
  B 연속찌르기 dmg_decay 0.68 → 0.58   (타수는 그대로, 2타 이후 피해만)
  C 연속찌르기 prob_decay 20 → 32      (타수 자체를 줄임 — LUC 의존을 낮춘다)
  D 연속찌르기 max_hits 4 → 3          (상한을 내림)
  E LUC 성장 상한 `0.6 + min(lv//6, 1)`  (Lv12부터 증가분 동결 — 곡선 레버, 대조군)
  F SPD 성장 상한 `0.9 + min(lv//8, 1)`  (Lv16부터 증가분 동결 — 곡선 레버, 대조군)

실행: python3 TestFile/rogue_band_measure.py   (환경변수 N / LEVELS / ARMS / JOBS / OUT)
상대는 등급·보스 팩토리 직접 생성이라 **튜너를 안 거친다**(결정적). 채택 후보는 반드시
montecarlo.py 스윕으로 실전 경로에서 다시 확인한다.
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아
회귀 스위트 루프에는 걸리지 않는다.
"""
import os, sys, io, random, contextlib, statistics, tempfile, subprocess
from collections import Counter

ROOT = os.environ.get("AI_RPG_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI
from ai.battle import EntitySnapshot, SKILL_META
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
import game.Lv as LvMod
from game import Enemy_Class as EC
from app.Map import (STAT_SCALE, NORMAL_GRADE_POOL, NORMAL_GRADE_3,
                     _early_game_multi_scale, _apply_stat_scale)

SEED = 20260923
N = int(os.environ.get("N", "150"))
MAX_STEPS = 600
SKILL = "연속찌르기"
JOBS = [x.strip() for x in os.environ.get("JOBS", "도적").split(",") if x.strip()]
ARMS = [x.strip() for x in os.environ.get("ARMS", "A,B,C,D,E,F").split(",") if x.strip()]
LEVELS = [int(x) for x in os.environ.get("LEVELS", "5,10,15,20,25").split(",")]
MAIN_STAT = {"전사": "stg", "마법사": "sp", "도적": "stg"}

_ORIG_SKILL = dict(SKILL_META[SKILL])
_ORIG_GROWTH = {j: dict(v) for j, v in LvMod.JOB_GROWTH.items()}

# 팔 = (스킬 메타 덮어쓰기, 도적 성장식 덮어쓰기)
ARM_SPEC = {
    "A": ({}, {}),
    "B": ({"dmg_decay": 0.58}, {}),
    "C": ({"prob_decay": 32}, {}),
    "D": ({"max_hits": 3}, {}),
    "E": ({}, {"luc": lambda lv: 0.6 + min(lv // 6, 1)}),
    "F": ({}, {"spd": lambda lv: 0.9 + min(lv // 8, 1)}),
}

def _multi(lv, n):
    """다대일은 실전과 같은 구성·보정을 쓴다.

    ★ 등급을 실전 풀에서 뽑는다 — 처음엔 세 칸 모두 「상」으로 고정했다가 3마리 칸이
      전 팔 0~2.7%로 바닥에 붙었는데, `app/Map.py`는 **3마리 노드에서 「상」을 금지**한다
      (`NORMAL_GRADE_3` = 하/중). 실전에 없는 조합으로 레버를 판정할 뻔했다.
    보정도 실전과 같다(STAT_SCALE × _early_game_multi_scale). 등급 추첨은 `run_one`이
    전투 시드를 심은 직후에 일어나므로 같은 전투 번호면 모든 팔에서 같은 구성이 나온다."""
    pool = NORMAL_GRADE_3 if n == 3 else NORMAL_GRADE_POOL
    grades = random.choices(list(pool), weights=list(pool.values()), k=n)
    units = [EC.Make_Goblin(lv, g) for g in grades]
    _apply_stat_scale(units, STAT_SCALE[n] * _early_game_multi_scale(lv))
    return units


# (이름, 챕터, 팩토리, 보스여부, 이 셀을 재는 레벨) — 만나지도 않는 칸은 아예 안 돈다
CELLS = [
    ("최종 보스", 2, lambda lv: [EC.Make_FinalBoss(lv)], True, {20, 25}),
    ("중간 보스", 1, lambda lv: [EC.Make_MidBoss(lv)], True, {8, 10}),
    ("골렘상", 2, lambda lv: [EC.Make_Golem(lv, "상")], False, {10, 15, 20, 25}),
    ("유령상", 2, lambda lv: [EC.Make_Ghost(lv, "상")], False, {10, 15, 20, 25}),
    ("고블린x2(실전)", 1, lambda lv: _multi(lv, 2), False, {5, 10, 15, 20, 25}),
    ("고블린x3(실전)", 1, lambda lv: _multi(lv, 3), False, {5, 10, 15, 20, 25}),
]


def set_arm(arm):
    """스킬 메타와 성장식을 이 프로세스에서만 갈아 끼운다(측정 전용)."""
    smeta, growth = ARM_SPEC[arm]
    SKILL_META[SKILL].clear(); SKILL_META[SKILL].update(_ORIG_SKILL); SKILL_META[SKILL].update(smeta)
    for job, base in _ORIG_GROWTH.items():
        LvMod.JOB_GROWTH[job] = dict(base, **(growth if job == "도적" else {}))


def restore():
    SKILL_META[SKILL].clear(); SKILL_META[SKILL].update(_ORIG_SKILL)
    for job, base in _ORIG_GROWTH.items():
        LvMod.JOB_GROWTH[job] = dict(base)


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


_PLAYERS = {}
def build_player(job, level, arm):
    """성장식이 변수인 팔(E/F)이 있으므로 캐시 키에 팔을 넣는다."""
    curve_key = arm if ARM_SPEC[arm][1] else "-"
    key = (job, level, curve_key)
    if key in _PLAYERS:
        return _PLAYERS[key]
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
    _PLAYERS[key] = p
    return p


def run_one(p, mk, chapter, is_boss, seed):
    random.seed(seed)
    units = mk(p.lv)
    items = items_for(p.lv)
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp, s.items = s.maxhp, s.maxmp, list(items)
    bs = BattleSession(s, enemies=[EntitySnapshot.from_enemy(u) for u in units],
                       items=list(items), enemy_origins=units, is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI("balanced")
    acts = steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            acts += 1
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
    casts = tot = mine = 0
    for lg in bs.logs:
        if lg.actor != "player":
            continue
        d = lg.damage_dealt or 0
        tot += d
        if (lg.action_detail or "").startswith(SKILL):
            casts += 1
            mine += d
    return {"win": bs.winner == "player", "turns": bs.turn, "acts": acts,
            "casts": casts, "share": mine / tot if tot else 0.0}


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    out = []
    say = out.append
    say(f"# 도적 밴드 복귀 레버 비교 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · AI=balanced(기본)")
    say("팔 A 현재 · B 연속찌르기 dmg_decay 0.58 · C prob_decay 32 · D max_hits 3 "
        "· E LUC 상한(Lv12~) · F SPD 상한(Lv16~)")
    say("B/C/D는 단일 대상 스킬 하나만, E/F는 성장 곡선 전체를 건드린다 — 다대일 칸에서 갈린다.")
    say("밴드: 일반 45~88% · 보스 45~90%. 시전 = 연속찌르기 시전/전투, 비중 = 그 스킬이 낸 피해 비율.")
    say("")
    head = (f"{'Lv':>3} {'셀':<12} | " + " ".join(f"{a}승률 " for a in ARMS)
            + "| " + " ".join(f"{a}시전" for a in ARMS)
            + " | " + " ".join(f"{a}턴  " for a in ARMS))
    try:
        for job in JOBS:
            say(f"[{job}]")
            say(head)
            band = {a: [] for a in ARMS}
            for lv in LEVELS:
                for cname, chapter, mk, is_boss, lv_set in CELLS:
                    if lv not in lv_set:
                        continue
                    res = {}
                    for arm in ARMS:
                        set_arm(arm)
                        pl = build_player(job, lv, arm)
                        set_arm(arm)   # build_player가 팔을 바꿔 놓을 수 있다
                        res[arm] = [run_one(pl, mk, chapter, is_boss,
                                            SEED * 1000 + lv * 100 + i) for i in range(N)]
                    w = {a: statistics.mean(r["win"] for r in res[a]) for a in ARMS}
                    lo, hi = (0.45, 0.90) if is_boss else (0.45, 0.88)
                    for a in ARMS:
                        band[a].append(lo <= w[a] <= hi)
                    say(f"{lv:>3} {cname:<12} | " + " ".join(pct(w[a]) + " " for a in ARMS) + "| "
                        + " ".join(f"{statistics.mean(r['casts'] for r in res[a]):5.2f}" for a in ARMS)
                        + " | "
                        + " ".join(f"{statistics.mean(r['turns'] for r in res[a]):5.1f}" for a in ARMS))
                say("")
            say("밴드 안 칸 수: " + " · ".join(
                f"{a} {sum(band[a])}/{len(band[a])}" for a in ARMS))
            say("")
    finally:
        restore()
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "rogue_band_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.remove(_db)


if __name__ == "__main__":
    main()
