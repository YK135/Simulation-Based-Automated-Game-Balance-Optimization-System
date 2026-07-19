# -*- coding: utf-8 -*-
"""
test_warrior_slash_shield.py — 전사 슬래시1/2 광역 실드 회귀 테스트

검증:
  · 슬래시1: 명중 1/2/3명 → 실드 maxhp 5%/10%/15%, cap 15%
  · 슬래시2: 명중 1/2/3명 → 실드 maxhp 7%/14%/21%, cap 21%
  · 비전사 직업은 같은 메타로도 실드 미부여
  · 회피(데미지 0) 대상은 명중 수에 미포함
  · 로그에 실드 획득 메시지(🛡) 포함

실행: python3 test_warrior_slash_shield.py
"""
import sys

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot

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


def make_warrior(maxhp=1000, job="전사", skills=None):
    return EntitySnapshot(
        name="테스트전사", hp=maxhp, maxhp=maxhp, mp=200, maxmp=200,
        stg=50, arm=20, sparm=10, sp=10, luc=10, lv=10, spd=99.0,
        job=job,
        learned_skills=list(skills or ["슬래시1", "슬래시2"]),
        items=[])


def make_dummy(n=1, hp=100000, luc=0):
    """회피 불가(luc=0) 더미 적 n마리. HP를 크게 잡아 안 죽게."""
    out = []
    for i in range(n):
        out.append(EntitySnapshot(
            name=f"더미{i+1}", hp=hp, maxhp=hp, mp=0, maxmp=0,
            stg=1, arm=0, sparm=0, sp=0, luc=luc, lv=1, spd=1.0,
            enemy_type="고블린"))
    return out


def run_slash(job, skill, n_enemies, dodge_all_but_first=False):
    """전사(또는 다른 직업)가 슬래시를 1회 시전 — (플레이어 스냅, 메시지) 반환.

    dodge_all_but_first=True면 Damage 모듈의 randint를 몽키패치해
    첫 대상만 명중, 나머지는 확정 회피로 결정론화한다.
    (게임 회피율 상한이 60%라 스탯만으로는 확정 회피가 불가능)
    """
    p = make_warrior(job=job)
    enemies = make_dummy(n_enemies)
    if dodge_all_but_first:
        for e in enemies[1:]:
            e.luc = 150
            e.dodge_bonus = 1.0   # 회피율 상한 60%까지 확보

        import ai.battle.Damage as DMG
        orig = DMG.randint
        calls = {"n": 0}

        def fake_randint(a, b):
            # 회피 판정 호출(1..100)만 가로챔: 첫 호출=첫 대상 명중(100),
            # 이후 호출=회피(1 → evade 60 이하이므로 회피 성공)
            if (a, b) == (1, 100):
                calls["n"] += 1
                return 100 if calls["n"] == 1 else 1
            return orig(a, b)

        DMG.randint = fake_randint
        try:
            bs = BattleSession(p, enemies=enemies)
            r = bs.step(f"skill:{skill}")
        finally:
            DMG.randint = orig
        return bs.player, r.get("messages", [])

    bs = BattleSession(p, enemies=enemies)
    r = bs.step(f"skill:{skill}")
    return bs.player, r.get("messages", [])


def main():
    print("=" * 52)
    print(" 전사 슬래시 실드 회귀 테스트")
    print("=" * 52)

    print("\n[슬래시1 — 5%/명중, cap 15%]")
    for n, expect in [(1, 0.05), (2, 0.10), (3, 0.15)]:
        pl, msgs = run_slash("전사", "슬래시1", n)
        want = pl.maxhp * expect
        check(f"적 {n}명 명중 → 실드 {int(expect*100)}%",
              abs(pl.shield - want) < 1.0,
              f"shield={pl.shield:.1f}, want={want:.1f}")
    # cap: 4명 명중해도 15%
    pl, _ = run_slash("전사", "슬래시1", 4)
    check("4명 명중해도 cap 15%",
          abs(pl.shield - pl.maxhp * 0.15) < 1.0, f"shield={pl.shield:.1f}")

    print("\n[슬래시2 — 7%/명중, cap 21%]")
    for n, expect in [(1, 0.07), (2, 0.14), (3, 0.21)]:
        pl, msgs = run_slash("전사", "슬래시2", n)
        want = pl.maxhp * expect
        check(f"적 {n}명 명중 → 실드 {int(expect*100)}%",
              abs(pl.shield - want) < 1.0,
              f"shield={pl.shield:.1f}, want={want:.1f}")
    pl, _ = run_slash("전사", "슬래시2", 4)
    check("4명 명중해도 cap 21%",
          abs(pl.shield - pl.maxhp * 0.21) < 1.0, f"shield={pl.shield:.1f}")

    print("\n[비전사 직업 — 실드 미부여]")
    for job in ["도적", "마법사", "탱커"]:
        pl, _ = run_slash(job, "슬래시1", 2)
        check(f"{job}: 슬래시1 사용해도 실드 0",
              pl.shield == 0, f"shield={pl.shield:.1f}")

    print("\n[회피 대상은 명중 수 미포함]")
    # 3마리 중 2마리(첫 대상 제외)가 확정 회피 → 명중 1명 = 실드 5%만
    pl, msgs = run_slash("전사", "슬래시1", 3, dodge_all_but_first=True)
    check("3마리 중 2마리 회피 → 명중 1명 실드 5%",
          abs(pl.shield - pl.maxhp * 0.05) < 1.0,
          f"shield={pl.shield:.1f} (10~15%면 회피가 명중으로 계산된 것)")

    print("\n[로그 메시지]")
    pl, msgs = run_slash("전사", "슬래시1", 2)
    check("실드 획득 메시지(🛡) 포함",
          any("🛡" in m and "실드" in m for m in msgs),
          f"msgs={[m for m in msgs if '실드' in m or '🛡' in m]}")
    check("메시지에 명중 수 표기 (2명 명중)",
          any("2명 명중" in m for m in msgs))

    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()