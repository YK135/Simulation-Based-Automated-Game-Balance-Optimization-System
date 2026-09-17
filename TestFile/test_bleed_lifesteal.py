# -*- coding: utf-8 -*-
"""
test_bleed_lifesteal.py — 출혈 스택 + 흡혈 시스템 회귀 테스트 (Combat Content Brief 10-4 · 11-1 2차 5번)

검증 대상:
  · 출혈 스택 — 최대 3, 다시 걸면 지속 갱신 + 스택 +1, 스택당 매 행동 maxHP 3% 확정(난수 없음),
    다른 상태이상은 스택 개념 없음. 도적 주사위 3·6이 실전 세션·튜너 엔진 양쪽에서 같은 규칙으로 쌓인다
  · 흡혈 — 기본 0, 버프(stat "lifesteal")로만 붙는다. 기준 = 실제 HP 감소 + 실드 감소(초과 피해 제외),
    타격당 maxHP 4% · 시전당 12% 두 겹 상한, maxHP 초과 회복 없음, DoT·적 피해에는 없음.
    일반공격 / 단일 스킬 / 연속공격 / AoE / 도적 반격 / BattleEngine 경로 모두 같은 Damage 함수
  · 상태 JSON status_effects[].stacks, 박쥐 흡혈은 별도 경로 그대로
DB를 쓰지 않는다.

실행: python3 TestFile/test_bleed_lifesteal.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import (
    EntitySnapshot, StatusEffect, Buff, Action, BattleEngine, LifestealCast, lifesteal_heal,
    BLEED_STACK_MAX, BLEED_RATE_PER_STACK,
)
from ai.battle.Damage import (
    deal_damage_with_lifesteal, LIFESTEAL_HIT_CAP_RATIO, LIFESTEAL_CAST_CAP_RATIO,
)
from ai.battle import Damage as D
import ai.battle_session.Player_Actions as PA
import ai.battle.Engine as EN
import ai.battle_session.Enemy_Actions as EA

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


class deterministic:
    def __enter__(self):
        self.ru, self.ri = D.uniform, D.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint = self.ru, self.ri


class dice:
    """도적 주사위를 고정한다 — 세션(Player_Actions.randint)과 엔진(Engine.randint) 둘 다."""
    def __init__(self, v): self.v = v
    def __enter__(self):
        self.pa, self.en = PA.randint, EN.randint
        PA.randint = lambda a, b: self.v
        EN.randint = lambda a, b: self.v
    def __exit__(self, *a):
        PA.randint, EN.randint = self.pa, self.en


def ent(name="용사", hp=1000, stg=100, job="전사", skills=None, spd=50.0, lifesteal=0.0, et="", **kw):
    return EntitySnapshot(name=name, hp=hp, maxhp=hp, mp=500, maxmp=500, stg=stg, arm=0, sparm=0, sp=10,
                          luc=0, lv=10, spd=spd, job=job, learned_skills=list(skills or []), items=[],
                          lifesteal=lifesteal, enemy_type=et, **kw)


def dummy(hp=5000, spd=1.0, et="슬라임", **kw):
    return ent("허수아비", hp=hp, stg=10, job="", spd=spd, et=et, **kw)


# ═══════════════════════════════════════════════════════════
print("\n[1] 출혈 스택 — apply_status_effect")
t = dummy()
e1 = t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
check("첫 출혈: 1스택 3턴", e1.stacks == 1 and e1.turns == 3 and len(t.status_effects) == 1)
e1.turns = 1
e2 = t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
check("재적용: 같은 객체, 2스택, 지속 갱신(1→3)", e2 is e1 and e1.stacks == 2 and e1.turns == 3)
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
check("3스택 상한", e1.stacks == BLEED_STACK_MAX == 3 and len(t.status_effects) == 1)
t.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="fire"))
ig = t.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="fire"))
check("점화는 스택 없음(1 유지, 효과 1개)", ig.stacks == 1 and sum(1 for x in t.status_effects if x.effect_type == "ignite") == 1)
check("StatusEffect 기본 stacks 1", StatusEffect(effect_type="rift", turns=2, name="균열").stacks == 1)

print("\n[2] 출혈 틱 — 스택당 3% 확정")
for n in (1, 2, 3):
    t = dummy(hp=1000)
    t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=n))
    msgs = t.tick_status_effects()
    check(f"{n}스택 틱 = {30 * n} (난수 없음)", 1000 - t.hp == 30 * n, (t.hp, msgs))
    if n == 1:
        check("1스택 메시지엔 ×n 없음", msgs and "×" not in msgs[0], msgs)
    else:
        check(f"메시지 '출혈 ×{n}'", msgs and f"출혈 ×{n}" in msgs[0], msgs)
t = dummy(hp=1000); t.hp = 20
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=3))
t.tick_status_effects()
check("틱이 HP를 0 아래로 내리지 않음", t.hp == 0.0)

print("\n[3] 도적 주사위 3 → 세션과 엔진에서 같은 스택 규칙")
p = ent(job="도적", spd=50.0)
s = BattleSession(p, enemies=[dummy()])
with dice(3), deterministic():
    r1 = s.step("attack")
    s.action_queue = [("player", -1)]
    r2 = s.step("attack")
bl = [x for x in s.enemies[0].status_effects if x.effect_type == "bleed"]
check("세션: 주사위 3 두 번 → 출혈 2스택", bl and bl[0].stacks == 2, [vars(x) for x in s.enemies[0].status_effects])
check("메시지 '출혈! (×2, 매 행동 maxHP 6%)'", any("출혈! (×2" in m and "6%" in m for m in r2["messages"]), r2["messages"])
check("상태 JSON stacks", r2["enemies"][0]["status_effects"][0]["stacks"] == 2, r2["enemies"][0]["status_effects"])
eng = BattleEngine(ent(job="도적"), dummy())
with dice(3), deterministic():
    eng._execute_action(Action("attack", "attack"), eng.player, eng.enemy, "player")
    eng._execute_action(Action("attack", "attack"), eng.player, eng.enemy, "player")
bl = [x for x in eng.enemy.status_effects if x.effect_type == "bleed"]
check("엔진: 같은 규칙으로 2스택", bl and bl[0].stacks == 2)

# ═══════════════════════════════════════════════════════════
print("\n[4] 흡혈 — Damage.lifesteal_heal / deal_damage_with_lifesteal")
a = ent(hp=1000); a.hp = 500
check("effective_lifesteal 기본 0 → 회복 0", a.effective_lifesteal() == 0.0 and lifesteal_heal(a, 100, None) == 0.0 and a.hp == 500)
a.apply_buff(Buff(stat="lifesteal", amount=0.25, turns=3, name="피의 격노"))
check("버프 stat lifesteal → 0.25", abs(a.effective_lifesteal() - 0.25) < 1e-9)
check("기준 100 × 25% = 25", lifesteal_heal(a, 100, None) == 25.0 and a.hp == 525)
check("타격당 상한 maxHP 4% (=40): 기준 400 → 40", lifesteal_heal(a, 400, None) == 40.0)
cast = LifestealCast(a)
check("시전 예산 = maxHP 12% (=120)", cast.pool == 1000 * LIFESTEAL_CAST_CAP_RATIO == 120.0)
got = [lifesteal_heal(a, 400, cast) for _ in range(4)]
check("한 시전에 400×4타 → 40+40+40+0 (시전 상한)", got == [40.0, 40.0, 40.0, 0.0] and cast.pool == 0.0, got)
a.hp = 990
check("maxHP 초과 회복 없음 (남은 10만)", lifesteal_heal(a, 400, LifestealCast(a)) == 10.0 and a.hp == 1000)
a.hp = 500
d = dummy(hp=100); d.hp = 10
hp_dmg, healed = deal_damage_with_lifesteal(a, d, 500, LifestealCast(a))
# _apply_damage_with_shield의 반환값은 실드를 뺀 '적용 피해'(기존 의미, HP에 잘리지 않음) — 흡혈 기준만 실제 감소량
check("초과 피해 불인정: 남은 HP 10에 500 → 기준 10 → 2.5 (반환 피해는 기존대로 500)", hp_dmg == 500 and healed == 2.5, (hp_dmg, healed))
d = dummy(hp=1000); d.shield = 50
hp_dmg, healed = deal_damage_with_lifesteal(a, d, 100, LifestealCast(a))
check("실드 흡수분 인정: 실드 50 + HP 50 → 기준 100 → 25", hp_dmg == 50 and healed == 25.0, (hp_dmg, healed))
a.hit_ledger = []
lifesteal_heal(a, 100, None)
check("피격 장부: heal via lifesteal", a.hit_ledger and a.hit_ledger[-1]["kind"] == "heal" and a.hit_ledger[-1]["via"] == "lifesteal")
_e = ent(hp=1000, lifesteal=1.0); _e.hp = 100
check("cast=None이면 시전 상한 없이 타격 상한만", lifesteal_heal(_e, 1000, None) == 40.0)

print("\n[5] 흡혈 — 세션 경로 (일반공격 · 단일 스킬 · 연속공격 · AoE · 반격 · DoT 제외 · 적은 없음)")
def ses(job="", skills=None, enemies=None, ls=0.25, spd=50.0):
    # job=""(직업 패시브 없음) — 전사 패시브(공격 3회마다 10% 회복)가 흡혈 수치에 섞이지 않게
    p = ent(job=job, skills=skills, spd=spd, lifesteal=ls)
    p.hp = 500
    return BattleSession(p, enemies=enemies or [dummy()])

s = ses()
with deterministic():
    r = s.step("attack")
dealt = s.logs[-1].damage_dealt
check("일반공격: 피해 200 → 흡혈 40(타격 상한 4%)", dealt == 200 and s.player.hp == 540, (dealt, s.player.hp))
check("메시지 '🩸 흡혈 +40 HP'", any("흡혈 +40" in m for m in r["messages"]), r["messages"])
check("hits에 회복 이벤트(플레이어 heal)", any(h.get("kind") == "heal" and h.get("target") == "player" for h in r["hits"]), r["hits"])

s = ses(skills=["강타1"])
with deterministic():
    s.step("skill:강타1")
check("단일 스킬(강타1 310) → 40", s.player.hp == 540, s.player.hp)

s = ses(skills=["연속공격2"])            # 0.70 × 3타 = 140×3, 각 타 35 → 105 (타격 상한 40 미만, 시전 상한 120 미만)
with deterministic():
    s.step("skill:연속공격2")
check("연속공격2 3타 × 35 = 105", s.player.hp == 605, s.player.hp)

s = ses(skills=["슬래시1"], enemies=[dummy(), dummy(), dummy()])   # 0.65 → 130/대상, 각 32.5 → 97.5
with deterministic():
    s.step("skill:슬래시1")
check("AoE 3대상 × 32.5 = 97.5 (시전 상한 120 이내)", abs(s.player.hp - 597.5) < 1e-9, s.player.hp)

s = ses(skills=["슬래시1"], enemies=[dummy(), dummy(), dummy()], ls=1.0)  # 각 대상 40(타격 상한) → 120(시전 상한)
with deterministic():
    s.step("skill:슬래시1")
check("흡혈 100%: 40+40+40 = 120 = 시전 상한", s.player.hp == 620, s.player.hp)

# DoT는 흡혈 기준이 아니다
s = ses()
s.enemies[0].apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
s.action_queue = [("enemy", 0)]
hp0 = s.player.hp
with deterministic():
    s.step("auto")            # 적 차례 진입 시 적 출혈 틱
check("적 출혈 틱으로는 회복 없음(피해도 안 받았을 때)", s.player.hp <= hp0, (hp0, s.player.hp))

# 적이 주는 피해로 적이 회복하지 않는다 (박쥐 제외 — 자기 경로)
s = ses(spd=1.0)
s.enemies[0].hp = 3000
with deterministic():
    s.step("auto")
check("적 일반공격: 적 HP 그대로(흡혈 0)", s.enemies[0].hp == 3000, s.enemies[0].hp)

# 도적 반격
p = ent(job="도적", spd=1.0, lifesteal=0.25); p.hp = 500; p.dodge_bonus = 0.5   # 회피 판정 50% → randint 1이면 회피
s = BattleSession(p, enemies=[dummy(spd=20)])
s._enemy_ai = lambda *a, **k: Action("attack", "attack")     # 슬라임 킷의 둔화1 대신 반드시 일반공격
old_ri = D.randint
try:
    # 회피 판정(randint ≤ evade)만 성공시키고 나머지는 상한 — 첫 호출은 회피 판정
    calls = {"n": 0}
    def ri(a, b):
        calls["n"] += 1
        return 1 if calls["n"] == 1 else b
    D.randint = ri; D.uniform = lambda a, b: 1.0
    r = s.step("auto")
finally:
    D.randint = old_ri; D.uniform = __import__("random").uniform
check("반격(20 STG… 기준 피해)도 흡혈", any("반격" in m for m in r["messages"]) and s.player.hp > 500, (s.player.hp, r["messages"]))

print("\n[6] 흡혈 — BattleEngine 경로")
eng = BattleEngine(ent(lifesteal=0.25), dummy())
eng.player.hp = 500
with deterministic():
    eng._execute_action(Action("attack", "attack"), eng.player, eng.enemy, "player")
check("엔진 일반공격 200 → 흡혈 40", eng.logs[-1].damage_dealt == 200 and eng.player.hp == 540, eng.player.hp)
eng = BattleEngine(ent(lifesteal=1.0, skills=["연속공격2"]), dummy())
eng.player.hp = 500
with deterministic():
    eng._execute_action(Action("skill", "연속공격2"), eng.player, eng.enemy, "player")
check("엔진 연속공격2(100%): 3타 × 40 = 120 (시전 상한)", eng.player.hp == 620, eng.player.hp)
eng = BattleEngine(ent(lifesteal=0.0), dummy(et="박쥐"))
eng.enemy.hp = 2000
with deterministic():
    eng._execute_action(Action("attack", "attack"), eng.enemy, eng.player, "enemy")
check("박쥐 흡혈은 자기 경로 그대로(효과 있음)", eng.enemy.hp > 2000, eng.enemy.hp)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
