# -*- coding: utf-8 -*-
"""
test_remaining_skills.py — 남은 신규 스킬 11종 + 스킬 2택 1 회귀 테스트 (Combat Content Brief 10장 · 10-6 · 11-1 2차 8번)

검증 대상:
  · 전사 — 불굴(HP 35% 이하·전투당 1회, 실드 25% + 피해 −20% 2턴) / 광풍 베기(AoE 0.90 + 시전 흡혈 8%) /
    철벽 의지(피해 −20% + 흡혈량 2배 3턴) / 피의 맹세(흡혈 40% 3턴, 만료 시 현재 HP 20% 지불 · 죽지 않음)
  · 마법사 — 연쇄 번개(AoE lightning 0.80, 원소 부착 대상 ×1.3) / 마나 장막(받는 피해 50% MP 대납) /
    서리 결계(나를 공격한 적에게 ice + SPD −10%, 세션·엔진)
  · 도적 — 약점 표식(받는 피해 +8%, 주사위 5 크리) / 혈흔 추적(출혈 대상 명중 시 ATB +25) /
    연막(회피 +35%, 회피 성공 시 패 고치기 무료 재굴림) / 칼날 폭풍(AoE 0.70×2, 타격마다 출혈 40%)
  · 공용 — damage_taken_mult가 버프 없으면 정확히 1.0, heal_taken_mult가 모든 회복에 곱해짐
  · 2택 1 — 표(직업당 3쌍), 레벨업 시 대기열, 확정 검증(없는 레벨·짝 아닌 스킬 거절), 기존 스킬 대체,
    auto_resolve 정책, 직렬화, _player_dict 선택지, /api/skill/choose(전투 중 거절)
  · AI — balanced는 불굴을 조건이 안 맞을 때 고르지 않는다, reactive 사용 규칙
DB는 Flask test_client 경로에서 init_db()만 거친다.

실행: python3 TestFile/test_remaining_skills.py
"""
import sys, os, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai.Battlesession import BattleSession
from ai.battle import (
    EntitySnapshot, StatusEffect, Buff, Debuff, Action, BattleEngine, SKILL_META, execute_skill,
    skill_requirement_error, LifestealCast, lifesteal_heal, _apply_damage_with_shield,
)
from ai.battle import Damage as D
from ai.battle import Skills as SK
from ai.battle.Skills import rogue_dice_crit, has_weak_mark, frost_ward_retaliate, attached_bonus_mult
from ai.Auto_AI import PlayerAI, _best_shield_skill
from game.Lv import (
    JOB_SKILL_UNLOCKS, JOB_SKILL_CHOICES, LV_, resolve_skill_choice, auto_resolve_skill_choices,
)
from game.Player_Class import Player, create_player_by_job
import ai.battle_session.Player_Actions as PA
import ai.battle.Engine as EN
from _helpers import make_session_dict, inject_test_session

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
    """난수·크리·회피 끔 + Skills.random=1.0(확률 효과 미발동)."""
    def __enter__(self):
        self.o = (D.uniform, D.randint, SK.random, SK.randint)
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        SK.random = lambda: 1.0
        SK.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint, SK.random, SK.randint = self.o


def ent(name="용사", hp=1000, stg=100, sp=100, mp=500, job="", skills=None, spd=50.0, et="", **kw):
    return EntitySnapshot(name=name, hp=hp, maxhp=hp, mp=mp, maxmp=mp, stg=stg, arm=0, sparm=0, sp=sp,
                          luc=0, lv=20, spd=spd, job=job, learned_skills=list(skills or []), items=[],
                          enemy_type=et, **kw)


