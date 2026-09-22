# -*- coding: utf-8 -*-
"""
final_boss_measure.py — 최종 보스 4페이즈 측정 (Combat Content Brief 4장 · 11-1 「1차의 판정 기준」 · 2차 8번)

boss_measure.py(중간 보스)와 같은 원칙: 승률 하나로 판정하지 않고, 도달 페이즈 · 패배 시 보스 잔여 HP ·
「종언」으로 죽은 비율 · 손아귀 1회 피해 · 그림자 처치 · 자원 소비를 같이 본다. balanced(튜닝 기준)와
reactive(예고·신규 스킬 사용 규칙이 있는 측정용 AI)를 나란히 잰다.

트리에 무관하게 돌아가도록 페이즈는 보스 HP 비율(70/40/15%)로 계산하고, 종언·손아귀는 TurnLog의
action_detail("종언" / "심연의 손아귀")로 센다 — 패턴이 없던 트리(cd516e6)에 대고 돌리면 「패턴 전」 비교가 된다.

입력: montecarlo.py와 같은 플레이어(Lv1→목표 레벨 Lv_up, 선택 포인트 주 스탯, 2택 1은 SKILL_PICK),
아이템 HP_L + HP_M + MP_L + MP_M(montecarlo.py의 Lv16+ 구성). 세션 items와 AI 스냅샷을 매 step 맞춘다
(boss_measure.py와 같은 방식 — AI가 없는 포션을 고르지 않게).
대상: 그림자가 살아 있으면 HP가 가장 낮은 그림자부터(montecarlo.py pick_target과 같은 규칙).

실행:  python3 TestFile/final_boss_measure.py     (N=200, LEVELS="20,25", SKILL_PICK=new 기본)
       AI_RPG_ROOT=<다른 트리> TREE_LABEL=<커밋> OUT=<파일> python3 TestFile/final_boss_measure.py
       ★ 다른 트리를 잴 때는 AI_RPG_ROOT가 필수다 — 없으면 이 스크립트 파일이 있는 트리의 코드를 불러온다.
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아 회귀 스위트에 안 걸린다.
"""
import os, sys, io, tempfile, random, contextlib, subprocess, statistics
from collections import Counter

ROOT = os.environ.get("AI_RPG_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db
sys.path.insert(0, ROOT)

from game.Player_Class import create_player_by_job          # noqa: E402
from game.Lv import LV_, Allocate_Stat_Points               # noqa: E402
from game.Enemy_Class import Make_FinalBoss                 # noqa: E402
from ai.Battlesession import BattleSession                  # noqa: E402
from ai.Auto_AI import PlayerAI                             # noqa: E402
from ai.battle import EntitySnapshot                        # noqa: E402
try:
    from game.Lv import auto_resolve_skill_choices          # noqa: E402
except ImportError:                                         # 2택 1이 없던 트리
    auto_resolve_skill_choices = None
import _measure_relics as MR                                # noqa: E402  (같은 TestFile/ 안)

SEED = 20260917
N = int(os.environ.get("N", "200"))
LEVELS = [int(x) for x in os.environ.get("LEVELS", "20,25").split(",")]
SKILL_PICK = os.environ.get("SKILL_PICK", "new")
JOBS = tuple(x.strip() for x in os.environ.get("JOBS", "전사,마법사,도적").split(",") if x.strip())
MODES = ("balanced", "reactive")
MAIN_STAT = {"전사": "stg", "마법사": "sp", "도적": "stg"}
ITEMS = ["HP_L_potion", "HP_M_potion", "MP_L_potion", "MP_M_potion"]
# 들고 들어가는 유물 — 세미콜론으로 여러 조합을 한 번에 잰다. 기본 "none"은 예전과 같은 출력.
#   예: RELICS="none;2;4;6"  ·  RELICS="none;relic_priest_remains"
RELIC_SPECS = [x.strip() for x in os.environ.get("RELICS", "none").split(";") if x.strip()]
MAX_STEPS = 600
SHADOW = "심연의 그림자"


def git_rev():
    """측정한 트리 표시 — git 밖에서(git archive로 꺼낸 트리) 돌릴 때는 TREE_LABEL로 적어 준다."""
    if os.environ.get("TREE_LABEL"):
        return os.environ["TREE_LABEL"]
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


def build_player(job, level):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        pts = getattr(p, "pending_points", 0)
        if pts > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: pts})
        if auto_resolve_skill_choices is not None:
            auto_resolve_skill_choices(p, SKILL_PICK, rng=random.Random(f"{job}|{level}"))
    return p


def phase_of(ratio):
    return 4 if ratio <= 0.15 else 3 if ratio <= 0.40 else 2 if ratio <= 0.70 else 1


def pick_target(bs):
    shadows = [(e.hp, i) for i, e in enumerate(bs.enemies) if e.hp > 0 and e.enemy_type == SHADOW]
    return min(shadows)[1] if shadows else None


