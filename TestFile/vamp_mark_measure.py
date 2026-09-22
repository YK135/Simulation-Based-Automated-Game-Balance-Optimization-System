# -*- coding: utf-8 -*-
"""
vamp_mark_measure.py — 「피의 격노」·「피의 맹세」·「약점 표식」의 수지 측정
(Combat Content Brief 11-1 후속 ① · 발견 ②)

발견 ②: "문서 수치 그대로면 수지가 안 맞는다 — 3턴 버프는 시전 행동에서 1턴이 줄어 실제로
덮는 행동이 2회뿐이고, 흡혈은 상한에 묶여 HP 지불을 회수하지 못한다."

세 스킬은 **기본 AI(balanced)가 아예 고르지 않는다** — balanced의 버프·디버프 선택은
`_best_buff_skill(stat="stg"/"arm"/"spd")` / `_best_debuff_skill(stat="spd"/"stg")`로
stat을 지정해 찾으므로 buff_stat "lifesteal"/"lifesteal_oath", debuff_stat "vulnerable"은
후보에 들어오지 않는다. 그래서 montecarlo.py 전 구간 스윕(balanced)으로는 이 세 스킬의
변화를 절대 잴 수 없고, 사람을 모델링하는 측정용 AI(reactive)로 재야 한다.
(반대로 말하면 balanced 스윕은 "다른 게 안 움직였다"는 대조군으로만 쓴다.)

같은 플레이어를 네 가지 팔로 나눠 같은 시드로 비교한다:
  A 게이트 — 스킬 보유, reactive AI의 판단 그대로(격노·맹세는 `_lifesteal_buff_profit > 0` 게이트)
  B 미보유 — 그 스킬만 제거(나머지 스킬·스탯·아이템 동일)
  C 항상   — 스킬 보유 + 게이트 무시, 조건만 맞으면 곧바로 사용
             ("설명만 보고 쓰는 사람"의 상한. A와 갈리는 폭이 게이트의 값이다)
  D 대안   — 2택 1의 짝(방패치기 / 철벽 의지 / 둔화2)으로 교체 — 실제 플레이어가 마주하는 선택
  E 1회    — 쓸 수 있게 된 첫 행동에 한 번만 쓰고, 그 뒤 스킬 목록에서 빼서 다시 못 쓰게 한다
             ("버프 걸고 싸운다"는 실제 플레이 패턴. 지불·회수의 1회당 실수지는 이 팔로 읽는다 —
              C는 게이트 없이 재시전을 반복해 행동 대부분을 시전에 쓰므로 회수가 과소평가된다)
지표: 승률 · 평균 턴 · 남은 HP 비율 · 사용 횟수 · **지불 HP와 흡혈 회수 합**(피격 장부의
via="cost"/"lifesteal"을 그대로 집계 — 장부는 표시 전용이지만 측정에서 읽는 것은 무해하다).

실행:  python3 TestFile/vamp_mark_measure.py     (환경변수 N / LEVELS / SKILLS / OUT)
로컬 ai_rpg.db는 건드리지 않는다(DATABASE_URL을 임시 파일로). 이름이 test_로 시작하지 않아
회귀 스위트 루프에는 걸리지 않는다.
"""
import os, sys, io, random, contextlib, statistics, tempfile, subprocess
from collections import defaultdict