def dummy(hp=100000, spd=1.0, stg=100, **kw):
    return ent("허수아비", hp=hp, stg=stg, sp=10, job="", spd=spd, et="슬라임", **kw)


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# ═══════════════════════════════════════════════════════════
print("\n[0] 공용 배율")
e = ent()
check("버프 없으면 damage_taken_mult == 1.0 (정확히)", e.damage_taken_mult() == 1.0)
check("heal_value 기본 그대로", e.heal_value(123.4) == 123.4)
e.apply_buff(Buff(stat="dmg_reduction", amount=0.2, turns=2, name="x"))
e.apply_debuff(Debuff(stat="vulnerable", amount=0.08, turns=3, name="약점 표식"))
check("경감 0.2 × 취약 0.08 → 0.864", abs(e.damage_taken_mult() - 0.8 * 1.08) < 1e-9)
e.boss_guard = 0.25
check("보스 경감까지 곱 → 0.648", abs(e.damage_taken_mult() - 0.8 * 1.08 * 0.75) < 1e-9)
t = ent(); t.hp = 1000
check("_apply_damage_with_shield가 배율 적용 (100 → 80)", _apply_damage_with_shield(
    (lambda x: (x.apply_buff(Buff(stat="dmg_reduction", amount=0.2, turns=2, name="x")), x)[1])(t), 100) == 80 and t.hp == 920)

# ═══════════════════════════════════════════════════════════
print("\n[1] 전사 — 불굴 · 광풍 베기 · 철벽 의지 · 피의 맹세")
w = ent(job="전사", skills=["불굴"])
check("HP 100%: 불굴 불가(hp_high)", skill_requirement_error("불굴", w, None) == "hp_high")
w.hp = 300
check("HP 30%: 가능", skill_requirement_error("불굴", w, None) == "")
d, lack, info = execute_skill("불굴", w, dummy())
check("실드 250 + 피해 경감 20% 2턴 + 사용 기록", w.shield == 250 and w.buff_amount("dmg_reduction") == 0.2
      and w.buffs[0].turns == 2 and "불굴" in w.once_used, (w.shield, w.buffs, w.once_used))
check("두 번째는 used", skill_requirement_error("불굴", w, None) == "used")
check("balanced 실드 선택: 불굴을 조건 밖(HP 45%)에선 고르지 않음", (lambda p: (setattr(p, "hp", 450), _best_shield_skill(p))[1])(
    ent(job="전사", skills=["불굴"])) is None)

s = BattleSession(ent(skills=["광풍 베기"]), enemies=[dummy(), dummy(), dummy()])
s.player.hp = 500
with deterministic():
    r = s.step("skill:광풍 베기")
dealt = [100000 - x.hp for x in s.enemies]
# 180 피해 × 8% = 14.4 × 3 = 43.2
check("광풍 베기: 세 대상 180, 시전 흡혈 8% → +43.2", dealt == [180, 180, 180] and abs(s.player.hp - 543.2) < 1e-6,
      (dealt, s.player.hp))
check("흡혈 메시지 3회", sum("흡혈 +" in m for m in r["messages"]) == 3, r["messages"])

w = ent(job="전사", skills=["철벽 의지"])
execute_skill("철벽 의지", w, dummy())
check("철벽 의지: 경감 0.2 + 흡혈량 +1.0, 3턴", w.buff_amount("dmg_reduction") == 0.2 and w.buff_amount("lifesteal_amp") == 1.0
      and all(b.turns == 3 for b in w.buffs))
w.apply_buff(Buff(stat="lifesteal", amount=0.1, turns=3, name="피의 격노"))
check("흡혈량 2배: 0.1 → 0.2", abs(w.effective_lifesteal() - 0.2) < 1e-9)
check("흡혈량 가산은 시전 보너스에도 곱한다", abs(lifesteal_heal((lambda x: (setattr(x, "hp", 100), x)[1])(w), 100, LifestealCast(w, bonus=0.08))
                                         - min(100 * (0.2 + 0.16), 40)) < 1e-9)

w = ent(job="전사", skills=["피의 맹세"])
execute_skill("피의 맹세", w, dummy())
check("피의 맹세: lifesteal_oath 0.4, 격노와 다른 stat", w.buff_amount("lifesteal_oath") == 0.4)
w.apply_buff(Buff(stat="lifesteal", amount=0.25, turns=3, name="피의 격노"))
check("격노와 합산 0.65 (서로 덮어쓰지 않음)", abs(w.effective_lifesteal() - 0.65) < 1e-9)
w.hp = 800
m1 = w.tick_buffs(); m2 = w.tick_buffs()
check("2턴 지나도 비용 없음", w.hp == 800 and not m1 and not m2)
m3 = w.tick_buffs()
check("만료 시 현재 HP 20% 지불(800 → 640) + 메시지", w.hp == 640 and any("피의 맹세" in x and "지불" in x for x in m3), m3)
w2 = ent(skills=["피의 맹세"]); execute_skill("피의 맹세", w2, dummy()); w2.hp = 1
for _ in range(3):
    w2.tick_buffs()
