# -*- coding: utf-8 -*-
"""
test_multi_hit_resolution.py — 연속공격류 개별 타격 판정 회귀 테스트

검증:
  · 연속공격1=2타 / 연속공격2=3타 개별 판정 (타별 로그)
  · 타별 회피 가능 (1타 명중 / 2타 회피)
  · 타별 실드 감소 / 타별 원소 반응(얼음 슬라임 파쇄 반복)
  · 사망 시 재타겟팅 / 살아있는 적 없으면 중단
  · MP 1회 소모 / skills_used +1 / 전사 카운트 = 수행 타격 수
  · multi_shield 스킬 1회당 1번
  · RL 로그 multi_hit 상세 구조

실행: python3 test_multi_hit_resolution.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def mk_player(job="전사", skills=None, mp=300):
    return EntitySnapshot(
        name="테스트", hp=1000, maxhp=1000, mp=mp, maxmp=mp,
        stg=50, arm=20, sparm=10, sp=10, luc=10, lv=10, spd=99.0,
        job=job, learned_skills=list(skills or ["연속공격1", "연속공격2"]), items=[])


def mk_enemy(name="더미", hp=100000, luc=0, etype="고블린", shield=0.0):
    e = EntitySnapshot(
        name=name, hp=hp, maxhp=hp, mp=0, maxmp=0,
        stg=1, arm=0, sparm=0, sp=0, luc=luc, lv=1, spd=1.0,
        enemy_type=etype)
    e.shield = shield
    return e


def hit_lines(msgs):
    return [m for m in msgs if m and m[0].isdigit() and "타:" in m]


def main():
    print("=" * 56)
    print(" Multi-hit 개별 타격 판정 회귀 테스트")
    print("=" * 56)

    print("\n[1] 타격 수만큼 개별 판정")
    p = mk_player()
    bs = BattleSession(p, enemies=[mk_enemy()])
    r = bs.step("skill:연속공격1")
    lines = hit_lines(r["messages"])
    check("연속공격1 = 2타 개별 로그", len(lines) == 2, str(lines))
    check("총합 메시지 존재", any(m.startswith("총 ") for m in r["messages"]))
    check("MP 1회만 소모 (300-8=292)", abs(bs.player.mp - 292) < 0.5,
          f"mp={bs.player.mp}")
    check("skills_used = 1", bs.skills_used == 1)

    p2 = mk_player()
    bs2 = BattleSession(p2, enemies=[mk_enemy()])
    r2 = bs2.step("skill:연속공격2")
    check("연속공격2 = 3타 개별 로그", len(hit_lines(r2["messages"])) == 3,
          str(hit_lines(r2["messages"])))

    print("\n[2] 타별 회피 (randint 결정론화)")
    import ai.battle.Damage as DMG
    orig = DMG.randint
    calls = {"n": 0}

    def fake(a, b):
        if (a, b) == (1, 100):          # 회피 판정만 가로챔
            calls["n"] += 1
            return 100 if calls["n"] == 1 else 1   # 1타 명중, 이후 회피
        return orig(a, b)

    p3 = mk_player()
    e3 = mk_enemy(luc=150)
    e3.dodge_bonus = 1.0                 # 회피율 상한(60%)까지 확보
    bs3 = BattleSession(p3, enemies=[e3])
    DMG.randint = fake
    try:
        r3 = bs3.step("skill:연속공격1")
    finally:
        DMG.randint = orig
    lines3 = hit_lines(r3["messages"])
    check("1타 명중 / 2타 회피", len(lines3) == 2 and "회피" in lines3[1],
          str(lines3))

    print("\n[3] 타별 실드 감소")
    p4 = mk_player()
    e4 = mk_enemy(shield=100)            # 1타에 일부, 2타에 깨짐
    bs4 = BattleSession(p4, enemies=[e4])
    r4 = bs4.step("skill:연속공격1")
    mh = bs4.rl_log[0]["result"]["multi_hit"]["hits"]
    check("1타 실드 흡수 기록", mh[0]["shield_damage"] > 0, str(mh[0]))
    check("2타에서 실드 깨지고 HP 피해", mh[1]["damage"] > 0, str(mh[1]))
    check("총 실드 피해 = 100 (전량 소진)",
          sum(h["shield_damage"] for h in mh) == 100,
          str([h["shield_damage"] for h in mh]))

    print("\n[4] 타별 원소 반응 — 빙결 슬라임 파쇄 반복")
    p5 = mk_player()
    e5 = mk_enemy(name="빙결 슬라임", etype="빙결 슬라임")
    e5.element_queue = ["ice"]
    bs5 = BattleSession(p5, enemies=[e5])
    r5 = bs5.step("skill:연속공격1")
    mh5 = bs5.rl_log[0]["result"]["multi_hit"]["hits"]
    reacted = [h for h in mh5 if h["reaction"]]
    check("파쇄가 2타 모두 발동 (innate 큐 유지)", len(reacted) == 2,
          f"reactions={[h['reaction'] for h in mh5]}, queue={e5.element_queue}")
    check("반응 후 innate 큐 복구 (ice)", e5.element_queue == ["ice"],
          str(e5.element_queue))

    print("\n[5] 사망 시 재타겟팅")
    p6 = mk_player()
    weak = mk_enemy(name="약한놈", hp=10)
    strong = mk_enemy(name="강한놈", hp=100000)
    bs6 = BattleSession(p6, enemies=[weak, strong])
    r6 = bs6.step("skill:연속공격1:0")    # 약한놈 지정
    mh6 = bs6.rl_log[0]["result"]["multi_hit"]
    check("1타로 약한놈 처치", mh6["hits"][0]["killed"] is True, str(mh6["hits"][0]))
    check("2타는 강한놈에게 재타겟", mh6["hits"][1]["target_name"] == "강한놈",
          str(mh6["hits"][1]))
    check("retargeted = True", mh6["retargeted"] is True)

    print("\n[6] 살아있는 적 없으면 중단")
    p7 = mk_player()
    solo = mk_enemy(name="솔로", hp=10)
    bs7 = BattleSession(p7, enemies=[solo])
    cnt_before = getattr(bs7, "_warrior_attack_count", 0)
    r7 = bs7.step("skill:연속공격1")
    mh7 = bs7.rl_log[0]["result"]["multi_hit"]
    check("1타 처치 후 2타 중단 (hits 1개만)", len(mh7["hits"]) == 1, str(mh7))
    check("중단된 타는 전사 카운트 제외 (+1만)",
          getattr(bs7, "_warrior_attack_count", 0) - cnt_before == 1,
          f"count diff={getattr(bs7, '_warrior_attack_count', 0) - cnt_before}")

    print("\n[7] 전사 카운트 = 수행 타격 수")
    p8 = mk_player()
    bs8 = BattleSession(p8, enemies=[mk_enemy()])
    bs8.step("skill:연속공격1")
    check("2타 수행 → 카운트 +2", getattr(bs8, "_warrior_attack_count", 0) == 2,
          str(getattr(bs8, "_warrior_attack_count", 0)))

    print("\n[8] multi_shield — 스킬 1회당 1번")
    p9 = mk_player()
    bs9 = BattleSession(p9, enemies=[mk_enemy(), mk_enemy(name="더미2")])
    bs9.step("skill:연속공격1")
    check("1v2 사용 → 실드 60 (1번만, 타별 아님)",
          abs(bs9.player.shield - 60) < 1.0, f"shield={bs9.player.shield}")

    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()