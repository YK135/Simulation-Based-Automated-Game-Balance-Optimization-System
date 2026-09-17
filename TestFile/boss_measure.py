# -*- coding: utf-8 -*-
"""boss_measure.py — 중간 보스 판정 지표 측정 (Combat Content Brief 11-1 3-4)

현재 AI(balanced) vs 측정용 AI(reactive) × 직업 3(전사·마법사·도적) × 레벨(기본 10·12·15) × N회를
실전 BattleSession 경로(보스 패턴 포함, ai/battle/BossKit.py)로 돌려 11-1 「1차의 판정 기준」
지표를 출력한다. 승률은 지표 하나일 뿐이다 — 도달 페이즈 · 패배 시 보스 잔여 HP ·
예고 공격 1회당 HP 피해와 실드 흡수 · 예고 후 실제로 한 행동 · 예고 직후 사망률 ·
자원 소비 · 예고 피해/총 피해 비율을 같이 본다. (2·3회차 변화는 사람 플레이의 BattleLog에서만
계산할 수 있어 여기 없다.)

실행:  python3 TestFile/boss_measure.py          (N=300 기본 — 환경변수 N, LEVELS="8,10,12,15"로 조정)
비교 실행: AI_RPG_ROOT=<패턴 이전 트리> OUT=boss_measure_before.out python3 TestFile/boss_measure.py
           — 같은 스크립트를 보스 패턴이 없던 커밋(6171135 이전)의 트리에 대고 돌리면
           "패턴 있는 보스 vs 없는 보스"를 같은 시드·같은 입력으로 비교할 수 있다
레벨을 여러 개 재는 이유: 권장 Lv15(선택 포인트 배분)에서는 세 직업 모두 승률 100%에 가까워
"둘 다 쉽게 이기면 격차는 당연히 작다"(11-1)에 걸린다 — 보스가 벽인 레벨에서 대응 차이가 보인다.
출력:  TestFile/boss_measure.out (표준출력과 동일). 시드·커밋·입력을 머리에 남긴다.
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아
회귀 스위트 루프에는 걸리지 않는다.
"""
import os, sys, io, tempfile, random, contextlib, subprocess, statistics
from collections import Counter, defaultdict

SEED = 20260917
LEVELS = [int(x) for x in os.environ.get("LEVELS", "8,10,12,15").split(",")]
OUT = os.environ.get("OUT", "boss_measure.out")
N = int(os.environ.get("N", "300"))
JOBS = ("전사", "마법사", "도적")
MODES = ("balanced", "reactive")
ITEMS = ["HP_M_potion", "HP_M_potion", "MP_M_potion"]   # montecarlo.py start_items(15)와 동일
MAX_STEPS = 400

ROOT = os.environ.get("AI_RPG_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_fd, _db = tempfile.mkstemp(prefix="bossm_", suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db
sys.path.insert(0, ROOT)

from game.Player_Class import create_player_by_job          # noqa: E402
from game.Lv import LV_, Allocate_Stat_Points               # noqa: E402
from game.Enemy_Class import Make_MidBoss                   # noqa: E402
from ai.Battlesession import BattleSession                  # noqa: E402
from ai.Auto_AI import PlayerAI                             # noqa: E402
from ai.battle import EntitySnapshot, SKILL_META            # noqa: E402
try:
    from ai.battle.BossKit import BOSS_TELEGRAPH_DETAIL     # noqa: E402
except ImportError:                                         # 패턴 이전 트리(비교 실행) — 예고가 없다
    BOSS_TELEGRAPH_DETAIL = "boss_telegraph"

MAIN_STAT = {"전사": "stg", "마법사": "sp", "탱커": "arm", "도적": "stg"}


def git_rev():
    try:
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode != 0
        return rev + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def build_player(job, level):
    """montecarlo.py의 build_player와 같은 방식 — Lv_up을 실제로 돌리고 선택 포인트는 주 스탯에 몰아준다."""
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        pts = getattr(p, "pending_points", 0)
        if pts > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: pts})
    assert p.lv == level, p.lv
    return p


def player_snap(p):
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp = s.maxhp, s.maxmp
    s.items = list(ITEMS)
    return s


def classify_player_action(action: str) -> str:
    """예고 뒤 플레이어가 고른 행동의 분류 — 지표 「예고 후 실제로 한 행동」."""
    if action.startswith("item:"):
        return "포션" if "potion" in action else "아이템"
    if action.startswith("skill:"):
        meta = SKILL_META.get(action.split(":")[1], {})
        t = meta.get("type", "")
        if t == "shield":
            return "실드"
        if t == "heal":
            return "회복"
        if t == "buff":
            return "방어 버프" if meta.get("buff_stat") == "arm" else "버프"
        if t == "debuff":
            return "디버프"
        return "공격 스킬"
    if action == "attack":
        return "일반공격"
    return "기타"


