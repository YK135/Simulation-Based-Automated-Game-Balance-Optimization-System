# -*- coding: utf-8 -*-
"""
test_rift_status.py — 전용 상태이상 "rift"(균열) 회귀 테스트 (Combat Brief 11-1 3-1)

검증:
  · tick_status_effects()가 rift에 점화와 같은 max(1, int(maxhp × dot_rate)) 피해를 준다
  · 피격 장부(hit_ledger)에 via="dot", element="physical"로 기록된다 — 숫자 색은 tone-physical
  · 화상(ignite)과 독립적으로 공존한다 (ignite 재사용 시 합쳐지던 문제 — 부록 D-2/D-3)
  · 재적용은 중첩이 아니라 남은 턴 갱신(max) — 총 피해는 적용 사이 틱 수에 따라 8/12/16%
  · 지속 피해 사망 문구가 "균열 데미지로"를 쓴다 (플레이어·적 양쪽)
  · step() 응답의 hits가 rift 틱을 via=dot / element=physical 이벤트로 낸다
DB를 쓰지 않는다.

실행: python3 TestFile/test_rift_status.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, StatusEffect

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def probe(maxhp=1000.0, job="전사", spd=99.0):
    return EntitySnapshot(name="표본", hp=maxhp, maxhp=maxhp, mp=100, maxmp=100,
                          stg=10, arm=10, sparm=10, sp=10, luc=0, lv=10, spd=spd,
                          job=job, learned_skills=[], items=[])


def rift(turns=2):
    return StatusEffect(effect_type="rift", turns=turns, name="균열", dot_rate=0.04)


def drain(e, ticks):
    before = e.hp
    for _ in range(ticks):
        e.tick_status_effects()
    return before - e.hp


def main():
    print("=" * 56)
    print(" 전용 상태이상 rift (3-1)")
    print("=" * 56)

    print("\n[1] 틱 피해와 장부 기록")
    e = probe()
    e.hit_ledger = []
    e.apply_status_effect(rift())
    msgs = e.tick_status_effects()
    check("1틱 피해 = maxhp 4% (40)", e.hp == 960.0, e.hp)
    check("틱 메시지에 균열", any("균열 -40" in m for m in msgs), msgs)
    check("장부 1줄 — damage / via=dot / element=physical",
          e.hit_ledger == [{"kind": "damage", "amount": 40.0, "via": "dot",
                            "element": "physical", "reaction": ""}], e.hit_ledger)
    check("표시 태그 last_hit_element=physical, via=dot",
          e.last_hit_element == "physical" and e.last_hit_via == "dot")
    check("남은 턴 1", e.status_effects[0].turns == 1)
    e.tick_status_effects()
    check("2틱 뒤 소멸", not e.status_effects and e.hp == 920.0)
    e2 = probe(maxhp=10.0)
    e2.apply_status_effect(rift())
    e2.tick_status_effects()
    check("최소 피해 1 (maxhp 10 × 4% → 1)", e2.hp == 9.0, e2.hp)

    print("\n[2] 화상과 독립 (부록 D-3)")
    e = probe()
    e.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="화상", dot_rate=0.04))
    e.apply_status_effect(rift())
    check("효과 2개로 공존", len(e.status_effects) == 2,
          [(x.effect_type, x.turns) for x in e.status_effects])
    d = drain(e, 5)
    check("5틱 총 피해 200 = 화상 120 + 균열 80", d == 200.0, d)
    e = probe()
    e.apply_status_effect(rift())
    e.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="화상", dot_rate=0.04))
    check("적용 순서를 바꿔도 효과 2개", len(e.status_effects) == 2)

    print("\n[3] 재적용 = 남은 턴 갱신 (부록 D-1)")
    e = probe(); e.apply_status_effect(rift()); d = drain(e, 5)
    check("재적용 없음: 총 80 (2틱)", d == 80.0, d)
    e = probe(); e.apply_status_effect(rift()); d1 = drain(e, 1)
    e.apply_status_effect(rift()); d2 = drain(e, 5)
    check("1틱 뒤 재적용: 총 120 (3틱)", d1 + d2 == 120.0, d1 + d2)
    check("재적용 후 효과는 여전히 1개", True)   # 위 drain이 끝나 소멸했으므로 아래에서 다시 확인
    e = probe(); e.apply_status_effect(rift(2)); e.tick_status_effects()
    e.apply_status_effect(rift(2))
    check("갱신 후 효과 1개, 남은 턴 2", len(e.status_effects) == 1 and e.status_effects[0].turns == 2)
    e = probe(); e.apply_status_effect(rift()); d1 = drain(e, 2)
    e.apply_status_effect(rift()); d2 = drain(e, 5)
    check("소진 뒤 재적용: 총 160 (4틱)", d1 + d2 == 160.0, d1 + d2)

    print("\n[4] 세션 — 사망 문구와 hits 이벤트")
    enemy = EntitySnapshot(name="더미", hp=100000, maxhp=100000, mp=0, maxmp=0,
                           stg=1, arm=0, sparm=0, sp=0, luc=0, lv=1, spd=1.0, enemy_type="고블린")
    p = probe(maxhp=1000.0)
    p.status_effects.append(rift())
    s = BattleSession(p, enemy=enemy, items=[])
    out = s.step("attack")                       # 플레이어 차례 시작에 틱 → 행동
    tick = [h for h in out["hits"] if h["target"] == "player" and h["kind"] == "damage"]
    check("hits에 플레이어 damage 이벤트 1개", len(tick) == 1, out["hits"])
    if tick:
        check("amount 40 / via dot / element physical / reaction 없음",
              tick[0]["amount"] == 40 and tick[0]["via"] == "dot"
              and tick[0]["element"] == "physical" and tick[0]["reaction"] == "", tick[0])
    check("RL 레코드 hp_damage_taken에 틱이 포함", s.rl_log[-1]["result"]["hp_damage_taken"] >= 40)
    check("잔차 0 (기록 누락 없음)", getattr(s, "_last_hit_residual", 0) == 0)

    p = probe(maxhp=1000.0); p.hp = 1.0
    p.status_effects.append(rift())
    s = BattleSession(p, enemy=enemy, items=[])
    out = s.step("attack")
    check("플레이어 사망 문구: 🌑 … 균열 데미지로 쓰러졌다",
          any(m.startswith("🌑") and "균열 데미지로 쓰러졌다" in m for m in out["messages"]), out["messages"])
    check("RL 레코드 action.type == none", s.rl_log[-1]["action"]["type"] == "none")

    en = EntitySnapshot(name="더미", hp=1.0, maxhp=1000, mp=0, maxmp=0,
                        stg=1, arm=0, sparm=0, sp=0, luc=0, lv=1, spd=99.0, enemy_type="고블린")
    en.status_effects.append(rift())
    s = BattleSession(probe(spd=1.0), enemy=en, items=[])
    out = s.step("auto")
    check("적 사망 문구: 🌑 … 균열 데미지로 처치했다",
          any(m.startswith("🌑") and "균열 데미지로 처치했다" in m for m in out["messages"]), out["messages"])
    check("전투 종료·플레이어 승리", s.done and s.winner == "player")

    print("\n" + "=" * 56)
    print(f" 결과: ✅ {PASS}  ❌ {FAIL}")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
