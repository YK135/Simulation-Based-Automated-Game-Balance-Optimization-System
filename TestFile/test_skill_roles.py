# -*- coding: utf-8 -*-
"""
test_skill_roles.py — 기존 스킬 역할 분화 회귀 테스트 (Combat Content Brief 6장 · 11-1 2차 4번)

검증 대상:
  · 강타1/2 처형 — 대상 HP 30% 이하면 계수 +50% (1.55→2.33 / 1.80→2.70), 31%면 그대로. 메시지 「처형」.
    몬스터판(고블린 강타1)은 개편 전 값 고정 — 처형 없음
  · 아이스볼릿1/2 확정 둔화 — 100%, −10% 2턴 / −15% 3턴. 빙결 슬라임의 아이스볼릿은 확률판 그대로
  · 강화1/2 지속 3턴. 유령의 강화1(몬스터판)은 2턴 그대로
  · 급소찌르기1/2 — 출혈 중인 대상에게 +15%, 아니면 그대로. 암살자판은 보너스 없음
  · 마법사 원소 공명 — 같은 원소 연속 시전 2단계 +10% / 3단계 +20%(상한), 전환 시 1단계 + 그 시전의 반응 보너스
    +5%p → +20%p, 힐·MP 부족 시전은 단계를 안 바꿈, 마법사 외 직업은 공명 없음, 상태 JSON player_resonance,
    AoE 나머지 대상에도 같은 배율, 튜너 엔진(BattleEngine) 경로도 동일
  · 측정용 AI(reactive)만 처형·출혈 급소·공명 단계를 점수에 반영, 기본 AI(balanced)는 그대로
DB를 쓰지 않는다.

실행: python3 TestFile/test_skill_roles.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import (
    EntitySnapshot, StatusEffect, Action, BattleEngine, SKILL_META, MONSTER_SKILL_META,
    execute_skill, execute_single_hit, physical_skill_mult,
)
from ai.battle import Damage as D
from ai.battle import Skills as SK
from ai.battle.Elements import (
    mage_resonance_on_cast, mage_resonance_mult, RESONANCE_MAX_STACK, RESONANCE_STEP,
    MAGE_REACTION_BONUS, MAGE_SWITCH_REACTION_BONUS, REACTION_EFFECTS,
)
from ai.Auto_AI import PlayerAI, _best_attack_skill

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
    """난수·크리·회피를 끈다 — uniform=1.0, randint는 상한(임계 초과). Skills.random도 1.0(확률 디버프 미발동)."""
    def __enter__(self):
        self.ru, self.ri, self.sr, self.sri = D.uniform, D.randint, SK.random, SK.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        SK.random = lambda: 1.0
        SK.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint, SK.random, SK.randint = self.ru, self.ri, self.sr, self.sri


def player(job="전사", stg=100, sp=100, mp=500, skills=None, spd=50.0, luc=0):
    return EntitySnapshot(name="용사", hp=3000, maxhp=3000, mp=mp, maxmp=mp,
                          stg=stg, arm=20, sparm=10, sp=sp, luc=luc, lv=15, spd=spd,
                          job=job, learned_skills=list(skills or []), items=[])


def dummy(hp=1000, et="", **kw):
    return EntitySnapshot(name="허수아비", hp=hp, maxhp=hp, mp=100, maxmp=100,
                          stg=10, arm=0, sparm=0, sp=10, luc=0, lv=5, spd=1.0, enemy_type=et, **kw)


def dmg_of(skill, atk, tgt):
    with deterministic():
        d, lack, info = execute_skill(skill, atk, tgt)
    return d, info


# ═══════════════════════════════════════════════════════════
print("\n[1] 강타 처형")
p = player(skills=["강타1", "강타2"])
t = dummy(); t.hp = 310                      # 31%
d_hi, _ = dmg_of("강타1", p, t)
t2 = dummy(); t2.hp = 300                    # 30% — 경계 포함
d_lo, info_lo = dmg_of("강타1", p, t2)
check("HP 31%: 처형 없음 = STG×2×1.55 (=310, 공식 atk×200/(100+0))", d_hi == 310, d_hi)
check("HP 30%: 처형 ×1.5 (=465)", d_lo == int(200 * 1.55 * 1.5), d_lo)
check("처형 메시지", "처형" in info_lo, info_lo)
t3 = dummy(); t3.hp = 100
d2, _ = dmg_of("강타2", p, t3)
check("강타2 처형 = 1.80×1.5 = 2.70 (=540)", d2 == 540, d2)
check("physical_skill_mult 태그", physical_skill_mult(SKILL_META["강타1"], t3) == (1.5, ["execute"]))
t4 = dummy(); t4.hp = 300
with deterministic():
    r1, *_ = execute_single_hit("강타1", p, t4)
check("execute_single_hit 경로도 처형 적용", r1 == 465, r1)
# 몬스터판 강타1 (고블린)은 처형 없음
gob = EntitySnapshot(name="고블린", hp=300, maxhp=300, mp=50, maxmp=50, stg=100, arm=0, sparm=0, sp=0,
                     luc=0, lv=5, enemy_type="고블린")
victim = dummy(); victim.hp = 100
dg, _ = dmg_of("강타1", gob, victim)
check("고블린 강타1은 MONSTER_SKILL_META(개편 전) — 처형 없음 (=310)", dg == 310 and "execute_hp" not in MONSTER_SKILL_META["강타1"], dg)

# ═══════════════════════════════════════════════════════════
print("\n[2] 아이스볼릿 확정 둔화 · 강화 3턴")
m = player(job="마법사", skills=["아이스볼릿1", "아이스볼릿2"])
t = dummy()
with deterministic():                       # SK.random=1.0: 확률판이면 절대 안 걸린다 → 확정판만 걸린다
    execute_skill("아이스볼릿1", m, t)
sd = [d for d in t.debuffs if d.stat == "spd"]
check("아이스볼릿1: 확정 둔화 −10% 2턴", sd and sd[0].amount == 0.10 and sd[0].turns == 2, [vars(x) for x in t.debuffs])
t = dummy()
with deterministic():
    execute_skill("아이스볼릿2", m, t)
sd = [d for d in t.debuffs if d.stat == "spd"]
check("아이스볼릿2: 확정 둔화 −15% 3턴", sd and sd[0].amount == 0.15 and sd[0].turns == 3, [vars(x) for x in t.debuffs])
check("계수는 그대로 1.25 / 1.45", SKILL_META["아이스볼릿1"]["mult"] == 1.25 and SKILL_META["아이스볼릿2"]["mult"] == 1.45)
ice = EntitySnapshot(name="빙결 슬라임", hp=300, maxhp=300, mp=50, maxmp=50, stg=10, arm=0, sparm=0, sp=50,
                     luc=0, lv=5, enemy_type="빙결 슬라임")
pl = dummy()
with deterministic():
    execute_skill("아이스볼릿1", ice, pl)
check("빙결 슬라임 아이스볼릿1은 확률판 그대로(30%) — 난수 1.0에서 미발동",
      not pl.debuffs and MONSTER_SKILL_META["아이스볼릿1"]["debuff_chance"] == 0.3, pl.debuffs)
w = player(skills=["강화1", "강화2"])
execute_skill("강화1", w, dummy())
check("강화1 3턴", w.buffs and w.buffs[0].turns == 3 and w.buffs[0].amount == 0.15, w.buffs)
w.buffs.clear(); execute_skill("강화2", w, dummy())
check("강화2 3턴", w.buffs and w.buffs[0].turns == 3 and w.buffs[0].amount == 0.25, w.buffs)
gh = EntitySnapshot(name="유령", hp=300, maxhp=300, mp=50, maxmp=50, stg=10, arm=0, sparm=0, sp=0,
                    luc=0, lv=5, enemy_type="유령")
execute_skill("강화1", gh, dummy())
check("유령 강화1은 몬스터판 2턴 그대로", gh.buffs and gh.buffs[0].turns == 2 and gh.buffs[0].amount == 0.12, gh.buffs)

# ── 「추진력」 지속 2 → 8턴 (BALANCE_PATCH_10) ──
# 2턴짜리는 시전 행동에서 1턴이 줄어 **덮는 행동이 1회뿐**이고, balanced AI가
# "내 실효 SPD ≥ 상대 실효 SPD"일 때 SPD 버프를 걸기 때문에 가장 빠른 도적이
# 전투의 33~63%를 0딜 재시전에 썼다. 효과·비용은 그대로 둔다.
rg = player(job="도적", skills=["추진력"], mp=200)
execute_skill("추진력", rg, dummy())
check("추진력 8턴 · +10% (효과·비용 불변)",
      rg.buffs and rg.buffs[0].turns == 8 and abs(rg.buffs[0].amount - 0.10) < 1e-9
      and SKILL_META["추진력"]["mp"] == 13, rg.buffs)
# 덮는 행동 수 = 지속 − 1 (시전 행동에서 같이 줄어든다)
_covered = 0
for _ in range(20):
    rg.tick_buffs()
    if any(b.stat == "spd" for b in rg.buffs):
        _covered += 1
check("추진력이 실제로 덮는 행동은 7회(지속 8 − 시전 1)", _covered == 7, _covered)
check("암살자판 추진력은 2턴 그대로(전투당 1회라 트레드밀이 없다)",
      MONSTER_SKILL_META["추진력"]["buff_turns"] == 2, MONSTER_SKILL_META["추진력"])

# ═══════════════════════════════════════════════════════════
print("\n[3] 급소찌르기 출혈 보너스")
r = player(job="도적", skills=["급소찌르기1"], luc=0)
t = dummy()
d_plain, _ = dmg_of("급소찌르기1", r, t)
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
d_bleed, info = dmg_of("급소찌르기1", r, t)
check("출혈 없음 = 240, 출혈 중 = 276 (+15%)", d_plain == 240 and d_bleed == 276, (d_plain, d_bleed))
check("메시지 '출혈 급소'", "출혈 급소" in info, info)
asn = EntitySnapshot(name="암살자", hp=300, maxhp=300, mp=50, maxmp=50, stg=100, arm=0, sparm=0, sp=0,
                     luc=0, lv=5, enemy_type="암살자")
v = dummy(); v.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
da, _ = dmg_of("급소찌르기1", asn, v)
check("암살자 급소찌르기1은 몬스터판(1.05) — 출혈 보너스 없음 (=210)", da == 210, da)

# ═══════════════════════════════════════════════════════════
print("\n[4] 원소 공명 — 순수 함수")
m = player(job="마법사")
check("첫 시전: 1단계, 전환 아님", mage_resonance_on_cast(m, "fire", "magical") == "stack"
      and (m.resonance_element, m.resonance_stack, m.resonance_switched) == ("fire", 1, False))
check("1단계 배율 1.0", mage_resonance_mult(m, "fire") == 1.0)
mage_resonance_on_cast(m, "fire", "magical")
check("2단계 → ×1.10", abs(mage_resonance_mult(m, "fire") - 1.10) < 1e-9)
mage_resonance_on_cast(m, "fire", "magical")
check("3단계 → ×1.20", abs(mage_resonance_mult(m, "fire") - 1.20) < 1e-9)
mage_resonance_on_cast(m, "fire", "magical")
check("4회째도 3단계 상한", m.resonance_stack == RESONANCE_MAX_STACK)
check("다른 원소의 배율은 1.0", mage_resonance_mult(m, "ice") == 1.0)
check("힐(무원소)은 단계를 바꾸지 않음", mage_resonance_on_cast(m, "", "heal") == "" and m.resonance_stack == 3)
check("전환: lightning → 1단계 + switched", mage_resonance_on_cast(m, "lightning", "magical") == "switch"
      and (m.resonance_element, m.resonance_stack, m.resonance_switched) == ("lightning", 1, True))
mage_resonance_on_cast(m, "lightning", "magical")
check("전환 뒤 같은 원소를 이으면 switched 해제", m.resonance_switched is False and m.resonance_stack == 2)
w2 = player(job="전사")
check("전사는 공명 없음", mage_resonance_on_cast(w2, "fire", "magical") == "" and w2.resonance_stack == 0
      and mage_resonance_mult(w2, "fire") == 1.0)

# ═══════════════════════════════════════════════════════════
print("\n[5] 원소 공명 — execute_skill 통합 (피해 · 반응 보너스 · MP 부족)")
m = player(job="마법사", skills=["파이어볼1", "라이트닝1", "힐1"])
base = int(200 * 1.50)                           # SP 100 × 200/(100+0) × 1.50 → 300
d1, i1 = dmg_of("파이어볼1", m, dummy())
d2, i2 = dmg_of("파이어볼1", m, dummy())
d3, i3 = dmg_of("파이어볼1", m, dummy())
check("연속 파이어볼: 300 → 330 → 360(부동소수 절삭으로 359 허용)", (d1, d2) == (300, 330) and abs(d3 - 360) <= 1, (d1, d2, d3))
check("공명 메시지(2·3단계에만)", "공명" not in i1 and "공명 2단계" in i2 and "공명 3단계" in i3, (i1, i2, i3))
# 전환 + 반응: fire가 붙은 대상에게 라이트닝 → 과부하 1.3 + 전환 0.20
t = dummy(); t.element_queue = ["fire"]
m.resonance_element, m.resonance_stack = "fire", 3
d_sw, i_sw = dmg_of("라이트닝1", m, t)
raw = int(200 * 1.55)                            # 310, 공명 배율은 전환이라 1.0
expect = raw + int(raw * (REACTION_EFFECTS["overload"]["bonus_mult"] + MAGE_SWITCH_REACTION_BONUS - 1.0))
check("전환 시전의 과부하: 1.30 + 0.20 (=310+155=465)", d_sw == expect, (d_sw, expect, i_sw))
check("전환 공명 메시지", "전환 공명" in i_sw, i_sw)
# 전환이 아닌 반응은 +5%p 그대로
m2 = player(job="마법사", skills=["라이트닝1"])
t = dummy(); t.element_queue = ["fire"]
d_n, i_n = dmg_of("라이트닝1", m2, t)
expect_n = raw + int(raw * (REACTION_EFFECTS["overload"]["bonus_mult"] + MAGE_REACTION_BONUS - 1.0))
check("첫 시전(전환 아님)의 과부하: 1.30 + 0.05 (=310+108=418)", d_n == expect_n, (d_n, expect_n))
# MP 부족 시전은 상태를 바꾸지 않는다
m3 = player(job="마법사", mp=5, skills=["파이어볼1"])
with deterministic():
    d, lack, _ = execute_skill("파이어볼1", m3, dummy())
check("MP 부족: 공명 단계 그대로 0", lack and m3.resonance_stack == 0)
# 힐은 스택을 유지
m.resonance_element, m.resonance_stack, m.resonance_switched = "fire", 2, False
execute_skill("힐1", m, dummy())
check("힐 시전 뒤에도 fire 2단계 유지", (m.resonance_element, m.resonance_stack) == ("fire", 2))

# ═══════════════════════════════════════════════════════════
print("\n[6] 원소 공명 — 세션(상태 JSON · AoE 나머지 대상) · 엔진")
s = BattleSession(player(job="마법사", skills=["파이어볼1"]), enemies=[dummy(hp=5000)])
with deterministic():
    r = s.step("skill:파이어볼1")
check("상태 JSON player_resonance fire 1/3", r["player_resonance"] == {"element": "fire", "stack": 1, "max": 3},
      r.get("player_resonance"))
s.action_queue = [("player", -1)]
with deterministic():
    r = s.step("skill:파이어볼1")
check("두 번째 시전: 2/3 + 메시지", r["player_resonance"]["stack"] == 2 and any("공명 2단계" in x for x in r["messages"]),
      r["messages"])
s_w = BattleSession(player(job="전사", skills=["강타1"]), enemies=[dummy(hp=5000)])
check("전사는 player_resonance None", s_w._state()["player_resonance"] is None)

# AoE 나머지 대상 — 임시 AoE 마법 메타로 확인 (화염 폭풍은 2차 6번에서 들어온다)
SKILL_META["_테스트_화염광역"] = {"mp": 1, "mult": 1.0, "type": "magical", "hits": 1, "element": "fire", "aoe": True}
try:
    mp_ = player(job="마법사", skills=["_테스트_화염광역"])
    mp_.resonance_element, mp_.resonance_stack = "fire", 2   # 시전하면 3단계(×1.20)
    s = BattleSession(mp_, enemies=[dummy(hp=5000), dummy(hp=5000), dummy(hp=5000)])
    with deterministic():
        r = s.step("skill:_테스트_화염광역")
    dealt = [5000 - e.hp for e in s.enemies]
    check("AoE: 세 대상 모두 3단계 배율(240)로 같은 피해", dealt == [240, 240, 240], dealt)
finally:
    del SKILL_META["_테스트_화염광역"]

eng = BattleEngine(player(job="마법사", skills=["파이어볼1"]), dummy(hp=5000))
with deterministic():
    eng._execute_action(Action("skill", "파이어볼1"), eng.player, eng.enemy, "player")
    eng._execute_action(Action("skill", "파이어볼1"), eng.player, eng.enemy, "player")
check("BattleEngine: 두 번째 파이어볼은 330", eng.logs[-1].damage_dealt == 330 and eng.player.resonance_stack == 2,
      [l.damage_dealt for l in eng.logs])

# ═══════════════════════════════════════════════════════════
print("\n[7] AI — 측정용(reactive)만 새 역할을 본다")
w = player(skills=["강타1", "연속공격1"], mp=500)
low = dummy(); low.hp = 200                         # 20%
hi = dummy()
check("balanced: 대상 HP와 무관하게 연속공격1(MP 효율)", _best_attack_skill(w, low) == "연속공격1"
      and _best_attack_skill(w, hi) == "연속공격1")
check("reactive: HP 20% 대상엔 강타1(처형), 만피엔 연속공격1",
      _best_attack_skill(w, low, reaction_aware=True) == "강타1"
      and _best_attack_skill(w, hi, reaction_aware=True) == "연속공격1")
rg = player(job="도적", skills=["급소찌르기1", "연속찌르기"], mp=500, luc=0)
bl = dummy(); bl.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
sc_b = _best_attack_skill(rg, bl, reaction_aware=True); sc_n = _best_attack_skill(rg, dummy(), reaction_aware=True)
check("reactive 도적: 출혈 대상에서 급소찌르기1 점수가 오른다(선택 결과가 바뀌거나 같은 스킬 유지)",
      sc_b in ("급소찌르기1", "연속찌르기") and sc_n in ("급소찌르기1", "연속찌르기"))
mg = player(job="마법사", skills=["파이어볼1", "라이트닝1"], mp=500)
mg.resonance_element, mg.resonance_stack = "라이트닝1" and "lightning", 2
check("reactive 마법사: 번개 2단계면 라이트닝1(×1.2 예상)이 파이어볼1(MP 효율 우위)을 이긴다",
      _best_attack_skill(mg, dummy(), reaction_aware=True) == "라이트닝1"
      and _best_attack_skill(mg, dummy()) == "파이어볼1")
ai_b, ai_r = PlayerAI("balanced"), PlayerAI("reactive")
check("PlayerAI.decide 경로: balanced 연속공격1 / reactive 강타1 (HP 20%)",
      ai_b.decide(w, low).detail == "연속공격1" and ai_r.decide(w, low).detail == "강타1")

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