def run_one(job, mode, p, rng_seed):
    """전투 1회 — 지표에 필요한 사건만 골라 기록한다."""
    random.seed(rng_seed)
    boss_unit = Make_MidBoss(p.lv)
    bs = BattleSession(player_snap(p), enemy=EntitySnapshot.from_enemy(boss_unit),
                       items=list(ITEMS), enemy_origins=[boss_unit], is_boss=True)
    bs.battle_meta = {"source": "ai", "battle_type": "mid_boss", "chapter": 1}
    ai = PlayerAI(mode)
    boss = bs.enemies[0]
    r = {
        "win": False, "turns": 0, "max_phase": 1, "boss_hp_left": 0.0,
        "telegraphs": 0, "rift_hits": 0, "rift_dodges": 0,
        "rift_hp_dmg": [], "rift_absorb": [],
        "after_tele": None, "died_after_rift": 0,
        "potions": 0, "final_mp": 0.0, "final_shield": 0.0,
        "dmg_taken_total": 0.0, "dmg_taken_rift": 0.0,
    }
    awaiting_player = False
    steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        hp0, sh0 = bs.player.hp, bs.player.shield
        n_logs = len(bs.logs)
        if na == "player":
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=1)
            action = {"attack": "attack", "skill": f"skill:{a.detail}",
                      "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            if action.startswith("item:HP"):
                r["potions"] += 1
            if awaiting_player:
                r["after_tele"] = classify_player_action(action)
                awaiting_player = False
            bs.step(action)
            # PlayerAI는 스냅샷의 items를 보고 포션을 고르는데 세션은 self.items에서만 차감한다 —
            # 둘을 맞춰 두지 않으면 AI가 없는 포션을 계속 고르며 차례를 버린다(item_failed)
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
        new_logs = bs.logs[n_logs:]
        taken = max(0.0, hp0 - bs.player.hp)
        r["dmg_taken_total"] += taken
        for lg in new_logs:
            if lg.actor != "enemy":
                continue
            if lg.action == "watch" and lg.action_detail == BOSS_TELEGRAPH_DETAIL:
                r["telegraphs"] += 1
                awaiting_player = True
            elif lg.action == "skill" and (lg.action_detail or "").startswith("대지 균열"):
                if lg.is_dodge:
                    r["rift_dodges"] += 1
                else:
                    r["rift_hits"] += 1
                    r["rift_hp_dmg"].append(taken)
                    r["rift_absorb"].append(max(0.0, sh0 - bs.player.shield))
                    r["dmg_taken_rift"] += taken
                    if bs.done and bs.winner == "enemy":
                        r["died_after_rift"] += 1
        r["max_phase"] = max(r["max_phase"], getattr(boss, "boss_phase", 0) or 1)
    if not bs.done:
        bs.winner = "enemy"          # 미결은 보수적으로 패배 (MultiBattleSimulator와 동일)
    r["win"] = bs.winner == "player"
    r["turns"] = bs.turn
    r["boss_hp_left"] = max(0.0, boss.hp) / boss.maxhp
    r["final_mp"] = bs.player.mp / max(1.0, bs.player.maxmp)
    r["final_shield"] = bs.player.shield
    return r


def pct(x):
    return f"{100 * x:5.1f}%"


def mean(xs, default=0.0):
    return statistics.mean(xs) if xs else default


def main():
    out = []
    say = out.append
    players = {(job, lv): build_player(job, lv) for job in JOBS for lv in LEVELS}
    say(f"boss_measure — seed={SEED} N={N} per (level × job × mode)  commit={git_rev()}  levels={LEVELS}  root={ROOT}")
    say(f"items={ITEMS}  boss=Make_MidBoss(lv) (HP 1200 / STG 36 / ARM 27 / SPARM 24 / SPD 24 / LUC 22 — 레벨 무관)")
    say("player: Lv1→목표 레벨까지 실제 Lv_up, 선택 포인트는 주 스탯에 전부 (montecarlo.py build_player와 동일)")
    for (job, lv), p in players.items():
        say(f"  Lv{lv:<3}{job:<4} maxHP {p.maxhp:>5} MP {p.maxmp:>4} STG {p.stg:>5.1f} ARM {p.arm:>5.1f} SPARM {p.sparm:>5.1f} "
            f"SP {p.sp:>5.1f} SPD {p.spd:>5.1f} LUC {p.luc:>5.1f}  skills={list(getattr(p, 'learned_skills', []) or [])}")
    say("AI: balanced = 현재 튜닝 기준 AI / reactive = 측정용(예고 시 실드→회복→포션→방어버프, 반응 스킬 가점)")
    say("")

    results = {}
    for lv in LEVELS:
        for job in JOBS:
            for mode in MODES:
                rows = [run_one(job, mode, players[(job, lv)], SEED * 1000 + i) for i in range(N)]
                results[(lv, job, mode)] = rows

    hdr = (f"{'Lv':<4} {'직업':<4} {'AI':<9} {'승률':>6} {'평균턴':>6} {'P2도달':>6} {'P3도달':>6} {'패배시보스HP':>9} "
           f"{'예고/전투':>7} {'균열명중':>6} {'회피':>4} {'1회HP피해':>8} {'1회흡수':>7} {'직후사망':>6} "
           f"{'포션/전투':>7} {'종료MP':>6} {'예고/총피해':>8}")
    say("[본표] 판정 지표 — 레벨 × 직업 × AI")
    say(hdr)
    for lv in LEVELS:
      for job in JOBS:
        for mode in MODES:
            rows = results[(lv, job, mode)]
            losses = [r for r in rows if not r["win"]]
            hits = [d for r in rows for d in r["rift_hp_dmg"]]
            absorbs = [d for r in rows for d in r["rift_absorb"]]
            n_hits = sum(r["rift_hits"] for r in rows)
            n_dodge = sum(r["rift_dodges"] for r in rows)
            tot_taken = sum(r["dmg_taken_total"] for r in rows)
            say(f"{lv:<4} {job:<4} {mode:<9} {pct(mean([r['win'] for r in rows])):>6} {mean([r['turns'] for r in rows]):>6.1f} "
                f"{pct(mean([r['max_phase'] >= 2 for r in rows])):>6} {pct(mean([r['max_phase'] >= 3 for r in rows])):>6} "
                f"{pct(mean([r['boss_hp_left'] for r in losses])) if losses else '   -  ':>9} "
                f"{mean([r['telegraphs'] for r in rows]):>7.2f} {n_hits:>6} {n_dodge:>4} "
                f"{mean(hits):>8.1f} {mean(absorbs):>7.1f} "
                f"{pct(sum(r['died_after_rift'] for r in rows) / n_hits) if n_hits else '  -  ':>6} "
                f"{mean([r['potions'] for r in rows]):>7.2f} {pct(mean([r['final_mp'] for r in rows])):>6} "
                f"{pct(sum(r['dmg_taken_rift'] for r in rows) / tot_taken) if tot_taken else '  -  ':>8}")
    say("  1회HP피해/1회흡수 = 균열 명중 1회당 실제 HP 감소 / 실드 흡수량 (플레이어 maxHP 기준은 위 표).")
    say("  직후사망 = 균열이 명중한 그 step에서 전투가 패배로 끝난 비율. 예고/총피해 = 균열 직격 HP 피해 / 전투 중 받은 HP 피해 합.")
    say("")

    say("[부록 A] 예고 후 실제로 한 행동 — 첫 예고 뒤 플레이어의 다음 행동 분포 (전투당 1회 집계)")
    for lv in LEVELS:
      for job in JOBS:
        for mode in MODES:
            c = Counter(r["after_tele"] for r in results[(lv, job, mode)] if r["after_tele"])
            total = sum(c.values())
            dist = ", ".join(f"{k} {100 * v / total:.0f}%" for k, v in c.most_common()) if total else "(예고 없음)"
            say(f"  Lv{lv:<3}{job:<4} {mode:<9} n={total:<4} {dist}")
    say("")
    say("[부록 B] 두 AI의 격차 (reactive − balanced) — 보조 지표. 둘 다 쉽게 이기거나 둘 다 지면 격차는 작다.")
    for lv in LEVELS:
      for job in JOBS:
        b, r_ = results[(lv, job, "balanced")], results[(lv, job, "reactive")]
        dw = mean([x["win"] for x in r_]) - mean([x["win"] for x in b])
        hb = mean([d for x in b for d in x["rift_hp_dmg"]]); hr = mean([d for x in r_ for d in x["rift_hp_dmg"]])
        ab = mean([d for x in b for d in x["rift_absorb"]]); ar = mean([d for x in r_ for d in x["rift_absorb"]])
        say(f"  Lv{lv:<3}{job:<4} 승률 {dw * 100:+5.1f}%p   균열 1회 HP 피해 {hb:6.1f} → {hr:6.1f}   실드 흡수 {ab:6.1f} → {ar:6.1f}   "
            f"패배 시 보스 잔여 HP {pct(mean([x['boss_hp_left'] for x in b if not x['win']]))} → "
            f"{pct(mean([x['boss_hp_left'] for x in r_ if not x['win']]))}")

    txt = "\n".join(out)
    print(txt)
    with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT), "w", encoding="utf-8") as f:
        f.write(txt + "\n")


try:
    main()
finally:
    os.remove(_db)
