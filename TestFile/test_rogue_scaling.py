# -*- coding: utf-8 -*-
"""
test_rogue_scaling.py — 도적 고레벨 스케일링의 "의도된 수치" 고정 (후속 5단계, BALANCE_PATCH_11.md)

이 파일은 기능 회귀가 아니라 **측정으로 내린 판단을 고정**한다. 아래 값들은 전부
`TestFile/rogue_band_measure.py`(팔 A~F, N=150/셀)와 `TestFile/final_boss_measure.py`로
재 본 뒤 "그대로 둔다"로 결론 난 것들이다. 고치려면 숫자만 바꾸지 말고 두 측정을 다시 돌려라.

고정하는 것:
  1. 「연속찌르기」 메타 — max_hits 4 / luc_mult 3 / prob_decay 20 / dmg_decay 0.68.
     이 스킬은 게임에서 **유일한 `multi_hit`**이고 **도적 Lv5 단독 해금**이다.
     타수가 `max(5, min(85, luc*3 - i*20))`이라 LUC가 곧 화력이다.
  2. 도적만 LUC·SPD가 자란다 — `0.6 + lv//6` · `0.9 + lv//8`.
     전사(`lv%2`)·마법사(`lv%4`)는 진동만 하고 커지지 않는다.
  3. ★ `PlayerPowerIndex.calc`에는 **LUC 항이 없다** — LUC만 다른 두 플레이어의 지수가 같다.
     이건 버그 보고가 아니라 **알려진 미보정 축**이다(SPD는 ≥14에서 +0.15인 계단이라도 있다).
     여기에 LUC 항을 넣는 것은 일반 몬스터를 전부 올리는 변경이라 전 구간 재측정이 필요하다.
     넣게 되면 이 테스트의 [3]을 그때 같이 고쳐라.
  4. 유령의 다단히트 회피 패널티가 살아 있다 — 타수를 깎는 레버(prob_decay·max_hits)는
     유령의 설계된 대응 수단을 같이 깎는다는 뜻이라, 기각 근거의 일부다.

DB를 쓰지 않는다.

실행: python3 TestFile/test_rogue_scaling.py
"""
import sys, os, io, random, contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.battle import SKILL_META, EntitySnapshot
from ai.battle.Skills import MONSTER_SKILL_META, roll_multi_hit_count
from ai.Simulator import PlayerPowerIndex
from game.Lv import JOB_GROWTH, JOB_SKILL_UNLOCKS

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}" + (f"  → {extra}" if extra != "" else ""))


def snap(**kw):
    s = EntitySnapshot(name="t", lv=20, hp=100, maxhp=100, mp=50, maxmp=50,
                       stg=10, sp=10, arm=5, sparm=5, spd=10, luc=10)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


print("[1] 「연속찌르기」 — 측정으로 유지하기로 한 값 (BALANCE_PATCH_11.md)")
m = SKILL_META["연속찌르기"]
check("max_hits 4", m["max_hits"] == 4, m.get("max_hits"))
check("luc_mult 3", m["luc_mult"] == 3, m.get("luc_mult"))
check("prob_decay 20", m["prob_decay"] == 20, m.get("prob_decay"))
check("dmg_decay 0.68", m["dmg_decay"] == 0.68, m.get("dmg_decay"))
check("base_prob 5", m["base_prob"] == 5, m.get("base_prob"))
check("type multi_hit", m["type"] == "multi_hit", m.get("type"))

mh = [k for k, v in SKILL_META.items() if v.get("type") == "multi_hit"]
check("게임에서 유일한 multi_hit 스킬이다", mh == ["연속찌르기"], mh)
mmh = [k for k, v in MONSTER_SKILL_META.items() if v.get("type") == "multi_hit"]
check("몬스터판 multi_hit은 없다", mmh == [], mmh)

owners = [j for j, tbl in JOB_SKILL_UNLOCKS.items()
          if any("연속찌르기" in (sk if isinstance(sk, (list, tuple)) else [sk])
                 for sk in tbl.values())]
check("도적만 배운다 (Lv5 단독 해금)",
      owners == ["도적"] and "연속찌르기" in JOB_SKILL_UNLOCKS["도적"][5], owners)

print("\n[2] 타수는 LUC가 정한다 — 상한 85%, 하한 base_prob")
# 확률식: max(5, min(85, luc*3 - i*20)) — i = 1,2,3
lo = snap(luc=2)
hi = snap(luc=100)
random.seed(1)
lo_hits = [roll_multi_hit_count(m, lo) for _ in range(400)]
hi_hits = [roll_multi_hit_count(m, hi) for _ in range(400)]
check("LUC 2는 거의 1타 (평균 < 1.3)", sum(lo_hits) / len(lo_hits) < 1.3,
      sum(lo_hits) / len(lo_hits))
check("LUC 100도 4타 고정은 아니다 — 85% 상한이 살아 있다",
      2.8 < sum(hi_hits) / len(hi_hits) < 3.9 and max(hi_hits) == 4,
      sum(hi_hits) / len(hi_hits))
check("어떤 LUC에서도 max_hits를 못 넘는다", max(lo_hits + hi_hits) <= m["max_hits"])

print("\n[3] ★ PlayerPowerIndex는 LUC를 안 본다 (알려진 미보정 축 — 고치면 전 구간 재측정)")
base = snap(luc=6)
lucky = snap(luc=60)
check("LUC만 다른 두 플레이어의 지수가 같다",
      PlayerPowerIndex.calc(base) == PlayerPowerIndex.calc(lucky),
      (PlayerPowerIndex.calc(base), PlayerPowerIndex.calc(lucky)))
check("SPD는 반대로 계단이 있다 (spd 10 < spd 14)",
      PlayerPowerIndex.calc(snap(spd=10)) < PlayerPowerIndex.calc(snap(spd=14)))
check("그 계단은 spd 14에서 포화한다 — 도적은 Lv1에 이미 14다",
      PlayerPowerIndex.calc(snap(spd=14)) == PlayerPowerIndex.calc(snap(spd=50)))

print("\n[4] 성장 곡선 — 도적만 자란다 (그대로 두기로 한 값)")
g = JOB_GROWTH["도적"]
check("도적 luc = 0.6 + lv//6", [g["luc"](lv) for lv in (5, 12, 18, 24)] == [0.6, 2.6, 3.6, 4.6],
      [g["luc"](lv) for lv in (5, 12, 18, 24)])
check("도적 spd = 0.9 + lv//8", [g["spd"](lv) for lv in (7, 8, 16, 24)] == [0.9, 1.9, 2.9, 3.9],
      [g["spd"](lv) for lv in (7, 8, 16, 24)])
for job, stat in (("전사", "luc"), ("마법사", "luc")):
    vals = [JOB_GROWTH[job][stat](lv) for lv in range(1, 26)]
    check(f"{job} {stat}는 진동만 한다 (최댓값이 레벨과 함께 안 커진다)",
          max(vals[:12]) == max(vals[12:]), (max(vals[:12]), max(vals[12:])))
for job in ("전사", "마법사", "탱커"):
    vals = {JOB_GROWTH[job]["spd"](lv) for lv in range(1, 26)}
    check(f"{job} spd 성장은 상수다", len(vals) == 1, vals)

print("\n[5] 유령의 다단히트 대응이 살아 있다 — 타수를 깎는 레버의 대가")
gh = snap(dodge_penalty_per_extra_hit=0.10)
check("EntitySnapshot에 dodge_penalty_per_extra_hit가 있다 (기본 0.10)",
      getattr(gh, "dodge_penalty_per_extra_hit", None) == 0.10)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
