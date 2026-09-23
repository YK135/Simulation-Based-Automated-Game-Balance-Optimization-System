# -*- coding: utf-8 -*-
"""
elite_logic_measure.py — 브리프 3장 「남은 로직 변경 3건」 측정

브리프 3장 표가 남겨둔 세 건 (전부 "일반 전투 밸런스를 건드리므로 2차"):
  ① 고블린 대장 — 격노 후 3턴마다 「호령」(살아있는 동료 STG +10%, 2턴)
  ② 증식 슬라임 — 분열 직후 본체 2턴 행동 불가
  ③ 그림자 암살자 — HP 30% 이하 퇴각 시 보상 완화(골드 지급 / 경험치 절반)

측정 전에 코드에서 확인된 것 — ②·③은 브리프의 전제가 당시 코드와 어긋나 있었다:
  ② `_split_slime`은 사망 훅에서만 불렸고, 그 훅은 `target.hp > 0`이면 즉시 반환했다.
     즉 분열은 **본체가 죽는 순간** 일어났고 분열 직후 본체는 이미 시체라
     "2턴 행동 불가"를 걸 대상이 없었다. 브리프 표의 "HP 30%에서 분열"은
     자식의 HP 비율(SLIME_SPLIT_HP_RATIO)을 트리거로 잘못 읽은 것이다.
     → 팔 B/C가 "브리프가 의도한 설계"(HP 30%에서 **살아있는 채** 분열) 프로토타입.
  ③ `ASSASSIN_SPRINT_HP_THRESHOLD`가 실제로 하는 일은 SPD +10% 버프(「추진력」)뿐이다.
     암살자는 전장을 떠나지 않으므로 **보상이 소멸하는 상황 자체가 없고**, 따라서
     "보상 완화"는 고칠 대상이 아니라 먼저 "퇴각을 구현할지"를 정할 일이다.
     → 팔 A로 "퇴각을 넣었다면 몇 %의 전투에서 처치를 놓쳤을지"를 먼저 잰다.

팔 (SUBJECT별):
  goblin    A 현재 / B 격노 후부터 카운트 / C 게이트 없음 / D 행동 소비 / E 카운트는 처음부터·발동만 격노 후
  slime     A 현재(사망 분열) / B 생존 분열 + 본체 2턴 행동 불가 / C 생존 분열만
  assassin  A 현재(추진력) / B 퇴각 확정(fled — 보상 소멸)

★ 채택 결과(BALANCE_PATCH_8.md): ① 팔 E, ② 팔 B가 프로덕션에 들어갔고 ③은 구현하지 않았다.
  그래서 `patch()`가 매 실행마다 프로덕션 쪽 동작을 끈다 — 팔 A는 계속 "구현 전 기준선"이고,
  팔 B~E는 이 파일의 래퍼가 전담한다. 채택 후에도 같은 표를 다시 뽑을 수 있게 하기 위함이다.

실행:  python3 TestFile/elite_logic_measure.py        (환경변수 N / LEVELS / SUBJECT / AI_MODE / OUT)
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
from ai.battle import EntitySnapshot, Buff
from ai.battle.Actions import Action
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
from core.Balance_Hook import BalanceHook
from app.Map import _apply_stat_scale
import ai.battle_session.Elite_Actions as EA

# ★ 8차 당시 app/Map.py의 엘리트 할인 표. 13차에서 엘리트 2마리가 튜너를
#   우회하며 전제가 깨져 본체에서는 삭제됐다(지금은 _elite_stat_scale의 가산).
#   이 스크립트는 8차 결과를 재현하는 기록이라 그때 값을 그대로 둔다.
_ELITE_STAT_SCALE_8TH = {1: 1.00, 2: 0.90}

SEED = 20260922
N = int(os.environ.get("N", "120"))
MAX_STEPS = 400
AI_MODE = os.environ.get("AI_MODE", "balanced")
MAIN_STAT = {"전사": "stg", "마법사": "sp", "도적": "stg"}
JOBS = os.environ.get("JOBS", "전사,마법사,도적").split(",")

# ── 후보 수치 (브리프 3장 표 그대로) ──
RALLY_INTERVAL = int(os.environ.get("RALLY_INTERVAL", "3"))
RALLY_AMOUNT = float(os.environ.get("RALLY_AMOUNT", "0.10"))
RALLY_TURNS = int(os.environ.get("RALLY_TURNS", "2"))
SLIME_ALIVE_SPLIT_RATIO = 0.30      # 본체가 살아있는 채 분열하는 HP 문턱(팔 B/C)
SLIME_STUN_ACTIONS = 2              # 분열 직후 본체가 건너뛰는 행동 수(팔 B)


def _items(level):
    if level <= 5:
        return ["HP_S_potion", "HP_S_potion", "MP_S_potion"]
    return ["HP_M_potion", "HP_M_potion", "MP_M_potion"]


def git_rev():
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "?"


_PLAYERS = {}
def build_player(job, level):
    key = (job, level)
    if key in _PLAYERS:
        return _PLAYERS[key]
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {MAIN_STAT[job]: p.pending_points})
        auto_resolve_skill_choices(p, "new")
    assert p.lv == level, p.lv
    _PLAYERS[key] = p
    return p


def snap(p, level):
    s = EntitySnapshot.from_player(p)
    s.hp, s.mp = s.maxhp, s.maxmp
    s.items = list(_items(level))
    return s


_HOOKS = {}
def get_hook(job, level):
    """(job, level)당 BalanceHook 하나 — 실전도 레벨업 전까진 같은 훅/캐시를 쓴다."""
    key = (job, level)
    if key not in _HOOKS:
        p = build_player(job, level)
        _HOOKS[key] = BalanceHook(p, _items(level), show_graph=False, verbose=False,
                                  auto_prewarm=False)
    return _HOOKS[key]


_TUNED = {}
def tuned_snap(job, level, enemy_type, chapter=1):
    """실전 엘리트 노드와 같은 경로 — hook.get_enemy(difficulty="hard")로 자동 튜닝된 스탯.

    ★ 팔 사이 비교가 목적이므로 (job, level, 몬스터)당 **한 번만** 뽑아 캐시한다.
      매 전투마다 다시 부르면 백그라운드 튜닝이 도중에 끝나면서 팔마다 다른 적을
      상대하게 된다. 캐시 전에 _sim_ready를 기다려 2초 폴백(미튜닝 기본 스탯)에
      걸리지 않게 한다 — 그래야 "실전에서 실제로 만나는 적"을 재는 것이 된다."""
    key = (job, level, enemy_type, chapter)
    if key not in _TUNED:
        hook = get_hook(job, level)
        hook.get_enemy(enemy_type, difficulty="hard", chapter=chapter)   # 백그라운드 튜닝 시작
        ev = hook._sim_ready.get((enemy_type, chapter))
        if ev is not None:
            ev.wait(timeout=180.0)
        _TUNED[key] = hook.get_enemy(enemy_type, difficulty="hard", chapter=chapter)
    return _TUNED[key]


def elite_units(job, leader_type, level, escort_type=None, chapter=1):
    """app/Map._make_elite_encounter와 같은 구성 — 리더(hard, elite_leader) + 선택적 동료(hard).
    동료가 있으면 실전과 같이 _ELITE_STAT_SCALE_8TH[2]를 적용한다."""
    hook = get_hook(job, level)
    leader = hook.make_battle_unit(copy.deepcopy(tuned_snap(job, level, leader_type, chapter)))
    leader.is_elite = True
    leader.elite_leader = True
    units = [leader]
    if escort_type is not None:
        escort = hook.make_battle_unit(copy.deepcopy(tuned_snap(job, level, escort_type, chapter)))
        escort.is_elite = True
        escort.elite_leader = False
        units.append(escort)
        _apply_stat_scale(units, _ELITE_STAT_SCALE_8TH[2])
    return units


# ═══════════════════════════════════════════════════════
# 팔 구현 — 프로덕션 코드는 건드리지 않고 이 프로세스에서만 덮어쓴다
# ═══════════════════════════════════════════════════════

_ORIG_GOBLIN_PRE = BattleSession._elite_goblin_pre
_ORIG_ASSASSIN_PRE = BattleSession._elite_assassin_pre
_ORIG_CHECK_DEATH = BattleSession._check_elite_hp

COUNTS = Counter()


def _goblin_pre(arm):
    """팔 정의
      A 현재 — 호령 없음
      B 브리프 그대로 — 격노 **후에 세기 시작**해 3행동마다, 살아있는 **동료**만 STG +10%(2턴), 무료
      C 게이트 제거 — 전투 시작부터 3행동마다 (격노를 기다리지 않는다)
      D B와 같되 호령이 **대장의 행동을 소비**한다(그 행동에 공격하지 않음)
      E 카운터는 전투 시작부터 돌고 **발동만 격노 후** — "격노 후"를 지키면서
        격노한 그 행동에서 바로 한 번 터진다(B는 격노 뒤 3행동을 더 기다린다)

    대장 자신은 어느 팔에서도 대상이 아니다 — apply_buff는 같은 stat을 덮어쓰므로
    분노(STG +15%, 무기한)가 호령(+10%, 2턴)에 지워져 **격노가 오히려 약해진다**.
    (자기 자신 포함 팔을 따로 돌려봤자 이 규칙 때문에 B와 같은 값이 나온다.)"""
    def pre(self, enemy, msgs):
        _ORIG_GOBLIN_PRE(self, enemy, msgs)
        if arm == "A":
            return
        # ★ 카운터는 이 스크립트 전용 필드에 따로 센다 — 프로덕션도 같은 행동에서
        #   elite_pattern_turn을 올리므로(호령 채택 이후), 그 필드를 같이 쓰면
        #   한 행동에 2씩 올라 팔의 주기가 절반이 된다.
        if arm in ("B", "D") and not enemy.elite_pattern_used:
            return              # 브리프 표의 "격노 후 3턴마다" — 카운터도 격노 후에 시작
        turn = getattr(enemy, "_measure_rally_turn", 0) + 1
        enemy._measure_rally_turn = turn
        if arm == "E" and not enemy.elite_pattern_used:
            return              # 카운터는 계속 돌되 발동만 격노 후
        if turn < RALLY_INTERVAL:
            return
        targets = [e for e in self.enemies if e.hp > 0 and e is not enemy]
        if not targets:
            return              # 동료가 없으면 호령 자체가 성립하지 않는다(카운터는 그대로 둔다)
        enemy._measure_rally_turn = 0
        for t in targets:
            t.apply_buff(Buff(stat="stg", amount=RALLY_AMOUNT,
                              turns=RALLY_TURNS, name="호령"))
        COUNTS["rally"] += 1
        msgs.append(f"{enemy.name}이(가) 호령했다! 동료의 공격력이 올랐다!")
        if arm == "D":
            self._rally_consumes_action = True
    return pre


class _RallyAI:
    """팔 D — 호령한 행동은 대장이 공격하지 않고 소비한다."""
    def __init__(self, session, inner):
        self.session, self.inner = session, inner

    def __call__(self, enemy, player, chapter=1):
        if getattr(self.session, "_rally_consumes_action", False):
            self.session._rally_consumes_action = False
            return Action("watch", "elite_rally")
        return self.inner(enemy, player, chapter=chapter)


def _check_death(arm):
    def check(self, target, msgs):
        if (arm in ("B", "C") and getattr(target, "elite_leader", False)
                and getattr(target, "enemy_type", "") == "슬라임"
                and target.hp > 0 and target.maxhp > 0
                and not target.elite_pattern_used
                and target.hp / target.maxhp <= SLIME_ALIVE_SPLIT_RATIO):
            self._split_slime(target, msgs)     # 안에서 elite_pattern_used를 세운다
            COUNTS["alive_split"] += 1
            if arm == "B":
                target.split_stun = SLIME_STUN_ACTIONS
            return
        return _ORIG_CHECK_DEATH(self, target, msgs)
    return check


def _assassin_pre(arm):
    def pre(self, enemy, msgs):
        if arm == "A":
            return _ORIG_ASSASSIN_PRE(self, enemy, msgs)
        # 팔 B — 「추진력」 자리에 진짜 퇴각을 넣는다(고블린 겁쟁이와 같은 처리).
        used_before = enemy.elite_pattern_used
        _ORIG_ASSASSIN_PRE(self, enemy, msgs)
        if enemy.elite_pattern_used and not used_before and enemy.hp > 0:
            enemy.buffs = [b for b in enemy.buffs if b.name != "추진력"]
            enemy.fled = True
            enemy.hp = 0.0
            enemy.reward_eligible = False
            COUNTS["retreat"] += 1
            msgs.append(f"{enemy.name}이(가) 그림자 속으로 사라졌다... (보상 소멸)")
    return pre


def patch(subject, arm):
    # 프로덕션에 들어간 동작(호령·생존 분열)은 이 프로세스에서 꺼 둔다 — 팔 A가 계속
    # "구현 전 기준선"이어야 같은 스크립트로 나중에도 같은 비교를 할 수 있다.
    # 팔 B~E의 동작은 전부 아래 래퍼가 전담한다(프로덕션 코드는 그대로 둔다).
    EA.GOBLIN_RALLY_INTERVAL = 10 ** 9
    EA.SLIME_SPLIT_TRIGGER_RATIO = -1.0
    BattleSession._elite_goblin_pre = _goblin_pre(arm) if subject == "goblin" else _ORIG_GOBLIN_PRE
    BattleSession._elite_assassin_pre = _assassin_pre(arm) if subject == "assassin" else _ORIG_ASSASSIN_PRE
    BattleSession._check_elite_hp = _check_death(arm) if subject == "slime" else _ORIG_CHECK_DEATH


def wrap_ai(bs, subject, arm):
    if subject == "goblin" and arm == "D":
        bs._enemy_ai = _RallyAI(bs, bs._enemy_ai)


# ═══════════════════════════════════════════════════════

def run_one(p, job, level, cell, subject, arm, seed):
    _cname, chapter, leader_type, escort_type = cell
    random.seed(seed)
    COUNTS.clear()
    units = elite_units(job, leader_type, level, escort_type, chapter)
    bs = BattleSession(snap(p, level),
                       enemies=[EntitySnapshot.from_enemy(u) for u in units],
                       items=list(_items(level)), enemy_origins=units, is_boss=False)
    bs.battle_meta = {"source": "ai", "battle_type": "elite", "chapter": chapter}
    wrap_ai(bs, subject, arm)
    ai = PlayerAI(AI_MODE)
    leader = bs.enemies[0]
    steps = 0
    reached = False         # 리더가 퇴각/격노 문턱 아래로 내려간 적이 있는가
    while not bs.done and steps < MAX_STEPS:
        steps += 1
        if leader.maxhp > 0 and 0 < leader.hp / leader.maxhp <= 0.30:
            reached = True
        na, _ = bs._peek_next_actor()
        if na == "player":
            alive = max(1, len([e for e in bs.enemies if e.hp > 0]))
            tgt = bs._current_target() or bs.enemy
            a = ai.decide(bs.player, tgt, enemy_count=alive)
            action = {"attack": "attack", "skill": f"skill:{a.detail}",
                      "item": f"item:{a.detail}"}.get(a.action_type, "attack")
            bs.step(action)
            bs.player.items = list(bs.items)
        else:
            bs.step("auto")
    if not bs.done:
        bs.winner = "enemy"
    win = bs.winner == "player"
    return {
        "win": win, "turns": bs.turn,
        "hp_left": max(0.0, bs.player.hp) / bs.player.maxhp,
        "rally": COUNTS["rally"], "alive_split": COUNTS["alive_split"],
        # 경직 소비는 프로덕션(_single_enemy_action_core)이 처리하므로 로그에서 센다
        "stun_action": sum(1 for lg in bs.logs if lg.action_detail == "split_stun"),
        "retreat": COUNTS["retreat"],
        # 「놓친 처치」 — 리더가 30% 아래로 내려갔고 그 뒤 실제로 잡혔다(= 퇴각을 넣었다면 뺏겼을 전투)
        "robbed": bool(reached and win and not getattr(leader, "fled", False)),
        "rage": bool(getattr(leader, "elite_pattern_used", False)),
    }


SUBJECTS = {
    # subject: (팔들, [(셀 이름, 챕터, 리더, 동료)])
    "goblin": (("A", "B", "C", "D", "E"), [
        ("대장 단독", 1, "고블린", None),
        ("대장+고블린", 1, "고블린", "고블린"),
        ("대장+박쥐", 1, "고블린", "박쥐"),
    ]),
    "slime": (("A", "B", "C"), [
        ("증식 슬라임", 1, "슬라임", None),     # _ELITE_SOLO_ONLY — 항상 단독
    ]),
    "assassin": (("A", "B"), [
        ("암살자 단독", 2, "암살자", None),
        ("암살자+유령", 2, "암살자", "유령"),
    ]),
}
DEFAULT_LEVELS = {"goblin": [3, 5, 7, 9], "slime": [3, 5, 7, 9], "assassin": [10, 13, 16, 20]}


def pct(x):
    return f"{100 * x:5.1f}%"


def main():
    subjects = os.environ.get("SUBJECT", "goblin,slime,assassin").split(",")
    out = []
    say = out.append
    say(f"# 브리프 3장 엘리트 로직 3건 측정 — 커밋 {git_rev()} · 시드 {SEED} · N={N}/셀 · AI={AI_MODE}")
    say("상대는 실전 엘리트 노드와 같은 경로 — hook.get_enemy(difficulty='hard')로 자동 튜닝된 스탯을")
    say("(직업,레벨,몬스터)당 한 번 뽑아 모든 팔이 같은 적을 상대한다. 동료가 있는 셀은")
    say("실전과 같이 _ELITE_STAT_SCALE_8TH[2]=0.90을 적용한다.")
    say("")
    for subject in subjects:
        subject = subject.strip()
        if subject not in SUBJECTS:
            continue
        arms, cells = SUBJECTS[subject]
        levels = [int(x) for x in os.environ["LEVELS"].split(",")] if os.environ.get("LEVELS") \
            else DEFAULT_LEVELS[subject]
        say(f"── {subject} — 팔 {' / '.join(arms)} ──")
        header = f"{'직업':<5} {'Lv':>3} {'셀':<12} | " + " ".join(f"{a}승률 " for a in arms)
        if subject == "goblin":
            header += f"| {'격노':>5} " + " ".join(f"{a}호령" for a in arms[1:]) + " "
        if subject == "slime":
            header += f"| {'분열':>5} {'경직':>5} "
        if subject == "assassin":
            header += f"| {'퇴각':>5} {'A뺏김':>6} "
        header += "| " + " ".join(f"{a}턴  " for a in arms)
        say(header)
        totals = {a: [] for a in arms}
        for job in JOBS:
            for lv in levels:
                p = build_player(job, lv)
                for cell in cells:
                    cname, chapter, leader_type, escort_type = cell
                    # ★ 팔 루프 전에 튜닝을 끝내 둔다 — get_enemy()의 백그라운드 시뮬은
                    #   전역 random 모듈을 쓰므로, 전투 도중에 끝나면 그 전투의 난수열만
                    #   어긋나 A/B가 같은 시드로도 갈린다(실측: 팔 A만 승률이 달랐다).
                    tuned_snap(job, lv, leader_type, chapter)
                    if escort_type:
                        tuned_snap(job, lv, escort_type, chapter)
                    res = {}
                    for arm in arms:
                        patch(subject, arm)
                        res[arm] = [run_one(p, job, lv, cell, subject, arm,
                                            SEED * 1000 + lv * 100 + i) for i in range(N)]
                    w = {a: statistics.mean(r["win"] for r in res[a]) for a in arms}
                    for a in arms:
                        totals[a].append(w[a])
                    line = (f"{job:<5} {lv:>3} {cname:<12} | "
                            + " ".join(pct(w[a]) + " " for a in arms))
                    if subject == "goblin":
                        line += (f"| {pct(statistics.mean(r['rage'] for r in res['A'])):>5} "
                                 + " ".join(f"{statistics.mean(r['rally'] for r in res[a]):5.2f}"
                                            for a in arms[1:]) + " ")
                    if subject == "slime":
                        line += (f"| {statistics.mean(r['alive_split'] for r in res['B']):5.2f} "
                                 f"{statistics.mean(r['stun_action'] for r in res['B']):5.2f} ")
                    if subject == "assassin":
                        line += (f"| {statistics.mean(r['retreat'] for r in res['B']):5.2f} "
                                 f"{pct(statistics.mean(r['robbed'] for r in res['A'])):>6} ")
                    line += "| " + " ".join(f"{statistics.mean(r['turns'] for r in res[a]):5.1f}"
                                            for a in arms)
                    say(line)
            say("")
        say("평균 승률: " + " · ".join(f"{a} {pct(statistics.mean(totals[a]))}" for a in arms))
        say("")
    patch("none", "A")      # 원복
    text = "\n".join(out)
    print(text)
    dst = os.environ.get("OUT") or os.path.join(ROOT, "TestFile", "elite_logic_measure.out")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