check("HP 1에서 만료돼도 죽지 않음", w2.hp == 1.0)
# 세션: 3턴 버프는 시전한 행동의 끝에서부터 줄어든다(강화 등 기존 버프와 같은 규칙) — 시전 + 2행동 뒤 만료
s = BattleSession(ent(skills=["피의 맹세"]), enemies=[dummy()])
seen = []
r = s.step("skill:피의 맹세"); seen.append(any("피의 맹세 종료" in m for m in r["messages"]))
for _ in range(3):
    s.action_queue = [("player", -1)]
    with deterministic():
        r = s.step("attack")
    seen.append(any("피의 맹세 종료" in m for m in r["messages"]))
check("세션: 시전 뒤 두 번째 행동에서 만료 메시지 한 번", seen == [False, False, True, False], seen)

# ═══════════════════════════════════════════════════════════
print("\n[2] 마법사 — 연쇄 번개 · 마나 장막 · 서리 결계")
t1, t2 = dummy(), dummy(); t2.element_queue = ["fire"]
check("attached_bonus_mult: 원소 없으면 1.0, 있으면 1.3", attached_bonus_mult(SKILL_META["연쇄 번개"], t1) == 1.0
      and attached_bonus_mult(SKILL_META["연쇄 번개"], t2) == 1.3)
m = ent(job="", skills=["연쇄 번개"])      # 직업 패시브(마법사 반응 보너스) 없이 배율만 본다
s = BattleSession(m, enemies=[dummy(), dummy(), dummy()])
s.enemies[1].element_queue = ["ice"]             # ice + lightning은 반응 없음 → 부착 보너스만
s.enemies[2].element_queue = ["fire"]            # fire + lightning = 과부하 1.3
with deterministic():
    r = s.step("skill:연쇄 번개")
dealt = [100000 - x.hp for x in s.enemies]
# 기본 160 / ice 부착: 160×1.3=208 / fire 부착: 208 → 과부하 +62 = 270
check("연쇄 번개: 160 / 부착 208 / 부착+과부하 270", dealt == [160, 208, 270], dealt)
eng = BattleEngine(ent(skills=["연쇄 번개"]), dummy())
eng.enemy.element_queue = ["ice"]
with deterministic():
    eng._execute_action(Action("skill", "연쇄 번개"), eng.player, eng.enemy, "player")
check("엔진(첫 대상 경로)도 ×1.3 → 208", eng.logs[-1].damage_dealt == 208, eng.logs[-1].damage_dealt)

v = ent(skills=["마나 장막"], mp=100); execute_skill("마나 장막", v, dummy())
v.mp = 100
hp_dmg = _apply_damage_with_shield(v, 100)
check("마나 장막: 100 피해 → MP 50 · HP 50", v.mp == 50 and v.hp == 950 and hp_dmg == 50, (v.mp, v.hp, hp_dmg))
v.mp = 20
_apply_damage_with_shield(v, 100)
check("MP가 모자라면 그만큼만(20) → HP 80", v.mp == 0 and v.hp == 870, (v.mp, v.hp))
v2 = ent(skills=["마나 장막"]); execute_skill("마나 장막", v2, dummy()); v2.shield = 40; v2.mp = 100
_apply_damage_with_shield(v2, 100)
check("실드 먼저(40), 남은 60의 절반 MP(30) → HP 30", v2.shield == 0 and v2.mp == 70 and v2.hp == 970, (v2.shield, v2.mp, v2.hp))

