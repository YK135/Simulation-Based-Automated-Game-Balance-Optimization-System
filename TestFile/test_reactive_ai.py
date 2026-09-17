# -*- coding: utf-8 -*-
"""
test_reactive_ai.py — 측정용 PlayerAI 모드 "reactive" 회귀 테스트 (Combat Brief 11-1 3-3)

검증:
  · 반응 가점 표 — ice+물리 1.2 / ice+fire 1.5 / fire+lightning 1.3 / lightning+fire 1.3 / 그 외 1.0
  · 예고 감지 — 중간 보스 예약 예고, 엘리트 박쥐·암살자 phase≠0, 엘리트 골렘 강타 대기. 비엘리트는 False
  · reactive: 예고 중이면 실드 → 회복 → 포션 → 방어 버프 순으로 선행, 할 게 없으면 평소대로
  · reactive: 적에게 붙은 원소로 반응이 나는 스킬을 고른다 (ice 보스에 파이어볼)
  · balanced: 같은 상황에서 예고를 무시하고, 반응 가점 없이 고른다 (기본 모드 불변)
  · 면역 대상 스킬은 reactive에서도 배제
  · BattleSimulator / MultiBattleSimulator에 player_ai_mode="reactive"로 바로 쓸 수 있다
DB를 쓰지 않는다.

실행: python3 TestFile/test_reactive_ai.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Auto_AI import PlayerAI, _reaction_bonus, _enemy_telegraphing, _best_attack_skill
from ai.battle import EntitySnapshot, SKILL_META, Buff
from ai.battle.EliteKit import GOLEM_PHASE_STRIKE, GOLEM_PHASE_GUARD
from ai.Simulator import BattleSimulator, MultiBattleSimulator
from game.Enemy_Class import Make_MidBoss

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def mage(hp=1000, mp=200, skills=None, items=None, shield=0.0):
    p = EntitySnapshot(name="측정", hp=hp, maxhp=1000, mp=mp, maxmp=200,
                       stg=20, arm=20, sparm=20, sp=60, luc=10, lv=15, spd=20.0, job="마법사",
                       learned_skills=list(skills or ["파이어볼1", "라이트닝1", "아이스볼릿1"]),
                       items=list(items or []))
    p.shield = shield
    return p


def boss(pending=False, element=None):
    b = EntitySnapshot.from_enemy(Make_MidBoss(15))
    b.boss_phase = 1
    if pending:
        b.boss_telegraph_at = 0
    if element:
        b.element_queue = [element]
    return b


def elite(etype, phase=0):
    e = EntitySnapshot(name=etype, hp=1000, maxhp=1000, mp=50, maxmp=50, stg=20, arm=10, sparm=10,
                       sp=10, luc=5, lv=10, spd=10.0, enemy_type=etype)
    e.is_elite = e.elite_leader = True
    e.elite_phase = phase
    return e


def main():
    print("=" * 56)
    print(" 측정용 PlayerAI 모드 reactive (3-3)")
    print("=" * 56)

    print("\n[1] 반응 가점 표")
    fb, lt, ib, st = SKILL_META["파이어볼1"], SKILL_META["라이트닝1"], SKILL_META["아이스볼릿1"], SKILL_META["강타1"]
    check("ice + 물리(강타) → 1.2 (파쇄)", _reaction_bonus(st, boss(element="ice")) == 1.2)
    check("ice + fire → 1.5 (융해)", _reaction_bonus(fb, boss(element="ice")) == 1.5)
    check("fire + lightning → 1.3 (과부하)", _reaction_bonus(lt, boss(element="fire")) == 1.3)
    check("lightning + fire → 1.3 (과부하)", _reaction_bonus(fb, boss(element="lightning")) == 1.3)
    check("fire + ice → 1.0 (반응 없음: 단방향)", _reaction_bonus(ib, boss(element="fire")) == 1.0)
    check("ice + lightning → 1.0", _reaction_bonus(lt, boss(element="ice")) == 1.0)
    check("원소 없음 → 1.0", _reaction_bonus(fb, boss()) == 1.0)
    check("defender None → 1.0", _reaction_bonus(fb, None) == 1.0)

    print("\n[2] 예고 감지")
    check("보스 예약 예고 → True", _enemy_telegraphing(boss(pending=True)) is True)
    check("보스 예고 없음 → False", _enemy_telegraphing(boss()) is False)
    check("엘리트 박쥐 phase 1/2 → True", _enemy_telegraphing(elite("박쥐", 1)) and _enemy_telegraphing(elite("박쥐", 2)))
    check("엘리트 암살자 phase 0 → False", _enemy_telegraphing(elite("암살자", 0)) is False)
    check("엘리트 골렘 강타 대기 → True / 수비 → False",
          _enemy_telegraphing(elite("골렘", GOLEM_PHASE_STRIKE)) and not _enemy_telegraphing(elite("골렘", GOLEM_PHASE_GUARD)))
    g = elite("골렘", GOLEM_PHASE_STRIKE); g.elite_leader = False
    check("비엘리트 골렘 → False", _enemy_telegraphing(g) is False)
    check("None → False", _enemy_telegraphing(None) is False)

    print("\n[3] reactive — 예고 대응 우선순위")
    ai_r, ai_b = PlayerAI("reactive"), PlayerAI("balanced")
    p = mage(skills=["파이어볼1", "실드", "힐1", "수비태세1"], items=["HP_M_potion"])
    a = ai_r.decide(p, boss(pending=True))
    check("실드 없음 → 실드", (a.action_type, a.detail) == ("skill", "실드"), a)
    p = mage(hp=800, skills=["파이어볼1", "실드", "힐1", "수비태세1"], shield=50)
    a = ai_r.decide(p, boss(pending=True))
    check("실드 있음 · HP 80% → 힐1", (a.action_type, a.detail) == ("skill", "힐1"), a)
    p = mage(hp=500, skills=["파이어볼1", "실드", "수비태세1"], items=["HP_M_potion"], shield=50)
    a = ai_r.decide(p, boss(pending=True))
    check("회복 스킬 없음 · HP 50% → HP 포션", (a.action_type, a.detail) == ("item", "HP_M_potion"), a)
    p = mage(hp=950, skills=["파이어볼1", "실드", "힐1", "수비태세1"], shield=50)
    a = ai_r.decide(p, boss(pending=True))
    check("실드 있음 · HP 95% → 방어 버프(수비태세1)", (a.action_type, a.detail) == ("skill", "수비태세1"), a)
    p.apply_buff(Buff(stat="arm", amount=0.15, turns=2, name="수비태세1"))
    a = ai_r.decide(p, boss(pending=True))
    check("전부 갖췄으면 평소대로 공격 스킬", a.action_type == "skill" and SKILL_META[a.detail]["type"] == "magical", a)
    p = mage(skills=["파이어볼1", "실드", "힐1", "수비태세1"])
    a = ai_r.decide(p, boss(pending=False))
    check("예고 없으면 실드부터 쓰지 않음 (평소 판단)", a.detail != "실드", a)
    p = mage(skills=["파이어볼1", "실드", "힐1", "수비태세1"])
    a = ai_b.decide(p, boss(pending=True))
    check("balanced는 예고를 무시 (HP 100%에서 실드 안 씀)", a.detail != "실드", a)
    p = mage(skills=["파이어볼1", "실드"], mp=50)   # MP 25% < SKILL_MP_RESERVE
    a = ai_r.decide(p, boss())
    check("reactive도 MP 기준은 balanced와 같음 (MP 25% → 공격 스킬 대신 일반공격)", a.action_type == "attack", a)

    print("\n[4] reactive — 반응 가점으로 스킬 선택")
    p = mage()
    # MP당 효율: 파이어볼1 = 60×1.5/10 = 9.0 > 라이트닝1 = 60×1.55/12 = 7.75 — 기본 모드는 항상 파이어볼1
    check("balanced: 원소 없는 보스엔 효율 최고 스킬(파이어볼1)", _best_attack_skill(p, boss()) == "파이어볼1")
    check("balanced: fire 보스에도 그대로 파이어볼1 (가점 없음)", _best_attack_skill(p, boss(element="fire")) == "파이어볼1")
    check("reactive: ice 보스엔 파이어볼1 (융해 1.5배)",
          _best_attack_skill(p, boss(element="ice"), reaction_aware=True) == "파이어볼1")
    check("reactive: fire 보스엔 라이트닝1 (과부하)",
          _best_attack_skill(p, boss(element="fire"), reaction_aware=True) == "라이트닝1")
    check("reactive: lightning 보스엔 파이어볼1 (과부하 1.3 > 라이트닝 효율 차)",
          _best_attack_skill(p, boss(element="lightning"), reaction_aware=True) == "파이어볼1")
    a = ai_r.decide(p, boss(element="fire"))
    check("decide 경로에서도 fire 보스엔 라이트닝1", (a.action_type, a.detail) == ("skill", "라이트닝1"), a)
    a = ai_b.decide(p, boss(element="fire"))
    check("balanced decide는 fire 보스에도 파이어볼1", (a.action_type, a.detail) == ("skill", "파이어볼1"), a)
    ice_slime = EntitySnapshot(name="빙결 슬라임", hp=500, maxhp=500, mp=0, maxmp=0, stg=10, arm=5, sparm=5,
                               sp=0, luc=0, lv=5, spd=5.0, enemy_type="빙결 슬라임", element_queue=["ice"])
    p2 = mage(skills=["아이스볼릿1", "파이어볼1"])
    check("면역(빙결 슬라임 + 아이스볼릿) 배제는 reactive에서도 유지",
          _best_attack_skill(p2, ice_slime, reaction_aware=True) == "파이어볼1")
    w = EntitySnapshot(name="전사", hp=1000, maxhp=1000, mp=100, maxmp=100, stg=60, arm=30, sparm=10, sp=5,
                       luc=10, lv=15, spd=15.0, job="전사", learned_skills=["강타1", "연속공격1"], items=[])
    check("물리 직업: ice 보스에서 물리 스킬은 같은 배율(1.2)로 가점 — 순위 불변",
          _best_attack_skill(w, boss(element="ice"), reaction_aware=True) == _best_attack_skill(w, boss()))

    print("\n[5] 시뮬레이터 연결")
    random.seed(1)
    p = mage()
    r = BattleSimulator(p, boss(), n=5, player_ai_mode="reactive").run()
    check("BattleSimulator(player_ai_mode='reactive') 실행", r.total_runs == 5)
    r2 = MultiBattleSimulator(p, [boss()], n=3, items=["HP_M_potion"], player_ai_mode="reactive").run()
    check("MultiBattleSimulator(...reactive) 보스전 실행 (BattleSession 경로 — 패턴 포함)", r2.total_runs == 3)

    print("\n" + "=" * 56)
    print(f" 결과: ✅ {PASS}  ❌ {FAIL}")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
