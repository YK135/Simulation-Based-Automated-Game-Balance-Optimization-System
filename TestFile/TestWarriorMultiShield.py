# -*- coding: utf-8 -*-
"""
test_warrior_multi_shield.py — 전사 연속공격1 다대일 조건부 실드 회귀 테스트

검증:
  · 적 2마리 이상일 때만 발동 (1대1은 미발동)
  · 실드량 maxhp 6%, 누적 cap maxhp 12%
  · 전사 전용 (다른 직업 미발동)
  · 명중/회피 무관하게 스킬 사용 성공 시 1회 부여
  · 데미지 계수 무변경 (mult 0.80 / hits 2)
  · 로그 메시지 포함

실행: python3 test_warrior_multi_shield.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, SKILL_META

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def make_player(job="전사", maxhp=1000):
    return EntitySnapshot(
        name="테스트전사", hp=maxhp, maxhp=maxhp, mp=300, maxmp=300,
        stg=50, arm=20, sparm=10, sp=10, luc=10, lv=10, spd=99.0,
        job=job, learned_skills=["연속공격1"], items=[])


def make_dummies(n, hp=100000):
    out = []
    for i in range(n):
        out.append(EntitySnapshot(
            name=f"더미{i+1}", hp=hp, maxhp=hp, mp=0, maxmp=0,
            stg=1, arm=0, sparm=0, sp=0, luc=0, lv=1, spd=1.0,
            enemy_type="고블린"))
    return out


def use_skill(job, n_enemies, times=1):
    """스킬을 times회 사용 — (플레이어, 마지막 메시지)"""
    p = make_player(job=job)
    bs = BattleSession(p, enemies=make_dummies(n_enemies))
    msgs = []
    for _ in range(times):
        # 플레이어 차례가 아니면 적 턴 소화
        guard = 0
        while bs._peek_next_actor()[0] != "player" and not bs.done and guard < 10:
            bs.step("auto")
            guard += 1
        if bs.done:
            break
        r = bs.step("skill:연속공격1")
        msgs = r.get("messages", [])
    return bs.player, msgs


def main():
    print("=" * 52)
    print(" 전사 연속공격1 다대일 실드 회귀 테스트")
    print("=" * 52)

    print("\n[메타 정의]")
    meta = SKILL_META["연속공격1"]
    check("multi_shield = 6%", meta.get("multi_shield") == 0.06, str(meta.get("multi_shield")))
    check("multi_shield_cap = 12%", meta.get("multi_shield_cap") == 0.12)
    check("데미지 계수 무변경 (mult 0.80 / hits 2)",
          meta.get("mult") == 0.80 and meta.get("hits") == 2,
          f"mult={meta.get('mult')}, hits={meta.get('hits')}")
    check("ATB 추가 효과 없음", "atb_gain" not in meta and "atb_bonus" not in meta)

    print("\n[발동 조건 — 적 2마리 이상]")
    pl, _ = use_skill("전사", 1)
    check("1대1: 실드 미발동 (0)", pl.shield == 0, f"shield={pl.shield}")
    pl, _ = use_skill("전사", 2)
    check("1대2: 실드 6% (60)", abs(pl.shield - 60) < 1.0, f"shield={pl.shield}")
    pl, _ = use_skill("전사", 3)
    check("1대3: 실드 6% (60)", abs(pl.shield - 60) < 1.0, f"shield={pl.shield}")

    print("\n[누적 cap 12%]")
    pl, _ = use_skill("전사", 2, times=2)
    check("2회 사용: cap 12%(120) 이하", pl.shield <= 120.1, f"shield={pl.shield}")
    pl, _ = use_skill("전사", 2, times=5)
    check("5회 사용해도 cap 초과 없음", pl.shield <= 120.1, f"shield={pl.shield}")

    print("\n[직업 제한]")
    for job in ["도적", "마법사", "탱커"]:
        pl, _ = use_skill(job, 2)
        check(f"{job}: 실드 미발동", pl.shield == 0, f"shield={pl.shield}")

    print("\n[로그 메시지]")
    pl, msgs = use_skill("전사", 2)
    check("다대일 실드 메시지(🛡) 포함",
          any("🛡" in m and "다대일" in m for m in msgs),
          str([m for m in msgs if "🛡" in m]))

    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()