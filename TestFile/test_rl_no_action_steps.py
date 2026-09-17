# -*- coding: utf-8 -*-
"""
test_rl_no_action_steps.py — RL 로그: 행동 로그가 없는 step 처리 (Combat Brief 11-1 3-0)

검증:
  · 마비로 행동에 실패한 step → action.type == "paralyzed", 직전 로그의 행동/크리를 복제하지 않는다
  · 지속 피해로 행동 전에 사망한 step → "none" + battle_done/winner, 사망 문구는 상태이상 이름을 쓴다
  · 엘리트 사제 부활 의식(TurnLog를 남기지 않는 행동) → "ritual"
  · 적 공격을 도적이 회피 반격한 step → 적의 행동은 반격(counter)이 아니라 attack, evade=True
  · 정상 step은 스킬명/크리/회피가 이번 step의 로그에서 나온다
  · "status" 조회는 여전히 기록되지 않는다
DB를 쓰지 않는다 (BattleSession은 순수 인메모리).

실행: python3 TestFile/test_rl_no_action_steps.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, StatusEffect, TurnLog

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def player(job="전사", spd=99.0, hp=1000, luc=10):
    return EntitySnapshot(
        name="기록자", hp=hp, maxhp=hp, mp=200, maxmp=200,
        stg=50, arm=20, sparm=10, sp=10, luc=luc, lv=10, spd=spd,
        job=job, learned_skills=["슬래시1"], items=[])


def enemy(etype="고블린", spd=1.0, hp=100000, stg=30, elite=False):
    e = EntitySnapshot(
        name=etype, hp=hp, maxhp=hp, mp=999, maxmp=999,
        stg=stg, arm=0, sparm=0, sp=10, luc=0, lv=5, spd=spd,
        enemy_type=etype)
    if elite:
        e.is_elite = e.elite_leader = True
    return e


def last(s):
    return s.rl_log[-1]


def main():
    print("=" * 56)
    print(" RL 로그 — 행동 로그가 없는 step (3-0)")
    print("=" * 56)

    # [1] 마비 실패 -----------------------------------------------------
    print("\n[1] 마비로 행동 실패")
    p = player()
    p.status_effects.append(StatusEffect(effect_type="paralyze", turns=5, name="lightning", fail_prob=100))
    s = BattleSession(p, enemy=enemy(), items=[])
    # 직전 step의 로그가 남아 있는 상황을 흉내 — 예전 구현은 이걸 그대로 복제했다
    s.logs.append(TurnLog(turn=0, actor="player", action="skill", action_detail="강타1",
                          damage_dealt=99, hp_after=1, mp_after=1, is_crit=True))
    n0 = len(s.rl_log)
    out = s.step("attack")
    rec = last(s)
    check("마비 step이 기록됨", len(s.rl_log) == n0 + 1)
    check("action.type == paralyzed", rec["action"]["type"] == "paralyzed", rec["action"]["type"])
    check("detail 비어 있음", rec["action"]["detail"] == "")
    check("직전 로그의 크리를 복제하지 않음", rec["result"]["crit"] is False)
    check("damage_type 비어 있음", rec["result"]["damage_type"] == "")
    check("forced_fail_risk 플래그 True", rec["action"]["forced_fail_risk"] is True)
    check("메시지에 마비 실패", any("마비로 행동에 실패" in m for m in out["messages"]))

    # [2] status 조회는 기록하지 않음 -------------------------------------
    print("\n[2] status 조회")
    n1 = len(s.rl_log)
    s.step("status")
    check("status는 레코드를 남기지 않음", len(s.rl_log) == n1)

    # [3] DoT 사망 -------------------------------------------------------
    print("\n[3] 지속 피해로 행동 전 사망")
    for etype, label in (("ignite", "점화"), ("bleed", "출혈"), ("rift", "균열")):
        p = player(hp=1)
        p.hp = 1.0
        p.status_effects.append(StatusEffect(effect_type=etype, turns=2, name=label))
        s = BattleSession(p, enemy=enemy(), items=[])
        out = s.step("attack")
        rec = last(s)
        check(f"{label}: 전투 종료·적 승리", s.done and s.winner == "enemy")
        check(f"{label}: action.type == none", rec["action"]["type"] == "none", rec["action"]["type"])
        check(f"{label}: result.battle_done/winner", rec["result"]["battle_done"] and rec["result"]["winner"] == "enemy")
        check(f"{label}: hp_damage_taken 기록", rec["result"]["hp_damage_taken"] >= 1)
        check(f"{label}: 사망 문구가 상태이상 이름을 씀",
              any(f"{label} 데미지로 쓰러졌다" in m for m in out["messages"]), out["messages"])

    # 적이 DoT로 죽는 경우도 같은 문구 규칙
    p = player(spd=1.0)
    e = enemy(spd=99.0, hp=1)
    e.hp = 1.0
    e.status_effects.append(StatusEffect(effect_type="bleed", turns=2, name="출혈"))
    s = BattleSession(p, enemy=e, items=[])
    out = s.step("auto")
    check("적 DoT 사망 문구: 출혈 데미지로 처치했다", any("출혈 데미지로 처치했다" in m for m in out["messages"]), out["messages"])
    check("적 DoT 사망 step은 none", last(s)["action"]["type"] == "none")

    # [4] 엘리트 사제 부활 의식 --------------------------------------------
    print("\n[4] 엘리트 사제 부활 의식")
    p = player(spd=1.0)
    p.stg = 1
    priest = enemy("사제", spd=99.0, elite=True)
    ally = enemy("고블린", spd=50.0)
    s = BattleSession(p, enemies=[priest, ally], items=[])
    s.enemies[1].hp = 0.0                       # 아군이 먼저 죽어 있음
    s._cleanup_dead_from_queue()
    out = s.step("auto")                        # 사제: 의식 준비 (TurnLog 없음)
    rec = last(s)
    check("의식 준비 step: action.type == ritual", rec["action"]["type"] == "ritual", rec["action"]["type"])
    check("의식 준비 step: actor enemy", rec["action"]["actor"] == "enemy")
    check("의식 준비 메시지", any("부활 의식을 시작" in m for m in out["messages"]))
    s.step("attack")                            # 플레이어 차례 소비
    out = s.step("auto")                        # 사제: 의식 완성
    rec = last(s)
    check("의식 완성 step: action.type == ritual", rec["action"]["type"] == "ritual", rec["action"]["type"])
    check("의식 완성: 아군 부활", s.enemies[1].hp > 0)

    # [5] 도적 회피 반격이 있는 적 step ------------------------------------
    print("\n[5] 도적 회피 반격이 끼어든 적 step")
    random.seed(7)
    found = None
    for _ in range(200):
        p = player(job="도적", spd=1.0, luc=100)   # 회피율 상한 25%
        s = BattleSession(p, enemy=enemy(spd=99.0), items=[])
        out = s.step("auto")
        if any("[도적 반격]" in m for m in out["messages"]):
            found = last(s)
            break
    check("반격 step을 찾음", found is not None)
    if found:
        check("적 행동은 attack (counter 아님)", found["action"]["type"] == "attack", found["action"]["type"])
        check("detail == basic_attack", found["action"]["detail"] == "basic_attack", found["action"]["detail"])
        check("evade == True (적 공격을 회피)", found["result"]["evade"] is True)
        check("반격 피해가 damage로 잡힘", found["result"]["damage"] >= 0)

    # [6] 정상 step -------------------------------------------------------
    print("\n[6] 정상 step")
    random.seed(3)
    p = player()
    s = BattleSession(p, enemy=enemy(), items=[])
    s.step("skill:슬래시1")
    rec = last(s)
    lg = s.logs[-1]
    check("플레이어 스킬 step: type skill / detail 슬래시1",
          rec["action"]["type"] == "skill" and rec["action"]["detail"] == "슬래시1")
    check("크리 값이 이번 step 로그와 일치", rec["result"]["crit"] == bool(lg.is_crit))
    out = s.step("auto")
    rec = last(s)
    lg = next(l for l in reversed(s.logs) if l.actor == "enemy")
    check("적 step: type이 로그 action과 일치",
          rec["action"]["type"] == ("attack" if lg.action == "attack" else lg.action), rec["action"]["type"])
    check("적 step: detail이 로그와 일치", rec["action"]["detail"] == lg.action_detail)
    check("적 step: crit/evade가 이번 step 로그와 일치",
          rec["result"]["crit"] == bool(lg.is_crit) and rec["result"]["evade"] == bool(lg.is_dodge))

    print("\n" + "=" * 56)
    print(f" 결과: ✅ {PASS}  ❌ {FAIL}")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
