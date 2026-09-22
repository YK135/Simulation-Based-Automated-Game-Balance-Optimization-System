# -*- coding: utf-8 -*-
"""
test_new_skills.py — 신규 스킬 6종 회귀 테스트 (Combat Content Brief 9·10장 · 11-1 2차 6번)

검증 대상:
  · 해금 테이블 — 전사 방패치기(8)·피의 격노(11), 마법사 화염 폭풍(7)·원소 폭발(9), 도적 패 고치기(8)·피의 수확(19)
  · 화염 폭풍 — AoE fire 0.95배, 명중한 모든 대상에 점화 확정(회피·면역은 제외), 공명 단계 반영
  · 원소 폭발 — 대상 부착 원소의 상대 원소 주입(ice→fire 융해 / fire→lightning / lightning→fire 과부하),
    부착 원소가 없으면 사용 불가(usable False + reason, 무효 요청은 MP 없이 차례만 소비), 공명에 주입 원소 반영
  · 방패치기 — 0.70배 + 명중 시 대상 ATB −25, 보스·엘리트는 −12 · 전투당 3회(4회째 피해만), 회피 시 감소 없음,
    BattleEngine도 같은 규칙
  · 피의 격노 — MP 0 · 현재 HP 15% 지불(1 미만으로 안 내려감) · 8턴 흡혈 25% (10-4 상한은 test_bleed_lifesteal)
    (지속 3턴 → 8턴: 후속 ①. 수지가 안 맞은 원인이 행동 비용이었다 — TestFile/test_vamp_mark_tuning.py)
  · 패 고치기 — 배우면 다음 주사위가 미리 보이고(전투 시작·소비 직후 굴림), 시전은 MP만 쓰는 재굴림(턴 소비 없음),
    전투당 3회, 다음 공격이 소비, 상태 JSON player_dice, 엔진 동일 (턴을 쓰는 첫 형태는 dice_fix_measure.py에서 손해로 측정)
  · 피의 수확 — 출혈 스택 전부 소비 → 스택당 maxHP 6% 고정 피해(보스·엘리트 3%), 출혈 없으면 사용 불가
  · get_skills usable/reason, AI: balanced는 신규 스킬(화염 폭풍 제외)을 고르지 않고 reactive만 규칙대로 사용,
    PlayerPowerIndex 축 가산(기존 스킬만이면 0)
DB를 쓰지 않는다.

실행: python3 TestFile/test_new_skills.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import (
    EntitySnapshot, StatusEffect, Action, BattleEngine, SKILL_META, execute_skill,
    skill_requirement_error, consume_atb_drain, harvest_damage, skill_effective_element, REACT_PARTNER,
)
from ai.battle import Damage as D
from ai.battle import Skills as SK
from ai.battle.Elements import REACTION_EFFECTS, MAGE_REACTION_BONUS
from ai.Auto_AI import PlayerAI, _best_attack_skill
from ai.Simulator import PlayerPowerIndex
from game.Lv import JOB_SKILL_UNLOCKS
import ai.battle_session.Player_Actions as PA
import ai.battle.Engine as EN

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
    """난수·크리·회피 끔. Skills.random=1.0(확률 디버프 미발동), Skills.randint는 상한(패 고치기 눈 = 6)."""
    def __enter__(self):
        self.ru, self.ri, self.sr, self.sri = D.uniform, D.randint, SK.random, SK.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        SK.random = lambda: 1.0
        SK.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint, SK.random, SK.randint = self.ru, self.ri, self.sr, self.sri


class skills_dice:
    """패 고치기의 눈(Skills.randint)만 고정."""
    def __init__(self, v): self.v = v
    def __enter__(self):
        self.old = SK.randint; SK.randint = lambda a, b: self.v
    def __exit__(self, *a):
        SK.randint = self.old


def ent(name="용사", hp=2000, stg=100, sp=100, mp=500, job="전사", skills=None, spd=50.0, et="", **kw):
    return EntitySnapshot(name=name, hp=hp, maxhp=hp, mp=mp, maxmp=mp, stg=stg, arm=0, sparm=0, sp=sp,
                          luc=0, lv=15, spd=spd, job=job, learned_skills=list(skills or []), items=[],
                          enemy_type=et, **kw)


def dummy(hp=5000, spd=1.0, et="슬라임", **kw):
    return ent("허수아비", hp=hp, stg=20, sp=10, job="", spd=spd, et=et, **kw)


# ═══════════════════════════════════════════════════════════
print("\n[1] 해금 테이블")
u = JOB_SKILL_UNLOCKS
from game.Lv import JOB_SKILL_CHOICES
# 2차 8번에서 전사의 방패치기·피의 격노는 Lv11 2택 1로 옮겼다 (test_remaining_skills.py가 선택 규칙을 본다)
check("전사 Lv11 2택 1: 피의 격노 ↔ 방패치기 (자동 해금 표에는 없음)",
      JOB_SKILL_CHOICES["전사"][11] == ("피의 격노", "방패치기")
      and all("방패치기" not in v and "피의 격노" not in v for v in u["전사"].values()))
check("마법사 7 화염 폭풍 / 9 원소 폭발", u["마법사"][7] == ["화염 폭풍"] and u["마법사"][9] == ["원소 폭발"])
check("도적 8 패 고치기 / 19 피의 수확", u["도적"][8] == ["패 고치기"] and u["도적"][19] == ["피의 수확"])
check("6종 모두 SKILL_META에 있음", all(k in SKILL_META for k in ("화염 폭풍", "원소 폭발", "방패치기", "피의 격노", "패 고치기", "피의 수확")))

# ═══════════════════════════════════════════════════════════
print("\n[2] 화염 폭풍")
m = ent(job="마법사", skills=["화염 폭풍"])
s = BattleSession(m, enemies=[dummy(), dummy(), dummy(et="화염 슬라임")])
s.enemies[2].element_queue = ["fire"]           # 화염 슬라임: fire 면역
with deterministic():
    r = s.step("skill:화염 폭풍")
dealt = [5000 - e.hp for e in s.enemies]
check("두 슬라임 190(0.95×200) 피해, 화염 슬라임 0(면역)", dealt[0] == 190 and dealt[1] == 190 and dealt[2] == 0, dealt)
ign = [any(x.effect_type == "ignite" for x in e.status_effects) for e in s.enemies]
check("명중 대상 둘 다 점화 확정, 면역 대상은 없음", ign == [True, True, False], ign)
check("MP 16 소모, 공명 fire 1단계", s.player.mp == 484 and s.player.resonance_element == "fire" and s.player.resonance_stack == 1)
check("action_fx는 와이드(aoe) 1회", r["action_fx"] and r["action_fx"].get("scope") == "aoe", r.get("action_fx"))

# ═══════════════════════════════════════════════════════════
print("\n[3] 원소 폭발")
check("판정표 ice→fire / fire→lightning / lightning→fire", REACT_PARTNER == {"ice": "fire", "fire": "lightning", "lightning": "fire"})
m = ent(job="마법사", skills=["원소 폭발", "파이어볼1"])
t = dummy()
check("부착 원소 없음 → 사용 불가(no_element)", skill_requirement_error("원소 폭발", m, t) == "no_element"
      and skill_effective_element(SKILL_META["원소 폭발"], t) == "")
t.element_queue = ["ice"]
check("ice 부착 → 주입 원소 fire, 사용 가능", skill_effective_element(SKILL_META["원소 폭발"], t) == "fire"
      and skill_requirement_error("원소 폭발", m, t) == "")
with deterministic():
    d, lack, info = execute_skill("원소 폭발", m, t)
raw = int(200 * 1.2)                                               # 240
expect = raw + int(raw * (REACTION_EFFECTS["melt"]["bonus_mult"] + MAGE_REACTION_BONUS - 1.0))
check("ice에 원소 폭발 = 240 + 융해(1.5+0.05) 보너스 = 372", d == expect and "융해" in info, (d, expect, info))
check("주입 원소가 공명에 반영(fire 1단계)", m.resonance_element == "fire" and m.resonance_stack == 1)
check("반응 뒤 큐 초기화(슬라임은 고유 원소 없음)", t.element_queue == [])
# lightning → fire(과부하), fire → lightning(과부하)
for pre in ("lightning", "fire"):
    t2 = dummy(); t2.element_queue = [pre]
    with deterministic():
        d2, _, info2 = execute_skill("원소 폭발", m, t2)
    check(f"{pre} 부착 → 과부하", "과부하" in info2, info2)
# 세션: 무효 요청은 MP 없이 차례만 소비
s = BattleSession(ent(job="마법사", skills=["원소 폭발"]), enemies=[dummy()])
mp0 = s.player.mp
r = s.step("skill:원소 폭발")
check("세션 무효 요청: MP 그대로, skill_failed(no_element), 메시지", s.player.mp == mp0
      and s.logs[-1].action == "skill_failed" and "no_element" in s.logs[-1].action_detail
      and any("부착된 원소가 없음" in x for x in r["messages"]), (s.logs[-1], r["messages"]))
sk = next(x for x in r["skills"] if x["name"] == "원소 폭발")
check("get_skills: usable False + reason", sk["usable"] is False and sk["reason"] == "대상에 부착된 원소가 없음", sk)
s.enemies[0].element_queue = ["ice"]
sk = next(x for x in s.get_skills() if x["name"] == "원소 폭발")
check("대상에 ice가 붙으면 usable True", sk["usable"] is True and sk["reason"] == "")

# ═══════════════════════════════════════════════════════════
print("\n[4] 방패치기")
w = ent(skills=["방패치기"])
s = BattleSession(w, enemies=[dummy(hp=10000)])
s.enemy_atbs[0] = 60.0
with deterministic():
    r = s.step("skill:방패치기")
check("0.70배 = 140 피해, 대상 ATB 60 → 35 (+행동 후 SPD 1)", s.logs[-1].damage_dealt == 140
      and abs(s.enemy_atbs[0] - (60 - 25 + 1.0)) < 1e-9, (s.logs[-1].damage_dealt, s.enemy_atbs[0]))
check("메시지 'ATB −25'", any("ATB −25" in x for x in r["messages"]), r["messages"])
# 보스·엘리트: −12, 3회
boss = dummy(hp=10000, et="중간 보스")
s = BattleSession(ent(skills=["방패치기"]), enemies=[boss])
drains = []
for i in range(4):
    s.action_queue = [("player", -1)]
    s.enemy_atbs[0] = 50.0
    with deterministic():
        s.step("skill:방패치기")
    drains.append(round(50.0 + 1.0 - s.enemy_atbs[0], 3))
check("보스: −12 × 3회, 4회째 0", drains == [12.0, 12.0, 12.0, 0.0] and s.player.atb_drain_uses == 3, drains)
el = dummy(hp=10000, elite_leader=True, is_elite=True)
check("엘리트 리더도 반감 대상(consume_atb_drain 12)", consume_atb_drain("방패치기", ent(skills=["방패치기"]), el) == 12.0)
# 회피 시 감소 없음
s = BattleSession(ent(skills=["방패치기"]), enemies=[dummy(hp=10000, dodge_bonus=0.5)])
s.enemy_atbs[0] = 60.0
_old = D.randint
D.randint = lambda a, b: 1            # 회피 판정 1 ≤ 50 → 회피
try:
    r = s.step("skill:방패치기")
finally:
    D.randint = _old
check("회피하면 ATB 그대로(+SPD)", s.logs[-1].damage_dealt == 0 and abs(s.enemy_atbs[0] - 61.0) < 1e-9,
      (s.logs[-1].damage_dealt, s.enemy_atbs[0]))
eng = BattleEngine(ent(skills=["방패치기"]), dummy(hp=10000))
eng.atb.enemy_pt = 60.0
with deterministic():
    eng._execute_action(Action("skill", "방패치기"), eng.player, eng.enemy, "player")
check("BattleEngine: 명중 시 적 ATB 60 → 35", abs(eng.atb.enemy_pt - 35.0) < 1e-9, eng.atb.enemy_pt)

# ═══════════════════════════════════════════════════════════
print("\n[5] 피의 격노")
w = ent(skills=["피의 격노"], mp=0)
w.hp = 1000
d, lack, info = execute_skill("피의 격노", w, dummy())
lb = [b for b in w.buffs if b.stat == "lifesteal"]
check("MP 0으로도 시전, HP 1000 → 850, 흡혈 버프 25% 8턴", not lack and w.hp == 850 and lb and lb[0].amount == 0.25 and lb[0].turns == 8,
      (w.hp, w.buffs))
w.hp = 1.0
execute_skill("피의 격노", w, dummy())
check("HP 1에서도 죽지 않음(max 1)", w.hp == 1.0)
s = BattleSession(ent(skills=["피의 격노"]), enemies=[dummy()])
r = s.step("skill:피의 격노")
check("세션 메시지: HP 지불 + 흡혈 25%", any("지불" in x and "흡혈 25%" in x for x in r["messages"]), r["messages"])
sk = next(x for x in r["skills"] if x["name"] == "피의 격노")
check("get_skills hp_cost 15", sk["hp_cost"] == 15 and sk["mp"] == 0, sk)

# ═══════════════════════════════════════════════════════════
print("\n[6] 패 고치기")
rg = ent(job="도적", skills=["패 고치기"])
with skills_dice(5):
    d, lack, info = execute_skill("패 고치기", rg, dummy())
check("저장 주사위 5, 사용 1회, info dice:5", rg.pending_dice == 5 and rg.dice_fix_uses == 1 and info == "dice:5")
with skills_dice(2):
    execute_skill("패 고치기", rg, dummy()); execute_skill("패 고치기", rg, dummy())
check("재시전 = 재굴림(2), 3회 사용", rg.pending_dice == 2 and rg.dice_fix_uses == 3)
check("4회째는 max_uses로 불가", skill_requirement_error("패 고치기", rg, dummy()) == "max_uses")
mp_before = rg.mp
d, lack, info = execute_skill("패 고치기", rg, dummy())
check("안전망: 4회째 execute_skill은 MP 안 쓰고 무효", not lack and info == "" and rg.mp == mp_before and rg.pending_dice == 2)
# 세션: 배우면 시작부터 다음 눈이 보이고, 시전은 턴을 쓰지 않는 재굴림
with skills_dice(2):
    s = BattleSession(ent(job="도적", skills=["패 고치기"]), enemies=[dummy()])
check("전투 시작: 다음 주사위 미리 보기(2)", s.player.pending_dice == 2 and s._state()["player_dice"] == {"pending": 2, "rerolls_left": 3, "free_rerolls": 0})
check("스킬이 없는 도적은 미리 보기 없음(0)", BattleSession(ent(job="도적", skills=["급소찌르기1"]), enemies=[dummy()]).player.pending_dice == 0)
turn0, q0 = s.turn, list(s.action_queue)
with skills_dice(6):
    r = s.step("skill:패 고치기")
check("재굴림: 메시지 + player_dice {pending 6, rerolls_left 2}, MP −6", any("다시 굴렸다: 6" in x for x in r["messages"])
      and r["player_dice"] == {"pending": 6, "rerolls_left": 2, "free_rerolls": 0} and s.player.mp == 494, (r["messages"], r.get("player_dice")))
check("자유 행동: 턴·큐·행동 카운터 그대로, 다음 행동자는 여전히 플레이어",
      s.turn == turn0 and s.action_queue == q0 and s._player_action_count == 0 and r["next_actor"] == "player")
with deterministic():
    r = s.step("attack")
check("다음 공격이 미리 본 6을 소비 → 치명타 확정, 새 눈이 바로 다시 보인다(6: 결정적 상한)",
      any("주사위: 6" in x and "미리 본 눈" in x for x in r["messages"]) and s.logs[-1].is_crit
      and s.player.pending_dice == 6 and s.turn == turn0 + 1, (r["messages"], s.player.pending_dice))
s.action_queue = [("player", -1)]        # 공격으로 차례가 넘어갔으므로 다시 플레이어 차례로
with skills_dice(1):
    s.step("skill:패 고치기"); s.step("skill:패 고치기")
r = s.step("skill:패 고치기")
check("4회째 재굴림은 거부되지만 차례는 남는다", s.player.dice_fix_uses == 3 and r["next_actor"] == "player"
      and any("사용 횟수 소진" in x for x in r["messages"]), r["messages"])
with skills_dice(6):
    eng = BattleEngine(ent(job="도적", skills=["패 고치기"]), dummy())
check("BattleEngine: 시작 미리 보기 6", eng.player.pending_dice == 6)
with deterministic():
    eng._execute_action(Action("attack", "attack"), eng.player, eng.enemy, "player")
check("BattleEngine: 미리 본 6 → 크리, 소비 후 새 눈", eng.logs[-1].is_crit and eng.player.pending_dice == 6)
# 엔진 run(): 자유 행동은 차례를 넘기지 않는다 — 재굴림 뒤 같은 틱에 공격까지
calls = []
def stub_ai(p, e, **kw):
    calls.append(p.pending_dice)
    return Action("skill", "패 고치기") if p.pending_dice < 3 and p.dice_fix_uses < 3 else Action("attack", "attack")
with skills_dice(1):
    eng2 = BattleEngine(ent(job="도적", skills=["패 고치기"], spd=100.0), dummy(hp=100000))
    eng2.atb.player_pt = 100.0
    eng2.tick_count = 0
eng2.MAX_TICKS = 1
with skills_dice(1):                                # 재굴림도 계속 1 → 상한(3회)까지 굴린 뒤 공격
    eng2.run(stub_ai, lambda a, d, **kw: Action("attack", "attack"))
check("엔진 run(): 눈 1 → 재굴림 3회(상한) 뒤 공격 1회 — 한 틱 안에서", eng2.player.dice_fix_uses == 3
      and any(l.action == "attack" for l in eng2.logs) and len(calls) >= 4, (calls, eng2.player.dice_fix_uses))
check("전사에게는 player_dice None", BattleSession(ent(skills=["강타1"]), enemies=[dummy()])._state()["player_dice"] is None)

# ═══════════════════════════════════════════════════════════
print("\n[7] 피의 수확")
rg = ent(job="도적", skills=["피의 수확"])
t = dummy(hp=1000)
check("출혈 없음 → 사용 불가(no_bleed)", skill_requirement_error("피의 수확", rg, t) == "no_bleed")
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=3))
check("harvest_damage: 3스택 × 6% = 180", harvest_damage(SKILL_META["피의 수확"], t) == (3, 180))
d, lack, info = execute_skill("피의 수확", rg, t)
check("고정 피해 180, 출혈 소비, info harvest:3", d == 180 and info == "harvest:3"
      and not any(x.effect_type == "bleed" for x in t.status_effects), (d, info, t.status_effects))
b = dummy(hp=1000, et="중간 보스")
b.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=3))
check("보스: 3스택 × 3% = 90", harvest_damage(SKILL_META["피의 수확"], b) == (3, 90))
e = dummy(hp=1000, elite_leader=True)
e.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=2))
check("엘리트: 2스택 × 3% = 60", harvest_damage(SKILL_META["피의 수확"], e) == (2, 60))
s = BattleSession(ent(job="도적", skills=["피의 수확"]), enemies=[dummy(hp=1000, dodge_bonus=1.0)])
s.enemies[0].apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=2))
r = s.step("skill:피의 수확")
check("세션: 회피 100% 대상에도 고정 피해 120 · 출혈 제거 · 메시지", s.logs[-1].damage_dealt == 120
      and any("출혈 2스택" in x for x in r["messages"]) and not s.enemies[0].status_effects, (s.logs[-1], r["messages"]))
s = BattleSession(ent(job="도적", skills=["피의 수확"]), enemies=[dummy()])
mp0 = s.player.mp
r = s.step("skill:피의 수확")
check("세션 무효 요청(출혈 없음): MP 그대로 + skill_failed(no_bleed)", s.player.mp == mp0 and "no_bleed" in s.logs[-1].action_detail)

# ═══════════════════════════════════════════════════════════
print("\n[8] AI — balanced 불변 / reactive 사용 규칙 / PowerIndex 축")
w = ent(skills=["강타1", "연속공격1", "방패치기", "피의 격노"], mp=500)
fast = dummy(spd=80.0)
b, rr = PlayerAI("balanced"), PlayerAI("reactive")
check("balanced 전사: 신규 스킬을 고르지 않는다(연속공격1)", b.decide(w, fast).detail == "연속공격1")
# 피의 격노 손익 — 지속 8턴 재조정(후속 ①) 뒤의 기준은 "회수할 시간이 있는 전투인가"다.
#   허수아비 HP 5000: 덮는 행동 7회 × 회수 80(연속공격1 2타 × 40) = 560 > 지불 300 → 만피에서도 쓴다.
#   (3턴이던 때는 덮는 행동이 2회뿐이라 160 < 300으로 안 썼다 — 그게 수지가 안 맞던 이유다.)
check("reactive 전사: 오래 버틸 적에게는 격노를 쓴다", rr.decide(w, fast).detail == "피의 격노")
#   같은 만피인데 적이 허약하면(HP 400 ≒ 1.25행동) 회수할 시간이 없다 — 지속 상한이 아니라
#   "남은 적 HP ÷ 1행동 피해"가 덮는 행동 수를 자른다.
frail = dummy(hp=400, spd=80.0)
check("reactive 전사: 곧 끝나는 전투에는 격노를 안 쓴다", rr.decide(w, frail).detail != "피의 격노")
from ai.battle import Buff
w.apply_buff(Buff(stat="lifesteal", amount=0.25, turns=8, name="피의 격노"))
check("reactive 전사: 버프 중 + 상대가 빠르면 방패치기", rr.decide(w, fast).detail == "방패치기")
w.atb_drain_uses = 3
boss = dummy(spd=80.0, et="중간 보스")
check("reactive 전사: 보스 상한 소진이면 방패치기 안 씀", rr.decide(w, boss).detail != "방패치기")
rg = ent(job="도적", skills=["급소찌르기1", "패 고치기", "피의 수확"], mp=500)
t = dummy()
rg.pending_dice = 2
check("reactive 도적: 미리 본 눈이 3 미만이면 재굴림(자유 행동)", rr.decide(rg, t).detail == "패 고치기")
rg.pending_dice = 5
check("reactive 도적: 눈 5면 공격", rr.decide(rg, t).detail == "급소찌르기1")
t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=3))
check("reactive 도적: 출혈 3스택이면 피의 수확", rr.decide(rg, t).detail == "피의 수확")
rg2 = ent(job="도적", skills=["급소찌르기1", "패 고치기", "피의 수확"], mp=500)
check("balanced 도적: 출혈 3스택이면 피의 수확도 공격 후보(MP당 피해로 이김), 패 고치기는 절대 안 씀",
      b.decide(rg2, t).detail == "피의 수확" and b.decide(rg2, dummy()).detail == "급소찌르기1")
mg = ent(job="마법사", skills=["파이어볼1", "원소 폭발"], mp=500)
t = dummy(); t.element_queue = ["ice"]
from ai.Auto_AI import _reaction_bonus
check("reactive 마법사: 원소 폭발은 ice 대상에서 융해(1.5+0.05) 확정 가점을 받는다",
      abs(_reaction_bonus(SKILL_META["원소 폭발"], t, mg) - 1.55) < 1e-9)
check("같은 대상에 파이어볼1도 융해가 나므로 MP 효율이 좋은 파이어볼1이 이긴다(설계 수치 그대로 — 보고 대상)",
      _best_attack_skill(mg, t, reaction_aware=True) == "파이어볼1")
t2 = dummy()
check("부착 원소 없으면 원소 폭발은 후보에서 빠진다", _best_attack_skill(mg, t2, reaction_aware=True) == "파이어볼1"
      and _best_attack_skill(mg, t2) == "파이어볼1")
mg3 = ent(job="마법사", skills=["파이어볼1", "화염 폭풍"], mp=500)
check("balanced 마법사: 적 3마리면 화염 폭풍(광역 효율)", _best_attack_skill(mg3, dummy(), enemy_count=3) == "화염 폭풍"
      and _best_attack_skill(mg3, dummy(), enemy_count=1) == "파이어볼1")
old_p = ent(skills=["강타1", "연속공격1", "슬래시1"])
new_p = ent(skills=["강타1", "방패치기", "피의 격노"])
check("PowerIndex 축: 기존 스킬만이면 0, 방패치기+피의 격노는 tempo·sustain 2축",
      PlayerPowerIndex.skill_axes(old_p) == set() and PlayerPowerIndex.skill_axes(new_p) == {"tempo", "sustain"})
check("PowerIndex calc: 축 2개 → +0.08", abs(PlayerPowerIndex.calc(new_p) - PlayerPowerIndex.calc(old_p) - 0.08) < 1e-9
      or PlayerPowerIndex.calc(new_p) == 2.0, (PlayerPowerIndex.calc(new_p), PlayerPowerIndex.calc(old_p)))

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