p = ent(job="마법사", skills=["서리 결계"], spd=1.0)
s = BattleSession(p, enemies=[dummy(spd=20, hp=1000)])
execute_skill("서리 결계", s.player, s.enemies[0])
s._enemy_ai = lambda *a, **k: Action("attack", "attack")
with deterministic():
    r = s.step("auto")
en = s.enemies[0]
check("서리 결계: 공격한 적에게 ice + SPD −10% 2턴 + 메시지", en.element_queue == ["ice"]
      and any(d.stat == "spd" and d.amount == 0.1 and d.turns == 2 for d in en.debuffs)
      and any("서리 결계" in x for x in r["messages"]), (en.element_queue, en.debuffs, r["messages"]))
s = BattleSession(ent(job="마법사", skills=["서리 결계"], spd=1.0), enemies=[dummy(spd=20, hp=1000)])
execute_skill("서리 결계", s.player, s.enemies[0])
s._enemy_ai = lambda *a, **k: Action("skill", "둔화1")
r = s.step("auto")
check("공격이 아닌 행동(둔화1)엔 반응 없음", s.enemies[0].element_queue == [], s.enemies[0].element_queue)
ice = ent("빙결 슬라임", et="빙결 슬라임", hp=1000)
pw = ent(skills=["서리 결계"]); execute_skill("서리 결계", pw, ice)
frost_ward_retaliate(pw, ice)
check("ice 면역(빙결 슬라임)에게는 SPD만", ice.element_queue == [] and any(d.stat == "spd" for d in ice.debuffs))
eng = BattleEngine(ent(skills=["서리 결계"], spd=1.0), dummy(spd=200, hp=1000))
execute_skill("서리 결계", eng.player, eng.enemy)
eng.MAX_TICKS = 1
eng.run(lambda p_, e_, **k: Action("attack", "attack"), lambda a, d_, **k: Action("attack", "attack"))
check("엔진: 적 공격 뒤 ice 부착", eng.enemy.element_queue == ["ice"], eng.enemy.element_queue)

# ═══════════════════════════════════════════════════════════
print("\n[3] 도적 — 약점 표식 · 혈흔 추적 · 연막 · 칼날 폭풍")
r_ = ent(job="도적", skills=["약점 표식"])
t = dummy()
with deterministic():
    execute_skill("약점 표식", r_, t)
check("약점 표식: 취약 +8% 3턴, 이름으로 판별", has_weak_mark(t) and any(d.stat == "vulnerable" and d.amount == 0.08 and d.turns == 3 for d in t.debuffs))
check("rogue_dice_crit: 6 항상, 5는 표식 대상만", rogue_dice_crit(6, None) and rogue_dice_crit(5, t) and not rogue_dice_crit(5, dummy())
      and not rogue_dice_crit(4, t))
s = BattleSession(ent(job="도적"), enemies=[dummy()])
execute_skill("약점 표식", ent(job="도적", skills=["약점 표식"]), s.enemies[0])
old_ri = PA.randint
PA.randint = lambda a, b: 5
try:
    with deterministic():
        r = s.step("attack")
finally:
    PA.randint = old_ri
# 200 × 1.25(주사위 5) = 250 × 1.5(크리) = 375 × 1.08(취약) = 405
# ★ 세션 일반공격 TurnLog.damage_dealt는 원래 실드·피해 배율 적용 전 값을 적는다(기존 동작) — 실제 HP 감소로 본다
check("세션: 표식 대상에 주사위 5 → 크리 + 취약 (HP −405)", 100000 - s.enemies[0].hp == 405 and s.logs[-1].is_crit
      and any("약점 표식: 5도 치명타" in m for m in r["messages"]), (100000 - s.enemies[0].hp, r["messages"]))
eng = BattleEngine(ent(job="도적"), dummy())
execute_skill("약점 표식", ent(job="도적", skills=["약점 표식"]), eng.enemy)
old_eri = EN.randint
EN.randint = lambda a, b: 5
try:
    with deterministic():
        eng._execute_action(Action("attack", "attack"), eng.player, eng.enemy, "player")
finally:
    EN.randint = old_eri
check("엔진: 같은 405", eng.logs[-1].damage_dealt == 405, eng.logs[-1].damage_dealt)

