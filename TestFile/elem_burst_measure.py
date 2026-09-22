# -*- coding: utf-8 -*-
"""
elem_burst_measure.py — 「원소 폭발」의 차별화 측정 (Combat Content Brief 11-1 후속 ② · 발견 ③)

발견 ③: "원소 폭발(1.2배, MP 15)은 상대 원소 스킬을 가진 마법사에게 MP당 효율로 밀린다 —
파이어볼1도 같은 융해를 내므로 AI는 거의 고르지 않는다."

측정 전에 코드에서 확정된 것 (더 센 진단):
  주입 가능한 원소는 셋뿐이고(REACT_PARTNER: ice→fire · fire→lightning · lightning→fire),
  마법사는 **Lv4에 세 원소를 전부** 갖는다(파이어볼1·아이스볼릿1·라이트닝1). 세 경우 모두
  직접 스킬이 **계수는 더 높고 MP는 더 싸다** — 즉 원소 폭발이 최선이 되는 상태가 하나도 없다.
  게다가 반응 배율은 두 스킬에 **똑같이** 곱해지므로(_reaction_bonus) 순위를 뒤집지 못한다.
  AI 점수(mult/mp): 원소 폭발 0.080 vs 파이어볼1 0.150 · 라이트닝1 0.129.

그래서 이 스크립트가 보는 것은 "얼마나 덜 쓰이나"가 아니라 **"고치면 실제로 쓰이고,
쓰였을 때 반응이 늘고 전투가 좋아지나"**다. 팔:
  A 보유 + 측정용 AI(reactive) 판단대로
  B 미보유(원소 폭발만 제거 — 나머지 스킬·스탯·아이템 동일)
  C 보유 + 강제(쓸 수 있으면 무조건 — 사람이 콤보를 의식하고 쓰는 상한)
  b 보유 + 기본 AI(balanced) — 대조군. 기본 AI 점수는 건드리지 않는 규칙이라
    여기서 선택 0회가 유지돼야 한다(= 자동 밸런싱/튜너에 영향 없음).
지표: 승률 · 평균 턴 · 남은 HP/MP 비율 · 원소 폭발 사용 횟수 · **반응 발생 횟수**(융해/과부하/파쇄)
· **화염 폭풍 선택 빈도**(브리프 후속 ②가 경고한 "광역 슬롯 순위가 뒤집히지 않게"를 감시).

후보 수치 시험:  TUNE="원소 폭발:mult=1.9,mp=10"   (이 프로세스의 SKILL_META만 덮어쓴다)
실행:  python3 TestFile/elem_burst_measure.py    (환경변수 N / LEVELS / OUT / TUNE)
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
from ai.Auto_AI import PlayerAI, Action
from ai.battle import EntitySnapshot, SKILL_META
from ai.battle.Entity import EntitySnapshot as _ES
from ai.battle.Skills import skill_requirement_error
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
from game import Enemy_Class as EC

SEED = 20260922
N = int(os.environ.get("N", "150"))
MAX_STEPS = 400
ITEMS = ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
SKILL = "원소 폭발"
LEVELS = [int(x) for x in os.environ.get("LEVELS", "12,15,20,22,25").split(",")]

# 원소가 실제로 붙어 있는 상대 위주 — 이 스킬은 부착 원소가 없으면 시전 자체가 불가능하다.
#   원소 슬라임 3종은 INNATE_ELEMENT_BY_ENEMY_TYPE으로 항상 자기 원소가 붙어 있고 그 원소에 면역,
#   두 보스는 자기 자신에게 원소를 붙이는 페이즈가 있다(브리프 4장). 고블린은 대조군 —
#   원소가 없으므로 마법사가 먼저 붙여야 쓸 수 있다.
# 측정 셀은 마법사 reactive 승률이 포화되지 않는 구간으로 골랐다(사전 스캔: 엘리트 원소 슬라임과
# 중간 보스는 Lv9~25 전 구간 100%라 아무것도 갈리지 않는다). 남은 밴드는 셋이다 —
#   · 원소 슬라임 혼합 1v3 (ice/fire/lightning 각 1) : Lv9 72.5% → Lv25 0%. 세 적 모두 원소가
#     붙어 있어 이 스킬의 조건이 항상 성립하고, **광역기(화염 폭풍)와 정면으로 경합**하는 셀이다
#     — 브리프 후속 ②가 경고한 "둘의 순위가 뒤집히지 않게"를 여기서 본다.
#   · 빙결 슬라임 ×3 : Lv18 87.5% → Lv25 32.5%
#   · 최종 보스 : Lv18 37.5% → Lv25 95% (페이즈 1이 자기 원소를 순환 부착한다)
# 고블린(상) 단일은 대조군 — 원소가 없어 마법사가 먼저 붙여야만 쓸 수 있다.
OPPONENTS = [
    ("원소3종", 1, lambda lv: [EC.Make_IceSlime(lv, "상"), EC.Make_FireSlime(lv, "상"),
                              EC.Make_LightningSlime(lv, "상")]),
    ("빙결x3",  1, lambda lv: [EC.Make_IceSlime(lv, "상") for _ in range(3)]),
    ("고블린상", 1, lambda lv: [EC.Make_Goblin(lv, "상")]),
    ("최종 보스", 2, lambda lv: [EC.Make_FinalBoss(lv)]),
]
ARMS = ("A", "B", "C", "b")


# ── 후보 수치 오버라이드 (측정 전용) ──
def apply_tune(spec: str) -> list:
    notes = []
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, kvs = part.split(":", 1)
        meta = SKILL_META.get(name.strip())
        if meta is None:
            continue
        for kv in kvs.split(","):
            k, v = kv.split("=")
            k, v = k.strip(), float(v)
            old = meta.get(k)
            meta[k] = (v, v) if isinstance(old, tuple) else (int(v) if isinstance(old, int) else v)
            notes.append(f"{name.strip()}.{k} {old} → {meta[k]}")
    return notes


TUNE_NOTES = apply_tune(os.environ.get("TUNE", ""))

# ── 반응 집계: 표시용 도장(_stamp_last_hit)을 감싸 반응 이름을 센다 (프로덕션 코드는 그대로) ──
REACTIONS = Counter()
_orig_stamp = _ES._stamp_last_hit


def _stamp_spy(self, element, reaction="", via=""):
    if reaction:
        REACTIONS[reaction] += 1
    return _orig_stamp(self, element, reaction=reaction, via=via)


_ES._stamp_last_hit = _stamp_spy


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


def build_player(level):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", "마법사")
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {"sp": p.pending_points})
        auto_resolve_skill_choices(p, "new")
    assert p.lv == level, p.lv
    return p


def snap(p, arm):
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp = s.maxhp, s.maxmp
    s.items = list(ITEMS)
    if arm == "B":
        s.learned_skills = [k for k in s.learned_skills if k != SKILL]
    return s


def forced(player, target):
    """팔 C — 점수 무시. 부착 원소가 있어 시전 가능하면 곧바로 쓴다."""
    if SKILL not in player.learned_skills:
        return None
    if skill_requirement_error(SKILL, player, target) != "":
        return None
    return Action("skill", SKILL)


def run_one(p, arm, make_enemy, chapter, seed):
    random.seed(seed)
    REACTIONS.clear()
    units = make_enemy(p.lv)
    is_boss = units[0].name in ("중간 보스", "최종 보스")
    bs = BattleSession(snap(p, arm), enemies=[EntitySnapshot.from_enemy(u) for u in units],
                       items=list(ITEMS), enemy_origins=units, is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI("balanced" if arm == "b" else "reactive")
    uses, steps = 0, 0
    picks = Counter()
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            alive = max(1, len([e for e in bs.enemies if e.hp > 0]))
            tgt = bs._current_target() or bs.enemy
            a = (arm == "C" and forced(bs.player, tgt)) or ai.decide(bs.player, tgt, enemy_count=alive)
            action = {"attack": "attack", "skill": f"skill:{a.detail}",
                      "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            if a.action_type == "skill":
                picks[a.detail] += 1
            if action == f"skill:{SKILL}":
                uses += 1
            bs.step(action)
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    return {
        "win": bs.winner == "player", "turns": bs.turn,
        "hp_left": max(0.0, bs.player.hp) / bs.player.maxhp,
        "mp_left": max(0.0, bs.player.mp) / max(1.0, bs.player.maxmp),
        "uses": uses, "react": sum(REACTIONS.values()),
        "storm": picks.get("화염 폭풍", 0), "picks": picks,
    }


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    out = []
    say = out.append
    say(f"# 후속 ② 원소 폭발 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀")
    say("입력: 마법사 Lv1→목표까지 Lv_up, 선택 포인트 SP, 2택 1은 신규 쪽, 아이템 HP_M×2+MP_M.")
    say("상대는 등급 팩토리(상)·보스 팩토리 직접 생성(자동 튜닝 없음 — 같은 조건 A/B가 목적).")
    say("팔 A 보유+reactive · B 미보유+reactive · C 보유+강제 시전 · b 보유+balanced(대조군).")
    say("반응은 융해·과부하·파쇄 발생 횟수의 전투당 평균(표시용 도장 _stamp_last_hit 집계).")
    if TUNE_NOTES:
        say("★ TUNE 적용: " + " · ".join(TUNE_NOTES))
    else:
        say("TUNE 없음 — 저장소의 현재 수치 그대로.")
    say("")
    say(f"{'Lv':>3} {'상대':<10} | " + " ".join(f"{a}승률" + " " * 2 for a in ARMS)
        + f"| {'A사용':>5} {'C사용':>5} {'b사용':>5} {'A폭풍':>5} {'B폭풍':>5} "
        + f"| {'A반응':>5} {'B반응':>5} {'C반응':>5} "
        + f"| {'A HP잔':>6} {'B HP잔':>6} {'A MP잔':>6} {'B MP잔':>6} | {'A턴':>5} {'B턴':>5}")
    totals = {a: [] for a in ARMS}
    for lv in LEVELS:
        p = build_player(lv)
        if SKILL not in EntitySnapshot.from_player(p).learned_skills:
            say(f"{lv:>3}  (미보유 — 스킬 해금 안 됨)")
            continue
        for oname, chapter, mk in OPPONENTS:
            res = {arm: [run_one(p, arm, mk, chapter, SEED * 1000 + lv * 100 + i)
                         for i in range(N)]
                   for arm in ARMS}
            w = {k: statistics.mean(r["win"] for r in v) for k, v in res.items()}
            for k in ARMS:
                totals[k].append(w[k])
            say(f"{lv:>3} {oname:<10} | " + " ".join(pct(w[a]) for a in ARMS) + " | "
                + " ".join(f"{statistics.mean(r['uses'] for r in res[a]):5.2f}" for a in ("A", "C", "b"))
                + " "
                + " ".join(f"{statistics.mean(r['storm'] for r in res[a]):5.2f}" for a in ("A", "B"))
                + " | "
                + " ".join(f"{statistics.mean(r['react'] for r in res[a]):5.2f}" for a in ("A", "B", "C"))
                + " | "
                + " ".join(f"{100 * statistics.mean(r[f]  for r in res[a]):5.1f}%"
                           for a, f in (("A", "hp_left"), ("B", "hp_left"),
                                        ("A", "mp_left"), ("B", "mp_left")))
                + " | "
                f"{statistics.mean(r['turns'] for r in res['A']):5.1f} "
                f"{statistics.mean(r['turns'] for r in res['B']):5.1f}")
        say("")
    say("전체 평균 승률: " + " · ".join(f"{a} {pct(statistics.mean(totals[a]))}" for a in ARMS))
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "elem_burst_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