def run_one(p, mode, seed, relic_spec="none"):
    # 유물 추첨은 전용 RNG로 — 전역 난수열을 건드리면 유물 없는 팔과 비교가 어긋난다.
    relics = MR.draw(relic_spec, p.job, random.Random(seed ^ 0x5EED))
    items = MR.items_for(relics, ITEMS)
    random.seed(seed)
    unit = Make_FinalBoss(p.lv)
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp, s.items = s.maxhp, s.maxmp, list(items)
    MR.apply_to_snapshot(s, relics)        # relics · 굶주린 칼날 maxHP 대가
    s.hp = min(s.hp, s.maxhp)
    bs = BattleSession(s, enemy=EntitySnapshot.from_enemy(unit), items=list(items),
                       enemy_origins=[unit], is_boss=True)
    bs.battle_meta = {"source": "ai", "battle_type": "final_boss", "chapter": 2}
    ai = PlayerAI(mode)
    boss = bs.enemies[0]
    r = {"win": False, "turns": 0, "min_ratio": 1.0, "doom": 0, "doom_death": False,
         "grasp": [], "shadow_kills": 0, "potions": 0, "mp_left": 0.0, "boss_left": 0.0}
    steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        n_logs = len(bs.logs)
        shadows_alive = sum(1 for e in bs.enemies if e.enemy_type == SHADOW and e.hp > 0)
        if na == "player":
            ti = pick_target(bs)
            tgt = bs.enemies[ti] if ti is not None else (bs._current_target() or bs.enemy)
            alive = sum(1 for e in bs.enemies if e.hp > 0)
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            act = {"attack": "attack", "skill": f"skill:{a.detail}",
                   "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            if ti is not None and a.action_type in ("attack", "skill"):
                act = f"attack:{ti}" if a.action_type == "attack" else f"{act}:{ti}"
            if act.startswith("item:HP"):
                r["potions"] += 1
            bs.step(act)
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
        r["shadow_kills"] += max(0, shadows_alive - sum(1 for e in bs.enemies if e.enemy_type == SHADOW and e.hp > 0))
        for lg in bs.logs[n_logs:]:
            if lg.actor != "enemy":
                continue
            if lg.action_detail == "종언":
                r["doom"] += 1
                if bs.done and bs.winner == "enemy":
                    r["doom_death"] = True
            elif lg.action_detail == "심연의 손아귀" and not lg.is_dodge:
                r["grasp"].append(lg.damage_dealt)
        r["min_ratio"] = min(r["min_ratio"], max(0.0, boss.hp) / boss.maxhp)
    if not bs.done:
        bs.winner = "enemy"
    r["win"] = bs.winner == "player"
    r["turns"] = bs.turn
    r["boss_left"] = max(0.0, boss.hp) / boss.maxhp
    r["mp_left"] = bs.player.mp / max(1.0, bs.player.maxmp)
    return r


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    out = []
    say = out.append
    say(f"# 최종 보스 측정 — 트리 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · 2택1 {SKILL_PICK}")
    say("입력: Lv1→목표 Lv_up, 선택 포인트 주 스탯, 아이템 HP_L+HP_M+MP_L+MP_M. 대상: 그림자 먼저.")
    say("도달 = 보스 HP 기준 페이즈(70/40/15%). 종언 사망 = 「종언」 직후 패배. 손아귀 = 명중 1회 피해(실드 전).")
    say("")
    say(f"{'Lv':>3} {'직업':<4} {'AI':<9} {'유물':<13} {'승률':>6} {'턴':>5} {'P2+':>6} {'P3+':>6} {'P4':>6} "
        f"{'패배 시 보스HP':>12} {'종언 사망':>8} {'종언/전투':>8} {'손아귀':>6} {'그림자 처치':>9} {'포션':>5} {'남은 MP':>7}")
    for lv in LEVELS:
        for job in JOBS:
            p = build_player(job, lv)
            for mode in MODES:
                for spec in RELIC_SPECS:
                    rows = [run_one(p, mode, SEED * 1000 + lv * 37 + i, spec) for i in range(N)]
                    win = statistics.mean(x["win"] for x in rows)
                    ph = Counter(phase_of(x["min_ratio"]) for x in rows)
                    reach = lambda k: sum(v for kk, v in ph.items() if kk >= k) / N
                    losses = [x for x in rows if not x["win"]]
                    bl = statistics.mean(x["boss_left"] for x in losses) if losses else 0.0
                    dd = sum(x["doom_death"] for x in rows) / N
                    grasp = [g for x in rows for g in x["grasp"]]
                    say(f"{lv:>3} {job:<4} {mode:<9} {MR.label(spec):<13} {pct(win):>6} {statistics.mean(x['turns'] for x in rows):5.1f} "
                        f"{pct(reach(2)):>6} {pct(reach(3)):>6} {pct(reach(4)):>6} "
                        f"{(pct(bl) if losses else '-'):>12} {pct(dd):>8} {statistics.mean(x['doom'] for x in rows):8.2f} "
                        f"{(statistics.mean(grasp) if grasp else 0):6.0f} {statistics.mean(x['shadow_kills'] for x in rows):9.2f} "
                        f"{statistics.mean(x['potions'] for x in rows):5.2f} {pct(statistics.mean(x['mp_left'] for x in rows)):>7}")
        say("")
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "final_boss_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.remove(_db)


if __name__ == "__main__":
    main()