s = BattleSession(ent(job="", skills=["혈흔 추적"]), enemies=[dummy()])
s.player_atb = 0.0
with deterministic():
    s.step("skill:혈흔 추적")
check("출혈 없는 대상: ATB = SPD 50뿐", s.player_atb == 50.0, s.player_atb)
s.enemies[0].apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
s.action_queue = [("player", -1)]; s.player_atb = 0.0
with deterministic():
    r = s.step("skill:혈흔 추적")
check("출혈 대상: ATB = 50 + 25, 메시지", s.player_atb == 75.0 and any("혈흔 추적" in m and "ATB +25" in m for m in r["messages"]),
      (s.player_atb, r["messages"]))
eng = BattleEngine(ent(skills=["혈흔 추적"]), dummy())
eng.enemy.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
with deterministic():
    eng._execute_action(Action("skill", "혈흔 추적"), eng.player, eng.enemy, "player")
check("엔진: ATB +25", eng.atb.player_pt == 25.0, eng.atb.player_pt)

sm = ent(job="도적", skills=["연막", "패 고치기"])
execute_skill("연막", sm, dummy())
check("연막: 회피 +0.35 2턴 → effective_dodge_bonus 0.35", abs(sm.effective_dodge_bonus() - 0.35) < 1e-9)
p = ent(job="도적", skills=["연막", "패 고치기"], spd=1.0)
s = BattleSession(p, enemies=[dummy(spd=20, hp=1000)])
execute_skill("연막", s.player, s.enemies[0])
s._enemy_ai = lambda *a, **k: Action("attack", "attack")
old = D.randint
calls = {"n": 0}
def ri(a, b):
    calls["n"] += 1
    return 1 if calls["n"] == 1 else b          # 첫 판정(회피)만 성공
D.randint = ri; D.uniform = lambda a, b: 1.0
try:
    r = s.step("auto")
finally:
    D.randint = old; D.uniform = __import__("random").uniform
check("연막 중 회피 → 무료 재굴림 +1 + 메시지", s.player.free_rerolls == 1 and any("무료 재굴림" in m for m in r["messages"]), r["messages"])
s.action_queue = [("player", -1)]
s.player.mp = 0
s.player.dice_fix_uses = 3
check("무료 재굴림은 MP 0·횟수 소진이어도 가능", skill_requirement_error("패 고치기", s.player, s.enemies[0]) == "")
r = s.step("skill:패 고치기")
check("재굴림: MP·횟수 그대로, 무료 1 소진, 차례 유지", s.player.mp == 0 and s.player.dice_fix_uses == 3
      and s.player.free_rerolls == 0 and r["next_actor"] == "player" and any("연막 무료 재굴림" in m for m in r["messages"]), r["messages"])

s = BattleSession(ent(job="", skills=["칼날 폭풍"]), enemies=[dummy(), dummy(), dummy()])
with deterministic():
    SK.random = lambda: 0.0                  # 출혈 판정 전부 성공
    r = s.step("skill:칼날 폭풍")
dealt = [100000 - x.hp for x in s.enemies]
stacks = [next((e.stacks for e in x.status_effects if e.effect_type == "bleed"), 0) for x in s.enemies]
check("칼날 폭풍: 대상마다 140×2=280, 타격마다 출혈 → 2스택씩", dealt == [280, 280, 280] and stacks == [2, 2, 2], (dealt, stacks))
s = BattleSession(ent(job="", skills=["칼날 폭풍"]), enemies=[dummy(), dummy()])
with deterministic():
    r = s.step("skill:칼날 폭풍")                 # SK.random = 1.0 → 출혈 없음
check("확률 실패면 출혈 없음", all(not x.status_effects for x in s.enemies))
eng = BattleEngine(ent(skills=["칼날 폭풍"]), dummy())
with deterministic():
    SK.random = lambda: 0.0
    eng._execute_action(Action("skill", "칼날 폭풍"), eng.player, eng.enemy, "player")
check("엔진(1v1 타격별 경로): 2타 × 출혈 → 2스택", next((e.stacks for e in eng.enemy.status_effects if e.effect_type == "bleed"), 0) == 2)

