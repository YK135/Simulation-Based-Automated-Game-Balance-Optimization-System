# -*- coding: utf-8 -*-
"""
test_tuner_session_parity.py — 튜너가 실전과 같은 전투를 재는가 (밸런스 5차)
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_tuner_session_parity.py

BALANCE_PATCH_4가 찾은 갭: 자동 밸런싱 튜너(`StatTuner` → `BattleSimulator`)는
`ai/battle/Engine.py`의 `BattleEngine`을 돌렸는데, 골렘 3페이즈·사제 부활·
엘리트 상태기계는 `ai/battle_session/`에만 있어서 **같은 몬스터로 엔진 97.5% 대
세션 0.0%**가 나왔다. 튜너가 "다른 게임"을 재고 있었다.

5차에서 1v1 시뮬과 1vN 시뮬이 `_run_session_battle()` 한 함수를 공유하게 바꿨다.
이 파일이 고정하는 계약:

  1) BattleSimulator가 BattleSession을 돌린다 — 같은 시드·같은 입력이면
     직접 만든 BattleSession과 승자·턴이 정확히 일치한다
  2) 세션 전용 상태기계를 가진 몬스터(골렘)에서도 일치한다 — 이게 핵심이다
  3) MultiBattleSimulator도 같은 러너를 쓴다 (1마리 = 1v1과 동일 결과)
  4) 튜너 경로에 BattleEngine이 남아 있지 않다
"""
import sys, os, io, random, contextlib, tempfile, copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.battle import EntitySnapshot                                  # noqa: E402
from ai.Simulator import BattleSimulator, MultiBattleSimulator, _run_session_battle  # noqa: E402
from ai.Auto_AI import PlayerAI                                       # noqa: E402
from game.Enemy_Class import Make_Goblin, Make_Golem, Make_Priest     # noqa: E402

PASS = FAIL = 0
_buf = io.StringIO()
SEED = 20260921


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}  {detail}")


def player(job="전사", skills=None, lv=20):
    return EntitySnapshot(
        name="SIM", hp=1400, maxhp=1400, mp=140, maxmp=140,
        stg=90, arm=25, sparm=15, sp=25, luc=15, lv=lv, spd=20,
        job=job, learned_skills=list(skills or ["강타1", "연속공격1"]),
        items=["HP_M_potion", "MP_M_potion"])


def enemy(maker, lv=20, grade="중"):
    with contextlib.redirect_stdout(_buf):
        return EntitySnapshot.from_enemy(maker(lv, grade))


def sim_one(p, e):
    """BattleSimulator n=1 — 튜너가 쓰는 바로 그 경로."""
    with contextlib.redirect_stdout(_buf):
        return BattleSimulator(p, e, n=1).run()


def direct_one(p, e):
    """같은 입력으로 직접 돌린 세션 — 실전과 같은 객체."""
    with contextlib.redirect_stdout(_buf):
        s = _run_session_battle(copy.deepcopy(p), [copy.deepcopy(e)],
                                list(p.items or []), PlayerAI("balanced"))
    return s


# ─────────────────────────────────────────────
def test_parity(label, maker, skills=None, job="전사"):
    p, e = player(job, skills), enemy(maker)
    agree = True
    detail = ""
    for i in range(6):
        random.seed(SEED + i)
        r = sim_one(p, e)
        random.seed(SEED + i)
        s = direct_one(p, e)
        sim_win = r.player_wins == 1
        if sim_win != (s.winner == "player") or r.avg_turns != s.turn:
            agree = False
            detail = f"시드 {SEED+i}: sim(win={sim_win}, turns={r.avg_turns}) vs 세션(win={s.winner}, turns={s.turn})"
            break
    check(f"{label} — 튜너 시뮬과 세션이 승자·턴까지 일치", agree, detail)


def test_multi_matches_single():
    print("\n[3] 1vN 시뮬도 같은 러너")
    p, e = player(), enemy(Make_Goblin)
    random.seed(SEED)
    r1 = sim_one(p, e)
    random.seed(SEED)
    with contextlib.redirect_stdout(_buf):
        r2 = MultiBattleSimulator(p, [e], n=1, items=list(p.items or [])).run()
    check("적 1마리를 넣으면 BattleSimulator와 같은 결과",
          r1.player_wins == r2.player_wins and r1.avg_turns == r2.avg_turns,
          f"{r1.player_wins}/{r1.avg_turns} vs {r2.player_wins}/{r2.avg_turns}")


def test_no_engine_in_tuner_path():
    print("\n[4] 튜너 경로에 BattleEngine이 없다")
    # 주석·docstring의 언급은 이력 설명이라 통과시키고, 실제 호출·import만 본다
    import re
    import ai.Simulator as S
    src = open(S.__file__, encoding="utf-8").read()
    used = [l.strip() for l in src.split("\n")
            if re.search(r"BattleEngine\s*\(", l) or re.search(r"import[^#]*\bBattleEngine\b", l)]
    check("ai/Simulator.py가 BattleEngine을 import하거나 호출하지 않는다", not used, used[:2])

    import core.Balance_Hook as B
    bsrc = open(B.__file__, encoding="utf-8").read()
    calls = [l for l in bsrc.split("\n")
             if "BattleEngine(" in l and not l.strip().startswith("#")]
    check("core/Balance_Hook.py도 BattleEngine을 호출하지 않는다", not calls, calls[:2])

    check("_run_session_battle이 끝난 세션을 돌려준다",
          hasattr(direct_one(player(), enemy(Make_Goblin)), "to_battle_result"))


def main():
    print("=" * 56)
    print(" 튜너 경로 일치 — 시뮬이 실전과 같은 전투를 재는가")
    print("=" * 56)
    print("\n[1] 일반 몬스터")
    test_parity("고블린", Make_Goblin)
    print("\n[2] 세션 전용 상태기계를 가진 몬스터 (예전엔 여기서 갈라졌다)")
    test_parity("골렘 (3페이즈·그로기)", Make_Golem)
    test_parity("사제 (힐·축복·약식 소생)", Make_Priest)
    test_multi_matches_single()
    test_no_engine_in_tuner_path()
    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    try:
        os.unlink(_db)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


main()
