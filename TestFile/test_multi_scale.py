# -*- coding: utf-8 -*-
"""
test_multi_scale.py — 일반 다대일의 "튜너 우회 + 가산 배율" 계약 고정 (BALANCE_PATCH_12.md)

무엇을 지키는가:
  1. `_make_enemies`가 **n == 1이면 튜너, n >= 2면 등급 팩토리**를 쓴다.
     (다대일에서 튜너를 다시 켜면 1v2/1v3이 전 직업 0%로 돌아간다 — 측정으로 확인.)
  2. n >= 2에서도 **예열(prewarm)은 걸린다** — 안 걸면 그 몬스터를 나중에 1v1로
     만날 때 2초 폴백에 걸린다.
  3. `_multi_stat_scale`은 **1.0을 넘는 가산**을 돌려준다(할인이 아니다). 레벨이
     오를수록 줄어든다 — `_level_curve_mult`가 이미 레벨당 +6%를 올려 주기 때문.
  4. `_apply_stat_scale`이 **1.0 초과 배율을 실제로 적용**한다. 예전엔 `scale >= 1.0`
     조기 반환이 있어서 가산이 통째로 무시됐다.
  5. 엘리트는 이 경로를 쓰지 않는다 — `ELITE_STAT_SCALE`(할인)이 그대로다.

DB를 쓰지 않는다(BalanceHook은 가짜 객체로 대체).

실행: python3 TestFile/test_multi_scale.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.Map import (
    _multi_stat_scale, _apply_stat_scale, _make_enemies,
    STAT_SCALE, ELITE_STAT_SCALE, NORMAL_GRADE_POOL, NORMAL_GRADE_3,
)

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}" + (f"  → {extra}" if extra != "" else ""))


class _Snap:
    def __init__(self, **kw):
        self.hp = self.maxhp = 100.0
        self.stg = self.sp = self.arm = self.sparm = 10.0
        self.name = "적"
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeHook:
    """get_enemy / make_graded_enemy / prewarm 호출만 기록하는 가짜 훅."""
    def __init__(self):
        self.tuned_calls = []
        self.graded_calls = []
        self.prewarm_calls = []

    def get_enemy(self, enemy_type, difficulty=None, chapter=1):
        self.tuned_calls.append((enemy_type, difficulty, chapter))
        return _Snap(name=enemy_type)

    def make_graded_enemy(self, enemy_type, grade="중"):
        self.graded_calls.append((enemy_type, grade))
        return _Snap(name=enemy_type)

    def prewarm(self, enemy_type, chapter=1):
        self.prewarm_calls.append((enemy_type, chapter))

    def make_battle_unit(self, snap):
        return snap


print("[1] 경로 분기 — 단독은 튜너, 다대일은 등급 팩토리")
h = _FakeHook()
_make_enemies(h, 1, NORMAL_GRADE_POOL, chapter=1, layer=1)
check("n=1 → 튜너 1회, 등급 팩토리 0회",
      len(h.tuned_calls) == 1 and len(h.graded_calls) == 0,
      (h.tuned_calls, h.graded_calls))
check("n=1은 예열을 따로 안 부른다 (get_enemy가 겸한다)", h.prewarm_calls == [], h.prewarm_calls)

for n, pool in ((2, NORMAL_GRADE_POOL), (3, NORMAL_GRADE_3)):
    h = _FakeHook()
    _make_enemies(h, n, pool, chapter=2, layer=5)
    check(f"n={n} → 등급 팩토리 {n}회, 튜너 0회",
          len(h.graded_calls) == n and len(h.tuned_calls) == 0,
          (h.graded_calls, h.tuned_calls))
    check(f"n={n} → 예열 {n}회 (나중의 1v1이 폴백에 안 걸리게)",
          len(h.prewarm_calls) == n, h.prewarm_calls)
    check(f"n={n} 등급은 해당 풀에서만 나온다",
          all(g in pool for _, g in h.graded_calls), h.graded_calls)

h = _FakeHook()
_make_enemies(h, 3, NORMAL_GRADE_3, chapter=1, layer=1)
check("3마리 풀은 「상」을 안 뽑는다 (NORMAL_GRADE_3)",
      all(g != "상" for _, g in h.graded_calls), h.graded_calls)

print("\n[2] 배율은 할인이 아니라 가산이다")
check("n=1은 보정 없음", _multi_stat_scale(10, 1) == 1.0, _multi_stat_scale(10, 1))
for lv in (1, 5, 10, 15, 20, 25):
    for n in (2, 3):
        check(f"Lv{lv} {n}마리 배율 >= 1.0", _multi_stat_scale(lv, n) >= 1.0,
              _multi_stat_scale(lv, n))
check("예전 STAT_SCALE은 할인이었다 (대조 — 엘리트용으로 남는다)",
      STAT_SCALE[2] < 1.0 and STAT_SCALE[3] < 1.0, STAT_SCALE)

s2 = [_multi_stat_scale(lv, 2) for lv in (1, 5, 10, 15, 20, 25)]
s3 = [_multi_stat_scale(lv, 3) for lv in (1, 5, 10, 15, 20, 25)]
check("2마리 배율은 레벨과 함께 단조 감소", all(a >= b for a, b in zip(s2, s2[1:])), s2)
check("3마리 배율은 레벨과 함께 단조 감소", all(a >= b for a, b in zip(s3, s3[1:])), s3)
check("같은 레벨에서 2마리 배율 > 3마리 배율 (3마리 풀이 「상」을 금지해 더 약하다)",
      all(a > b for a, b in zip(s2, s3)), list(zip(s2, s3)))

print("\n[3] ★ 가산이 실제로 적용된다 (예전엔 scale>=1.0에서 조기 반환했다)")
e = _Snap()
_apply_stat_scale([e], 1.5)
check("hp가 1.5배가 된다", e.hp == 150 and e.maxhp == 150, (e.hp, e.maxhp))
check("stg/arm도 1.5배", e.stg == 15.0 and e.arm == 15.0, (e.stg, e.arm))
e = _Snap()
_apply_stat_scale([e], 1.0)
check("정확히 1.0이면 아무것도 안 한다", e.hp == 100 and e.stg == 10.0, (e.hp, e.stg))
e = _Snap()
_apply_stat_scale([e], 0.8)
check("할인도 그대로 동작한다 (엘리트 경로)", e.hp == 80 and e.stg == 8.0, (e.hp, e.stg))

print("\n[4] 엘리트는 이 경로를 쓰지 않는다")
check("ELITE_STAT_SCALE은 여전히 할인이다",
      ELITE_STAT_SCALE[2] < 1.0, ELITE_STAT_SCALE)
check("엘리트 2마리 할인이 일반 2마리 가산과 다르다 (같은 값이면 배선이 섞인 것)",
      ELITE_STAT_SCALE[2] != _multi_stat_scale(10, 2))

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