# ═══════════════════════════════════════════════════════════
print("\n[4] 스킬 2택 1")
C = JOB_SKILL_CHOICES
check("직업당 3쌍", all(len(C[j]) == 3 for j in ("전사", "마법사", "도적")) and "탱커" not in C)
check("선택 스킬은 자동 해금 표에 없다", all(sk not in lst for j in C for pair in C[j].values() for sk in pair
                                       for lst in JOB_SKILL_UNLOCKS[j].values()))
check("짝이 된 기존 스킬은 선택 지점으로 이동(파이어볼2 → 14, 난사2 → 16, 연막 → 25)",
      C["마법사"][14][1] == "파이어볼2" and C["도적"][16][1] == "난사2" and C["도적"][25][1] == "연막")
from game.Skill import Ply_Skill


def game_player(name, job):
    """app/Game.py new_game과 같은 방식 — Ply_Skill을 붙인 플레이어."""
    pl = quiet(create_player_by_job, name, job)
    sk = Ply_Skill(job)
    quiet(sk.update_skills, 1)
    pl.skill = sk
    pl.learned_skills = list(sk.learned_skills)
    quiet(LV_, pl)
    return pl


p = game_player("t", "마법사")
for _ in range(13):
    p.exp = p.maxexp
    quiet(LV_.Lv_up, p)
check("Lv14 도달 → 대기 [14], 둘 다 아직 없음", p.pending_skill_choices == [14]
      and "연쇄 번개" not in p.learned_skills and "파이어볼2" not in p.learned_skills, p.pending_skill_choices)
check("없는 레벨 거절", not resolve_skill_choice(p, 17, "힐2")["ok"])
check("짝이 아닌 스킬 거절", not resolve_skill_choice(p, 14, "힐2")["ok"])
res = resolve_skill_choice(p, 14, "파이어볼2")
check("기존 스킬 선택 → 파이어볼1 대체, 대기 비움, skill 객체 동기화",
      res["ok"] and "파이어볼2" in p.learned_skills and "파이어볼1" not in p.learned_skills
      and p.pending_skill_choices == [] and "파이어볼2" in p.skill.learned_skills, p.learned_skills)
check("이미 고른 레벨은 다시 못 고름", not resolve_skill_choice(p, 14, "연쇄 번개")["ok"])
for _ in range(6):
    p.exp = p.maxexp
    quiet(LV_.Lv_up, p)
check("Lv20까지 → 대기 [17, 20]", p.pending_skill_choices == [17, 20], p.pending_skill_choices)
picked = auto_resolve_skill_choices(p, "new")
check("auto new → 마나 장막·서리 결계", picked == ["마나 장막", "서리 결계"] and not p.pending_skill_choices)
q = game_player("t2", "도적")
for _ in range(24):
    q.exp = q.maxexp
    quiet(LV_.Lv_up, q)
check("도적 Lv25: 대기 [11,16,25]", q.pending_skill_choices == [11, 16, 25], q.pending_skill_choices)
q2 = Player.from_dict(q.to_dict())
check("직렬화 왕복 유지", q2.pending_skill_choices == [11, 16, 25])
check("auto old → 둔화2·난사2·연막 (둔화1·난사1 대체)", auto_resolve_skill_choices(q, "old") == ["둔화2", "난사2", "연막"]
      and "둔화1" not in q.learned_skills and "난사1" not in q.learned_skills)
import random as _r
got = auto_resolve_skill_choices(q2, "random", rng=_r.Random(3))
check("auto random: 쌍마다 하나씩", len(got) == 3 and all(g in C["도적"][lv_] for g, lv_ in zip(got, (11, 16, 25))), got)

from app.Shared import _player_dict
w = game_player("t3", "전사")
for _ in range(10):
    w.exp = w.maxexp
    quiet(LV_.Lv_up, w)