ROOT = os.environ.get("AI_RPG_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.Battlesession import BattleSession
from ai.Auto_AI import PlayerAI, Action, _self_has_buff, _enemy_has_debuff
from ai.battle import EntitySnapshot, SKILL_META
from ai.battle.Entity import EntitySnapshot as _ES
from ai.battle.Skills import skill_requirement_error
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices, JOB_SKILL_CHOICES
from game import Enemy_Class as EC

SEED = 20260922
N = int(os.environ.get("N", "100"))
MAX_STEPS = 400
ITEMS = ["HP_M_potion", "HP_M_potion", "MP_M_potion"]

# 측정 대상 — (스킬, 직업, 해금 레벨, 짝이 되는 기존 스킬)
TARGETS = {
    "피의 격노": ("전사", 11, JOB_SKILL_CHOICES["전사"][11][1]),
    "피의 맹세": ("전사", 25, JOB_SKILL_CHOICES["전사"][25][1]),
    "약점 표식": ("도적", 11, JOB_SKILL_CHOICES["도적"][11][1]),
}
SKILLS = [s for s in os.environ.get("SKILLS", ",".join(TARGETS)).split(",") if s in TARGETS]
# ── 후보 수치 시험용 오버라이드 (측정 전용 — 이 프로세스의 SKILL_META만 바꾼다) ──
#   TUNE="피의 격노:hp_cost_ratio=0.08,buff_amount=0.35;약점 표식:debuff_amount=0.20"
#   debuff_amount/debuff_turns는 (min, max) 튜플이라 스칼라를 주면 양쪽에 같은 값을 넣는다.
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

LEVELS = [int(x) for x in os.environ.get("LEVELS", "11,15,20,25").split(",")]

# 일반 몬스터·중간 보스는 Lv11 이상에서 reactive AI가 전부 100% 이긴다(band_scan 실측) —
# 그 셀의 지표는 승률이 아니라 **남은 HP 비율과 지불/회수**다. 승률이 갈리는 곳은 최종 보스뿐.
OPPONENTS = [
    ("골렘상",    2, lambda lv: EC.Make_Golem(lv, "상")),
    ("암살자상",  2, lambda lv: EC.Make_Assassin(lv, "상")),
    ("중간 보스", 1, lambda lv: EC.Make_MidBoss(lv)),
    ("최종 보스", 2, lambda lv: EC.Make_FinalBoss(lv)),
]
ARMS = ("A", "B", "C", "D", "E")

# ── 지불·회수 집계: 피격 장부 훅을 감싸 via별로 더한다 (프로덕션 코드는 그대로) ──
LEDGER = defaultdict(float)
_orig_record_hit = _ES._record_hit


def _record_hit_spy(self, kind, amount, via="", element=None, reaction=None):
    if via in ("cost", "lifesteal") and amount > 0:
        LEDGER[via] += float(amount)
    return _orig_record_hit(self, kind, amount, via=via, element=element, reaction=reaction)


_ES._record_hit = _record_hit_spy


def git_rev():
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
            Allocate_Stat_Points(p, {"stg": pts})
        auto_resolve_skill_choices(p, "new")     # 2택 1은 전부 신규 쪽 — 팔 D만 해당 한 쌍을 되돌린다
    assert p.lv == level, p.lv
    return p


def snap(p, skill, arm, alt_skill):
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp = s.maxhp, s.maxmp
    s.items = list(ITEMS)
    # 측정 대상 하나만 남긴다 — Lv25 전사는 격노와 맹세를 둘 다 배우므로, 안 빼면
    # 피격 장부의 via="cost"에 맹세의 만료 지불이 섞여 격노의 지불/회수가 오염된다.
    other = [k for k in TARGETS if k != skill]
    s.learned_skills = [k for k in s.learned_skills if k not in other]
    if arm in ("B", "D"):
        s.learned_skills = [k for k in s.learned_skills if k != skill]
        if arm == "D" and alt_skill not in s.learned_skills:
            s.learned_skills = list(s.learned_skills) + [alt_skill]
    return s


def forced(skill, player, target):
    """팔 C — 게이트 무시. 조건이 맞고 아직 안 걸려 있으면 곧바로 쓴다."""
    if skill not in player.learned_skills:
        return None
    if skill_requirement_error(skill, player, target) != "":
        return None
    meta = SKILL_META[skill]
    if meta.get("type") == "buff":
        if _self_has_buff(player, meta["buff_stat"]):
            return None
    elif _enemy_has_debuff(target, meta["debuff_stat"]):
        return None
    return Action("skill", skill)


def run_one(p, skill, arm, alt_skill, make_enemy, chapter, seed):
    random.seed(seed)
    LEDGER.clear()
    unit = make_enemy(p.lv)
    is_boss = unit.name in ("중간 보스", "최종 보스")
    bs = BattleSession(snap(p, skill, arm, alt_skill), enemy=EntitySnapshot.from_enemy(unit),
                       items=list(ITEMS), enemy_origins=[unit], is_boss=is_boss)
    bs.battle_meta = {"source": "ai", "battle_type": "measure", "chapter": chapter}
    ai = PlayerAI("reactive")
    uses, steps = 0, 0
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            tgt = bs._current_target() or bs.enemy
            push = None
            if arm == "C" or (arm == "E" and uses == 0):
                push = forced(skill, bs.player, tgt)
            a = push or ai.decide(bs.player, tgt, enemy_count=1)
            # 팔 E는 "딱 1회" — 시전한 뒤에는 목록에서 빼서 AI가 다시 고르지 못하게 한다
            # (안 빼면 reactive가 자기 판단으로 또 써서 E ≈ A + 1이 된다)
            action = {"attack": "attack", "skill": f"skill:{a.detail}",
                      "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            if action == f"skill:{skill}":
                uses += 1
            bs.step(action)
            if arm == "E" and uses > 0 and skill in bs.player.learned_skills:
                bs.player.learned_skills = [k for k in bs.player.learned_skills if k != skill]
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    return {
        "win": bs.winner == "player", "turns": bs.turn,
        "hp_left": max(0.0, bs.player.hp) / bs.player.maxhp,
        "uses": uses, "paid": LEDGER["cost"], "healed": LEDGER["lifesteal"],
    }


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    out = []
    say = out.append
    say(f"# 후속 ① 수지 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · 측정용 AI reactive")
    say("입력: 해당 직업 Lv1→목표까지 Lv_up, 선택 포인트 STG, 2택 1은 신규 쪽, 아이템 HP_M×2+MP_M.")
    say("상대는 등급 팩토리(중)·보스 팩토리 직접 생성(자동 튜닝 없음 — 같은 조건 A/B가 목적).")
    say("팔 A 게이트(reactive 판단대로) · B 미보유 · C 항상(게이트 무시) · D 2택 1의 짝으로 교체 · E 첫 기회에 1회만")
    say("E지불/E회수는 팔 E에서 실제로 시전한 전투만 모은 1회당 평균(피격 장부 via=cost / via=lifesteal). E수지 = 회수/지불.")
    if TUNE_NOTES:
        say("★ TUNE 적용: " + " · ".join(TUNE_NOTES))
    else:
        say("TUNE 없음 — 저장소의 현재 수치 그대로.")
    say("")
    for skill in SKILLS:
        job, unlock, alt = TARGETS[skill]
        levels = [lv for lv in LEVELS if lv >= unlock]
        if not levels:
            continue
        say(f"═══ {skill} ({job} Lv{unlock}, 짝: {alt}) ═══")
        say(f"{'Lv':>3} {'상대':<9} | " + " ".join(f"{a}승률" + " " * 2 for a in ARMS)
            + "| " + " ".join(f"{a}HP잔" + " " * 2 for a in ARMS)
            + f"| {'A사용':>5} {'E지불':>6} {'E회수':>6} {'E수지':>8} {'A턴':>5} {'B턴':>5}")
        for lv in levels:
            p = build_player(job, lv)
            if skill not in EntitySnapshot.from_player(p).learned_skills:
                say(f"{lv:>3}  (미보유 — 스킬 해금 안 됨)")
                continue
            for oname, chapter, mk in OPPONENTS:
                res = {arm: [run_one(p, skill, arm, alt, mk, chapter, SEED * 1000 + lv * 100 + i)
                             for i in range(N)]
                       for arm in ARMS}
                w = {k: statistics.mean(r["win"] for r in v) for k, v in res.items()}
                hp = {k: statistics.mean(r["hp_left"] for r in v) for k, v in res.items()}
                e_used = [r for r in res["E"] if r["uses"] > 0]
                paid = statistics.mean(r["paid"] for r in e_used) if e_used else 0.0
                healed = statistics.mean(r["healed"] for r in e_used) if e_used else 0.0
                say(f"{lv:>3} {oname:<9} | " + " ".join(pct(w[a]) for a in ARMS) + " | "
                    + " ".join(f"{100 * hp[a]:5.1f}%" for a in ARMS) + " | "
                    f"{statistics.mean(r['uses'] for r in res['A']):5.2f} "
                    f"{paid:6.0f} {healed:6.0f} {(healed / paid if paid else 0):7.2f}x "
                    f"{statistics.mean(r['turns'] for r in res['A']):5.1f} "
                    f"{statistics.mean(r['turns'] for r in res['B']):5.1f}")
            say("")
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "vamp_mark_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
