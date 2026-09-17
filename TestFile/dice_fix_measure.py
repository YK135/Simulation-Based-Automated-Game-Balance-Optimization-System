# -*- coding: utf-8 -*-
"""
dice_fix_measure.py — 「패 고치기」의 턴 소비 가치 측정 (Combat Content Brief 6-3 · 10-3 · 11-1 2차 6번)

6-3: "공격 한 번을 포기하고 눈을 고르는 거래가 이득인지는 MC로 측정할 문제이고, 손해로 나오면
공격과 동시에 굴리는 형태(재굴림은 MP만 소비·턴 소비 없음)로 바꿔야 합니다."

같은 도적(레벨·스탯·아이템 동일)을 측정용 AI(reactive)로 두 번 재서 비교한다:
  A) 패 고치기 보유 — reactive 규칙대로 미리 보인 눈이 3 미만이면 재굴림
     (1차 측정: 턴을 쓰는 형태 → 전체 −1.5p, Lv8 보스 −28p로 손해 → 6-3 규칙대로
      "다음 주사위 미리 보기 + MP만 쓰는 재굴림(턴 소비 없음)"으로 바꾼 뒤 재측정)
  B) 패 고치기 없음 — 나머지 스킬 동일
상대: 챕터1 고블린·박쥐·슬라임(중), 챕터2 암살자·골렘(중) — 등급 팩토리 직접 호출(자동 튜닝 없음,
같은 조건의 A/B 비교가 목적) + 중간 보스. 지표: 승률 · 평균 턴 · 남은 HP 비율 · 패 고치기 사용 횟수 ·
저장 눈을 소비한 공격의 주사위 분포(6 = 확정 크리 비율).

실행:  python3 TestFile/dice_fix_measure.py    (N=200 기본, 환경변수 N / LEVELS / OUT)
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
from ai.Auto_AI import ATTACK_TYPES
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
from game import Enemy_Class as EC

SEED = 20260917
N = int(os.environ.get("N", "200"))
LEVELS = [int(x) for x in os.environ.get("LEVELS", "8,10,12,15").split(",")]
ITEMS = ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
MAX_STEPS = 400
OPPONENTS = [
    ("고블린",   1, lambda lv: EC.Make_Goblin(lv, "중")),
    ("박쥐",     1, lambda lv: EC.Make_Bat(lv, "중")),
    ("슬라임",   1, lambda lv: EC.Make_Slime(lv, "중")),
    ("암살자",   2, lambda lv: EC.Make_Assassin(lv, "중")),
    ("골렘",     2, lambda lv: EC.Make_Golem(lv, "중")),
    ("중간 보스", 1, lambda lv: EC.Make_MidBoss(lv)),
]


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


def build_player(level):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", "도적")
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        pts = getattr(p, "pending_points", 0)
        if pts > 0:
            Allocate_Stat_Points(p, {"stg": pts})
        auto_resolve_skill_choices(p, os.environ.get("SKILL_PICK", "new"))   # 스킬 2택 1 (2차 8번)
    assert p.lv == level, p.lv
    return p


def snap(p, with_fix):
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp = s.maxhp, s.maxmp
    s.items = list(ITEMS)
    if not with_fix:
        s.learned_skills = [k for k in s.learned_skills if k != "패 고치기"]
    return s


def run_one(p, with_fix, make_enemy, chapter, seed):
    random.seed(seed)
    unit = make_enemy(p.lv)
    is_boss = unit.name == "중간 보스"
    bs = BattleSession(snap(p, with_fix), enemy=EntitySnapshot.from_enemy(unit),
                       items=list(ITEMS), enemy_origins=[unit], is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI("reactive")
    fixes = 0
    fixed_dice = Counter()
    steps = 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=1)
            action = {"attack": "attack", "skill": f"skill:{a.detail}",
                      "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            pending_before = bs.player.pending_dice
            r = bs.step(action)
            bs.player.items = list(bs.items)
            if action == "skill:패 고치기":
                fixes += 1
            elif pending_before and (action == "attack" or (
                    action.startswith("skill:") and SKILL_META.get(action[6:], {}).get("type") in ATTACK_TYPES)):
                fixed_dice[pending_before] += 1        # 미리 본 눈을 소비한 공격 — 소비 직후 새 눈이 보인다
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    return {
        "win": bs.winner == "player", "turns": bs.turn,
        "hp_left": max(0.0, bs.player.hp) / bs.player.maxhp,
        "fixes": fixes, "fixed_dice": fixed_dice,
    }


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    out = []
    say = out.append
    say(f"# 패 고치기 턴 소비 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · 측정용 AI reactive")
    say("입력: 도적 Lv1→목표까지 Lv_up, 선택 포인트 STG, 아이템 HP_M×2+MP_M. 상대는 등급 팩토리(중) 직접 생성(자동 튜닝 없음).")
    say("A = 패 고치기 보유(미리 보인 눈이 3 미만이면 재굴림 — 현재 형태는 자유 행동) · B = 패 고치기 없음. 나머지 동일.")
    say("")
    say(f"{'Lv':>3} {'상대':<8} {'A 승률':>7} {'B 승률':>7} {'격차':>7} {'A 턴':>6} {'B 턴':>6} {'A HP잔':>7} {'B HP잔':>7} {'고치기/전투':>10} {'저장눈 소비 분포(1~6)':<28}")
    totals = {"A": [], "B": []}
    for lv in LEVELS:
        p = build_player(lv)
        for name, chapter, mk in OPPONENTS:
            res = {}
            for tag, with_fix in (("A", True), ("B", False)):
                rows = [run_one(p, with_fix, mk, chapter, SEED * 1000 + lv * 100 + i) for i in range(N)]
                res[tag] = rows
            a, b = res["A"], res["B"]
            wa, wb = statistics.mean(r["win"] for r in a), statistics.mean(r["win"] for r in b)
            totals["A"].append(wa); totals["B"].append(wb)
            dist = Counter()
            for r in a:
                dist.update(r["fixed_dice"])
            tot = sum(dist.values()) or 1
            dist_s = " ".join(f"{dist[i] / tot * 100:4.0f}%" for i in range(1, 7))
            say(f"{lv:>3} {name:<8} {pct(wa):>7} {pct(wb):>7} {100 * (wa - wb):+6.1f}p "
                f"{statistics.mean(r['turns'] for r in a):6.1f} {statistics.mean(r['turns'] for r in b):6.1f} "
                f"{pct(statistics.mean(r['hp_left'] for r in a)):>7} {pct(statistics.mean(r['hp_left'] for r in b)):>7} "
                f"{statistics.mean(r['fixes'] for r in a):10.2f} {dist_s:<28}")
        say("")
    ga, gb = statistics.mean(totals["A"]), statistics.mean(totals["B"])
    say(f"전체 평균 승률: A {pct(ga)} / B {pct(gb)} → 격차 {100 * (ga - gb):+.1f}p")
    say("판정 규칙(6-3): 격차가 −1p 이하(손해)면 '공격과 동시에 굴리는 형태(턴 소비 없음)'로 바꾼다.")
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "dice_fix_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