gs = make_session_dict(player=w)
d = _player_dict(w, gs["inventory"])
opt = d["pending_skill_choices"]
check("_player_dict: Lv11 선택지 2개 + 설명·MP", len(opt) == 1 and opt[0]["lv"] == 11
      and [o["name"] for o in opt[0]["options"]] == ["피의 격노", "방패치기"]
      and all(o["desc"] for o in opt[0]["options"]) and opt[0]["options"][1]["mp"] == 9
      and opt[0]["options"][0]["hp_cost"] == 15 and opt[0]["options"][1]["hp_cost"] == 0, opt)
client, uid, store = inject_test_session(gs)
r = client.post("/api/skill/choose", json={"lv": 11, "skill": "강타2"})
check("API: 짝 아닌 스킬 400", r.status_code == 400)
r = client.post("/api/skill/choose", json={"lv": "x", "skill": "방패치기"})
check("API: lv 숫자 아님 400", r.status_code == 400)
gs["battle"] = object()
r = client.post("/api/skill/choose", json={"lv": 11, "skill": "방패치기"})
check("API: 전투 중 400", r.status_code == 400)
gs["battle"] = None
r = client.post("/api/skill/choose", json={"lv": 11, "skill": "방패치기"})
j = r.get_json()
check("API: 확정 → skills에 방패치기, 대기 비움", r.status_code == 200 and "방패치기" in j["player"]["skills"]
      and j["player"]["pending_skill_choices"] == [], j)
r = client.post("/api/skill/choose", json={"lv": 11, "skill": "피의 격노"})
check("API: 같은 레벨 재선택 400", r.status_code == 400)

# ═══════════════════════════════════════════════════════════
print("\n[5] AI — reactive 사용 규칙")
rr = PlayerAI("reactive")
w = ent(job="전사", skills=["불굴", "강타1"]); w.hp = 300
check("reactive 전사: HP 30%면 불굴", rr.decide(w, dummy()).detail == "불굴")
w = ent(job="전사", skills=["피의 맹세", "강타1"])
check("reactive 전사: 단일 타격뿐이면 맹세는 손해(지불 200 > 회수 80) → 강타1", rr.decide(w, dummy()).detail == "강타1")
w = ent(job="전사", skills=["피의 맹세", "광풍 베기"]); w.hp = 600
check("reactive 전사: 광역 3대상이면 이득(회수 240 > 지불 120) → 피의 맹세",
      rr.decide(w, dummy(), enemy_count=3).detail == "피의 맹세")
check("_lifesteal_buff_profit 부호", PlayerAI._lifesteal_buff_profit(w, dummy(), "피의 맹세", 3) > 0
      > PlayerAI._lifesteal_buff_profit(ent(skills=["피의 맹세"]), dummy(), "피의 맹세", 1))
mg = ent(job="마법사", skills=["서리 결계", "파이어볼1"])
check("reactive 마법사: 서리 결계 선행", rr.decide(mg, dummy()).detail == "서리 결계")
rg = ent(job="도적", skills=["약점 표식", "급소찌르기1"])
check("reactive 도적: 표식 없으면 약점 표식", rr.decide(rg, dummy()).detail == "약점 표식")
check("reactive 도적: 대상이 더 빠르면 표식을 쓰지 않음", rr.decide(rg, dummy(spd=80)).detail == "급소찌르기1")
sh = dummy(); sh.is_summoned = True
check("reactive 도적: 소환체에는 표식을 쓰지 않음", rr.decide(rg, sh).detail == "급소찌르기1")
tt = dummy(); execute_skill("약점 표식", ent(job="도적", skills=["약점 표식"]), tt)
check("reactive 도적: 이미 표식이면 공격", rr.decide(rg, tt).detail == "급소찌르기1")
bb = PlayerAI("balanced")
check("balanced는 버프형 신규 스킬(피의 맹세·서리 결계·약점 표식)을 쓰지 않는다",
      bb.decide(ent(job="전사", skills=["피의 맹세", "강타1"]), dummy()).detail == "강타1"
      and bb.decide(ent(job="마법사", skills=["서리 결계", "파이어볼1"]), dummy()).detail == "파이어볼1"
      and bb.decide(ent(job="도적", skills=["약점 표식", "급소찌르기1"]), dummy()).detail == "급소찌르기1")

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
