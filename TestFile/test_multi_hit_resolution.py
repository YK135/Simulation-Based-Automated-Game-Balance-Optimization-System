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
  · 연속찌르기(multi_hit 타입)도 같은 타격별 경로 — 예전엔 execute_skill이
    합계 한 개만 돌려줘서 로그가 "연속찌르기 사용 → N 데미지" 한 줄이었다
  · 타별 감쇠(dmg_decay 0.68) / 주사위 6의 ATB +20은 스킬당 1회
  · 메시지가 프론트 분류기(BattleSequencer._classifyMessages)가 읽는 형식인지
    — "사용" 선언 + "N타: ...에게 N 피해" + "총 N 피해". 이 형식이 깨지면
    데미지 숫자 팝업/피격 모션이 조용히 사라진다(실제로 발생했던 버그)

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
    bs4.step("skill:연속공격1")
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
    bs5.step("skill:연속공격1")
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
    bs6.step("skill:연속공격1:0")    # 약한놈 지정
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
    bs7.step("skill:연속공격1")
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

    print("\n[9] 연속찌르기(multi_hit)도 타격별 경로를 탄다")
    # ★ 예전엔 multi_hit 타입이 이 경로를 안 타서 execute_skill의 합계 한 개만
    #   나왔다 — 로그가 "연속찌르기 사용 → N 데미지" 한 줄(전사는 타별).
    # ★ Player_Actions가 `from ai.battle import roll_multi_hit_count`로 이름을
    #   바인딩해 두므로, ai.battle.Skills 쪽을 갈아도 안 먹는다 — 호출부 모듈의
    #   이름을 패치해야 한다.
    import ai.battle_session.Player_Actions as PA
    p10 = mk_player(job="도적", skills=["연속찌르기"])
    # ★ luc=0 — 크리(luc×0.5%)가 한 타에만 터지면 감쇠 단조성이 깨져
    #   [10]이 ~14% 확률로 간헐 실패한다. multi_hit은 skill_mult 1.0 고정이고
    #   luc_bonus도 없어서 luc을 0으로 둬도 감쇠 검증에 영향이 없다.
    p10.luc = 0
    bs10 = BattleSession(p10, enemies=[mk_enemy()])
    bs10.player.luc = 0
    orig_roll = PA.roll_multi_hit_count
    PA.roll_multi_hit_count = lambda meta, atk: 3          # 타수 고정
    try:
        r10 = bs10.step("skill:연속찌르기")
    finally:
        PA.roll_multi_hit_count = orig_roll
    lines10 = hit_lines(r10["messages"])
    check("3타 개별 로그", len(lines10) == 3, str(lines10))
    check("선언에 타수 표기", any("연속찌르기 사용!" in m and "(3타!)" in m
                                 for m in r10["messages"]),
          str([m for m in r10["messages"] if "연속찌르기" in m]))
    check("총합 메시지 존재", any(m.startswith("총 ") for m in r10["messages"]))
    check("MP 1회만 소모 (300-14=286)", abs(bs10.player.mp - 286) < 0.5,
          f"mp={bs10.player.mp}")
    check("RL 로그 multi_hit 상세 기록",
          bs10.rl_log and bs10.rl_log[0]["result"].get("multi_hit") is not None)

    print("\n[10] 타별 감쇠 (dmg_decay 0.68)")
    mh10 = bs10.rl_log[0]["result"]["multi_hit"]["hits"]
    dmgs = [h["damage"] for h in mh10 if not h["dodge"]]
    check("타가 갈수록 피해 감소", len(dmgs) == 3 and dmgs[0] > dmgs[1] > dmgs[2],
          str(dmgs))
    # 0.68^1 = 0.68, 0.68^2 = 0.4624 — 난수 폭(0.9~1.1)을 감안해 넉넉히 검사
    check("2타/1타 비율이 0.68 근방", 0.50 < dmgs[1] / dmgs[0] < 0.90,
          f"ratio={dmgs[1] / dmgs[0]:.3f} dmgs={dmgs}")
    check("3타/1타 비율이 0.46 근방", 0.33 < dmgs[2] / dmgs[0] < 0.65,
          f"ratio={dmgs[2] / dmgs[0]:.3f} dmgs={dmgs}")

    print("\n[11] 주사위 6의 ATB +20은 스킬당 1회 (타별 아님)")
    # 타마다 주면 4타에 ATB +80이 되어 도적 턴이 폭주한다.
    p11 = mk_player(job="도적", skills=["연속찌르기"])
    bs11 = BattleSession(p11, enemies=[mk_enemy()])
    orig_dice = PA.PlayerActionsMixin._roll_rogue_dice
    PA.PlayerActionsMixin._roll_rogue_dice = lambda self, msgs: {
        "mult": 1.0, "force_crit": True, "bleed": False, "value": 6}
    PA.roll_multi_hit_count = lambda meta, atk: 4
    atb_before = bs11.player_atb
    try:
        r11 = bs11.step("skill:연속찌르기")
    finally:
        PA.PlayerActionsMixin._roll_rogue_dice = orig_dice
        PA.roll_multi_hit_count = orig_roll
    gained = bs11.player_atb - atb_before
    check("4타여도 ATB 보너스 메시지 1번",
          sum(1 for m in r11["messages"] if "ATB +20" in m) == 1,
          str([m for m in r11["messages"] if "ATB" in m]))
    check("치명타 확정 메시지도 1번",
          sum(1 for m in r11["messages"] if "치명타 확정" in m) == 1,
          str([m for m in r11["messages"] if "치명타 확정" in m]))
    check("4타 전부 치명타 처리", len(hit_lines(r11["messages"])) == 4
          and all("치명타" in m for m in hit_lines(r11["messages"])),
          str(hit_lines(r11["messages"])))

    print("\n[12] 프론트 분류기가 읽는 메시지 형식 유지")
    # BattleSequencer._classifyMessages가 damage 그룹으로 넣는 조건:
    #   "에게" + ("데미지" 또는 "피해")  /  "총 ...피해"
    # player 그룹 조건: "사용" 포함. 둘 중 하나라도 어긋나면 팝업이 사라진다.
    for label, msgs in (("연속공격1", BattleSession(mk_player(), enemies=[mk_enemy()])
                                        .step("skill:연속공격1")["messages"]),
                        ("연속찌르기", r10["messages"])):
        hits_ok = [m for m in msgs if "에게" in m and ("피해" in m or "데미지" in m)]
        total_ok = [m for m in msgs if m.startswith("총 ") and "피해" in m]
        decl_ok = [m for m in msgs if "사용" in m]
        check(f"{label}: 타격 줄이 damage 조건 충족", len(hits_ok) >= 1, str(msgs))
        check(f"{label}: 합계 줄이 damage 조건 충족", len(total_ok) == 1, str(msgs))
        check(f"{label}: 선언 줄이 player 조건('사용') 충족", len(decl_ok) >= 1, str(msgs))

    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()