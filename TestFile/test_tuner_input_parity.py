# -*- coding: utf-8 -*-
"""
test_tuner_input_parity.py — 튜너가 보는 플레이어와 실전이 보는 플레이어가 같은가

`core/Balance_Hook._player_to_snap`(자동 밸런싱 입력)과 `ai/battle/Entity.EntitySnapshot.from_player`
(실전 전투 입력)는 **같은 플레이어를 같게** 읽어야 한다. 둘이 어긋나면 튜너는 존재하지 않는
플레이어를 기준으로 몬스터 스탯을 맞추고, 그 결과가 실전에 그대로 나간다.

실제로 두 번 어긋났다:
  · 4차 — `job`/`relics`가 튜너 쪽에만 빠져 직업 패시브가 시뮬에서 통째로 죽었다.
  · 이번 — **스킬 조회가 1단뿐**이었다. `from_player`는 `player.skill.learned_skills`를 보고
    없으면 `player.learned_skills`로 폴백하는데, `_player_to_snap`은 1단만 봤다.
    `player.skill`이 None이고 `learned_skills`만 있는 플레이어(측정 스크립트가
    `create_player_by_job`으로 바로 만드는 형태)에서 **튜너만 스킬 0개로 읽었다**.
    실측 여파: 튜너 시뮬 승률 0.0% 대 실전 100.0%(마법사 Lv20) — 튜너가 몬스터를 바닥까지
    깎아 난이도 하/중/상이 563/563/563으로 완전히 같아졌다.
    ※ 실전 경로는 `app/Game.py`가 `player.skill`을 세우고 `game/Lv._sync_skill_object`가
      맞춰 주므로 영향이 없었다 — 망가진 건 측정 하네스 전부였다.

그래서 이 파일은 "새 필드가 생기면 두 변환기에 같이 넣어라"를 강제한다.
DB를 쓰지 않는다.

실행: python3 TestFile/test_tuner_input_parity.py
"""
import sys, os, io, random, contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.Balance_Hook import _player_to_snap
from ai.battle import EntitySnapshot
from game.Player_Class import create_player_by_job
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices
from game.Skill import Ply_Skill

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}" + (f"  → {extra}" if extra != "" else ""))


ITEMS = ["HP_M_potion", "HP_M_potion", "MP_M_potion"]
MAIN = {"전사": "stg", "마법사": "sp", "도적": "stg"}
# 두 변환기가 반드시 같게 읽어야 하는 필드
FIELDS = ("hp", "maxhp", "mp", "maxmp", "stg", "sp", "arm", "sparm", "spd", "luc", "lv", "job")


def make(job, lv, live_wiring):
    """live_wiring=True면 app/Game.py의 새 게임 경로와 같게 player.skill을 세운다."""
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("파리티", job)
        if live_wiring:
            ss = Ply_Skill(job); ss.update_skills(1)
            p.skill = ss
            p.learned_skills = list(ss.learned_skills)
        lv_ = LV_(p); guard = 0
        while p.lv < lv and guard < 300:
            lv_.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {MAIN[job]: p.pending_points})
        auto_resolve_skill_choices(p, "new", rng=random.Random(f"{job}|{lv}"))
    return p


def both(p):
    a = _player_to_snap(p, ITEMS)
    b = EntitySnapshot.from_player(p)
    return a, b


for wiring, label in ((True, "실전 배선 (app/Game.py처럼 player.skill을 세움)"),
                      (False, "하네스 배선 (player.skill이 None — 측정 스크립트 형태)")):
    print(f"\n[{label}]")
    for job in ("전사", "마법사", "도적"):
        for lv in (1, 15):
            p = make(job, lv, wiring)
            a, b = both(p)
            diff = [f for f in FIELDS if getattr(a, f, None) != getattr(b, f, None)]
            check(f"{job} Lv{lv}: 스탯/직업 전 필드 일치", not diff, diff)
            sa, sb = list(a.learned_skills), list(b.learned_skills)
            check(f"{job} Lv{lv}: 스킬 목록 일치 ({len(sb)}개)", sa == sb,
                  f"튜너 {len(sa)}개 / 실전 {len(sb)}개, 차이 {sorted(set(sb) ^ set(sa))}")

print("\n[회귀 — 이번에 터진 정확한 조건]")
p = make("마법사", 15, live_wiring=False)
check("player.skill이 None이다 (이 테스트의 전제)", p.skill is None)
check("그래도 learned_skills는 채워져 있다", bool(getattr(p, "learned_skills", None)))
a, b = both(p)
check("★ 튜너가 스킬 0개로 읽지 않는다", len(a.learned_skills) > 0,
      f"{len(a.learned_skills)}개")
check("★ 실전과 같은 개수를 읽는다", len(a.learned_skills) == len(b.learned_skills),
      (len(a.learned_skills), len(b.learned_skills)))

print("\n[4차에서 터졌던 필드도 같이 지킨다]")
p = make("도적", 15, live_wiring=True)
p.relics = ["relic_priest_remains"]
a, b = both(p)
check("job이 비어 있지 않다", a.job == "도적", a.job)
check("relics가 전달된다", list(a.relics) == ["relic_priest_remains"], a.relics)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
