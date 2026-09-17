# -*- coding: utf-8 -*-
"""
test_monster_identity.py — 일반 몬스터 정체성 개편 회귀 테스트 (Combat Content Brief 2장 · 11-1 2차 3번)

검증 대상:
  · 고블린 무리 전술 — 살아있는 고블린 2/3마리 → 각자 STG +8%/+16%(상한), 한 마리가 죽거나(직접 피해·지속 피해)
    달아나면 즉시 다시 셈. 버프 목록이 아니라 pack_bonus 필드(전투 함성·사제축복과 안 겹침). 배지 노출
  · 고블린 겁쟁이 — HP 15% 이하 + 다른 고블린이 이미 죽었을 때만, 전투당 1회, 성공/실패 모두 차례 소비,
    성공하면 fled + hp 0 + reward_eligible False(보상 목록에서 제외), 단독 고블린·엘리트 대장은 안 달아남
  · 박쥐 — 킷에서 파이어볼 제거(날갯소리·약화1), 날갯소리는 피해 없이 플레이어 ATB −12(0 아래로는 안 감),
    일반공격 흡혈 10%(1회 상한 maxHP 5%), 엘리트 흡혈 박쥐는 20%/10% 그대로. 튜너 엔진(BattleEngine)도 같은 규칙
  · 사제 — 일반 사제 약식 소생: 죽은 아군을 maxHP 10%로 즉시(전투당 1회), 달아난 개체는 대상 아님,
    엘리트 부활 의식(2단계·25%)은 그대로. 배지(안 썼을 때만)
  · 다른 몬스터·플레이어의 effective_stg는 불변 (pack_bonus 기본 0)
DB를 쓰지 않는다.

실행: python3 TestFile/test_monster_identity.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, StatusEffect, Action, BattleEngine, get_monster_kit
from ai.battle import Damage as D
from ai.battle.MonsterKit import (
    goblin_pack_bonus, goblin_wants_to_flee, bat_lifesteal_amount,
    GOBLIN_PACK_STG_PER_ALLY, GOBLIN_PACK_STG_CAP, GOBLIN_FLEE_HP_RATIO,
    BAT_WING_SKILL, BAT_WING_ATB_DRAIN, BAT_WING_MP,
    NORMAL_BAT_LIFESTEAL_RATIO, NORMAL_BAT_LIFESTEAL_CAP_RATIO,
    PRIEST_QUICK_REVIVE_HP_RATIO, PRIEST_QUICK_REVIVE_SKILL,
)
from ai.battle.EliteKit import BAT_LIFESTEAL_RATIO, BAT_LIFESTEAL_CAP_RATIO, PRIEST_PHASE_PREPARING
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
    """난수·크리·회피를 끈다 — uniform=1.0, randint는 상한(임계 초과)."""
    def __enter__(self):
        self.ru, self.ri = D.uniform, D.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint = self.ru, self.ri


class force_roll:
    """Enemy_Actions._random(도주 판정)을 고정값으로."""
    def __init__(self, v): self.v = v
    def __enter__(self):
        self.old = EA._random
        EA._random = lambda: self.v
    def __exit__(self, *a):
        EA._random = self.old


class stub_ai:
    """세션의 EnemyAI를 고정 행동으로 바꾼다."""
    def __init__(self, session, action):
        self.s, self.a = session, action
    def __enter__(self):
        self.old = self.s._enemy_ai
        a = self.a
        self.s._enemy_ai = lambda *args, **kw: a
    def __exit__(self, *x):
        self.s._enemy_ai = self.old


def player(spd=50.0, hp=3000, stg=60, arm=20, job="전사"):
    return EntitySnapshot(name="용사", hp=hp, maxhp=hp, mp=100, maxmp=100,
                          stg=stg, arm=arm, sparm=10, sp=10, luc=0, lv=10, spd=spd,
                          job=job, learned_skills=["강타1"], items=[])


def mob(name, et, hp=200, stg=20, spd=10.0, **kw):
    return EntitySnapshot(name=name, hp=hp, maxhp=hp, mp=60, maxmp=60,
                          stg=stg, arm=5, sparm=5, sp=10, luc=0, lv=5, spd=spd,
                          enemy_type=et, **kw)


def session(p, enemies):
    return BattleSession(p, enemies=enemies)


def goblins_of(s):
    return [e for e in s.enemies if e.enemy_type == "고블린"]


# ═══════════════════════════════════════════════════════════
print("\n[1] 무리 전술 — 수치 함수와 effective_stg")
check("0~1마리는 가산 없음", goblin_pack_bonus(0) == 0.0 and goblin_pack_bonus(1) == 0.0)
check("2마리 +8%", abs(goblin_pack_bonus(2) - GOBLIN_PACK_STG_PER_ALLY) < 1e-9)
check("3마리 +16%", abs(goblin_pack_bonus(3) - GOBLIN_PACK_STG_CAP) < 1e-9)
check("4마리도 상한 +16%", abs(goblin_pack_bonus(4) - GOBLIN_PACK_STG_CAP) < 1e-9)
g = mob("고블린", "고블린", stg=100)
check("pack_bonus 기본 0 → effective_stg 불변", g.pack_bonus == 0.0 and g.effective_stg() == 100.0)
g.pack_bonus = 0.16
check("pack_bonus 0.16 → STG 116", abs(g.effective_stg() - 116.0) < 1e-9)
from ai.battle import Buff, Debuff
g.apply_buff(Buff(stat="stg", amount=0.10, turns=2, name="전투 함성"))
check("버프와 가산(전투 함성 +10% + 무리 +16%)", abs(g.effective_stg() - 126.0) < 1e-9,
      f"{g.effective_stg()}")
g.apply_debuff(Debuff(stat="stg", amount=0.20, turns=2, name="저주1"))
check("디버프와도 가산으로 합산 (1 - 0.2 + 0.1 + 0.16)", abs(g.effective_stg() - 106.0) < 1e-9)

# ═══════════════════════════════════════════════════════════
print("\n[2] 무리 전술 — 세션 동기화 (시작 · 직접 피해 사망 · 지속 피해 사망 · 배지)")
s = session(player(), [mob("고블린", "고블린", hp=100), mob("고블린", "고블린", hp=100), mob("고블린", "고블린", hp=100)])
check("전투 시작: 세 마리 전부 +16%", all(abs(x.pack_bonus - 0.16) < 1e-9 for x in goblins_of(s)))
st = s._state()
b = [x for x in st["enemies"][0]["pattern"] if "무리 전술" in x["label"]]
check("배지 '무리 전술 +16%' 3/3", b and b[0]["cur"] == 3 and b[0]["max"] == 3 and "+16%" in b[0]["label"],
      str(st["enemies"][0]["pattern"]))
check("무리가 아닌 슬라임은 pack_bonus 0", mob("슬라임", "슬라임").pack_bonus == 0.0)

s.enemies[0].hp = 1
with deterministic():
    r = s.step("attack:0")           # 플레이어(SPD 50) 선공 — 고블린 0 처치
check("한 마리 처치 → 나머지 두 마리 +8%",
      s.enemies[0].hp <= 0 and all(abs(x.pack_bonus - 0.08) < 1e-9 for x in goblins_of(s)[1:]),
      [x.pack_bonus for x in goblins_of(s)])
check("죽은 고블린은 pack_bonus 0", s.enemies[0].pack_bonus == 0.0)
check("변경 메시지 '무리 전술 … 2마리 … +8%'",
      any("무리 전술" in m and "2마리" in m and "+8%" in m for m in r["messages"]), r["messages"])

# 지속 피해로 죽어도 동기화된다 — 고블린 1을 1 HP + 점화, 고블린 차례에 틱으로 사망
s2 = session(player(spd=1.0), [mob("고블린", "고블린", hp=100, spd=20), mob("고블린", "고블린", hp=100, spd=10)])
s2.enemies[0].hp = 1
s2.enemies[0].apply_status_effect(StatusEffect(effect_type="ignite", turns=2, name="fire"))
na, idx = s2._peek_next_actor()
check("고블린 0이 먼저 움직인다", na == "enemy" and idx == 0, (na, idx))
r = s2.step("auto")
check("점화로 사망 → 남은 고블린 가산 해제 (+ 메시지)",
      s2.enemies[0].hp <= 0 and s2.enemies[1].pack_bonus == 0.0
      and any("흩어졌다" in m for m in r["messages"]), r["messages"])

# 첫 고블린 행동에서 발동 중임을 한 번 알린다
s3 = session(player(spd=1.0), [mob("고블린", "고블린", hp=500, spd=20), mob("고블린", "고블린", hp=500, spd=10)])
with deterministic():
    r1 = s3.step("auto"); r2 = s3.step("auto")
check("첫 고블린 행동에 '무리 전술' 안내 1회", sum("무리 전술" in m for m in r1["messages"]) == 1, r1["messages"])
check("두 번째 고블린 행동에는 반복 안내 없음", not any("무리 전술" in m for m in r2["messages"]), r2["messages"])

# ═══════════════════════════════════════════════════════════
print("\n[3] 겁쟁이 — 조건")
a = mob("고블린", "고블린", hp=100); b2 = mob("고블린", "고블린", hp=100)
a.hp = 10; b2.hp = 0
check("HP 10% + 다른 고블린 사망 → 도주 원함", goblin_wants_to_flee(a, [a, b2]))
a.hp = 16
check("HP 16%면 아직 아님", not goblin_wants_to_flee(a, [a, b2]))
a.hp = 10; b2.hp = 50
check("다른 고블린이 살아 있으면 아님", not goblin_wants_to_flee(a, [a, b2]))
check("단독 고블린은 절대 아님", not goblin_wants_to_flee(a, [a]))
sl = mob("슬라임", "슬라임"); sl.hp = 0
check("죽은 게 슬라임이면 아님(고블린만 센다)", not goblin_wants_to_flee(a, [a, sl]))
b2.hp = 0; a.flee_attempted = True
check("이미 시도했으면 아님", not goblin_wants_to_flee(a, [a, b2]))
a.flee_attempted = False; a.elite_leader = True
check("엘리트 고블린 대장은 안 달아남", not goblin_wants_to_flee(a, [a, b2]))
a.elite_leader = False
fb = mob("고블린", "고블린", hp=100); fb.hp = 0; fb.fled = True
check("다른 고블린이 '달아난' 경우도 사망으로 친다", goblin_wants_to_flee(a, [a, fb]))

# ═══════════════════════════════════════════════════════════
print("\n[4] 겁쟁이 — 세션 (성공 / 실패 / 1회 한정 / 보상 제외 / 승리 판정)")
def coward_session():
    p = player(spd=1.0)
    dead = mob("고블린", "고블린", hp=100, spd=10); dead.hp = 0
    cow = mob("고블린", "고블린", hp=100, spd=20); cow.hp = 10
    other = mob("슬라임", "슬라임", hp=300, spd=5)
    s = session(p, [dead, cow, other])
    return s, s.enemies[1]

s, cow = coward_session()
with force_roll(0.0):                    # 판정 성공
    r = s.step("auto")
check("도주 성공 → fled / hp 0 / 보상 제외 / 시도 표시",
      cow.fled and cow.hp <= 0 and cow.reward_eligible is False and cow.flee_attempted, vars(cow))
check("메시지 '{이름} → 도주! … 달아났다' (프론트 적 행동 분류 형식)",
      any(m.startswith("고블린 → 도주!") and "달아났다" in m for m in r["messages"]), r["messages"])
check("TurnLog escape / goblin_flee", s.logs[-1].action == "escape" and s.logs[-1].action_detail == "goblin_flee"
      and s.logs[-1].escaped)
check("상태 JSON: alive False + fled True", r["enemies"][1]["alive"] is False and r["enemies"][1]["fled"] is True)
check("전투는 계속(슬라임 생존)", not s.done)
check("'처치했다'/'쓰러졌다' 문구는 없다(프론트 사망 분류 회피)",
      not any("처치했다" in m or "쓰러졌다" in m for m in r["messages"]))

from app.Battle import _get_defeated_list
s.enemies[2].hp = 0
lst = _get_defeated_list(s)
check("보상 목록: 달아난 고블린 제외, 죽은 고블린·슬라임 포함",
      cow not in lst and s.enemies[0] in lst and s.enemies[2] in lst, [e.name for e in lst])

s, cow = coward_session()
with force_roll(1.0):                    # 판정 실패
    r = s.step("auto")
check("도주 실패 → 살아 있고 시도만 소진, 메시지 '도주에 실패'",
      not cow.fled and cow.hp > 0 and cow.flee_attempted and any("도주에 실패" in m for m in r["messages"]),
      r["messages"])
check("실패도 차례를 소비 — 그 행동에 공격 로그 없음",
      s.logs[-1].action == "escape_failed" and s.logs[-1].action_detail == "goblin_flee")
# 다음 차례엔 다시 시도하지 않는다 (겁쟁이는 1회)
s.action_queue = [("enemy", 1)]
with force_roll(0.0), stub_ai(s, Action("attack", "attack")), deterministic():
    r = s.step("auto")
check("두 번째 차례엔 도주 없이 일반 행동", not cow.fled and s.logs[-1].action == "attack", s.logs[-1])

# 마지막 남은 적이 달아나면 승리로 끝난다
p = player(spd=1.0)
dead = mob("고블린", "고블린", hp=100, spd=10); dead.hp = 0
cow = mob("고블린", "고블린", hp=100, spd=20); cow.hp = 5
s = session(p, [dead, cow])
with force_roll(0.0):
    r = s.step("auto")
check("마지막 적 도주 → 전투 종료 · 승리", s.done and s.winner == "player", (s.done, s.winner))
check("달아난 개체도 무리 전술 재계산에서 빠진다(둘 다 0)", all(x.pack_bonus == 0.0 for x in goblins_of(s)))

# ═══════════════════════════════════════════════════════════
print("\n[5] 박쥐 — 킷 · 날갯소리 · 흡혈")
k1, k2 = get_monster_kit("박쥐", 1), get_monster_kit("박쥐", 2)
check("챕터1 킷: 파이어볼 없음, 날갯소리+약화1", "파이어볼1" not in k1["skills"] and set(k1["skills"]) == {BAT_WING_SKILL, "약화1"})
check("챕터2 킷: 파이어볼2·미약화1 없음", "파이어볼2" not in k2["skills"] and "미약화1" not in k2["skills"]
      and set(k2["skills"]) == {BAT_WING_SKILL, "약화1"})
check("확률은 그대로(0.70/0.30, 0.65/0.35)",
      (k1["attack_prob"], k1["skill_prob"]) == (0.70, 0.30) and (k2["attack_prob"], k2["skill_prob"]) == (0.65, 0.35))

p = player(spd=1.0)
s = session(p, [mob("박쥐", "박쥐", hp=200, spd=20)]); bat = s.enemies[0]; s.player_atb = 50.0
with stub_ai(s, Action("skill", BAT_WING_SKILL)):
    r = s.step("auto")
# 적 행동이 끝나면 모두 자기 SPD만큼 ATB를 얻으므로(플레이어 SPD 1.0) 50 − 12 + 1
check("날갯소리: 플레이어 ATB 50 → 38 (+행동 후 SPD 1), 피해 0",
      abs(s.player_atb - (50.0 - BAT_WING_ATB_DRAIN + 1.0)) < 1e-9 and p.hp == s.player.hp, s.player_atb)
check("박쥐 MP −6", bat.mp == 60 - BAT_WING_MP, bat.mp)
check("메시지 '박쥐 → 날갯소리! … ATB −12'", any(m.startswith("박쥐 → 날갯소리!") and "ATB −12" in m for m in r["messages"]),
      r["messages"])
check("TurnLog skill/날갯소리 · 피해 0", s.logs[-1].action == "skill" and s.logs[-1].action_detail == BAT_WING_SKILL
      and s.logs[-1].damage_dealt == 0)
s.player_atb = 5.0; s.action_queue = [("enemy", 0)]
with stub_ai(s, Action("skill", BAT_WING_SKILL)):
    r = s.step("auto")
check("ATB는 0 아래로 내려가지 않는다 (0 + 행동 후 SPD 1)", s.player_atb == 1.0
      and any("ATB −5" in m for m in r["messages"]), s.player_atb)

# 흡혈 — 일반공격
p = player(spd=1.0, arm=0)
s = session(p, [mob("박쥐", "박쥐", hp=1000, stg=100, spd=20)]); bat = s.enemies[0]; bat.hp = 500
with stub_ai(s, Action("attack", "attack")), deterministic():
    r = s.step("auto")
dealt = s.logs[-1].damage_dealt
expect = min(dealt * NORMAL_BAT_LIFESTEAL_RATIO, bat.maxhp * NORMAL_BAT_LIFESTEAL_CAP_RATIO)
check("일반 박쥐 흡혈 = 피해의 10% (상한 maxHP 5%)", dealt > 0 and abs((bat.hp - 500) - expect) < 1.0,
      (dealt, bat.hp - 500, expect))
check("흡혈 메시지", any("피해를 흡수해" in m for m in r["messages"]))
check("bat_lifesteal_amount: 상한 적용 (피해 1000 → maxHP 5% = 50)", bat_lifesteal_amount(bat, 1000) == 50.0)
ebat = mob("흡혈 박쥐", "박쥐", hp=1000, elite_leader=True, is_elite=True)
check("엘리트는 20%/상한 10% 그대로", bat_lifesteal_amount(ebat, 100) == 100 * BAT_LIFESTEAL_RATIO
      and bat_lifesteal_amount(ebat, 5000) == 1000 * BAT_LIFESTEAL_CAP_RATIO)
check("피해 0이면 회복 없음", bat_lifesteal_amount(bat, 0) == 0.0)

# 튜너 엔진(1v1)도 같은 규칙
eng = BattleEngine(player(spd=1.0, arm=0), mob("박쥐", "박쥐", hp=1000, stg=100, spd=20))
eng.atb.player_pt = 40.0
eng._execute_action(Action("skill", BAT_WING_SKILL), eng.enemy, eng.player, "enemy")
check("BattleEngine: 날갯소리 → 플레이어 ATB 40 → 28", abs(eng.atb.player_pt - 28.0) < 1e-9, eng.atb.player_pt)
eng.enemy.hp = 500
with deterministic():
    eng._execute_action(Action("attack", "attack"), eng.enemy, eng.player, "enemy")
d2 = eng.logs[-1].damage_dealt
check("BattleEngine: 박쥐 일반공격 흡혈", d2 > 0 and abs((eng.enemy.hp - 500) - min(d2 * 0.10, 50.0)) < 1.0,
      (d2, eng.enemy.hp))

# ═══════════════════════════════════════════════════════════
print("\n[6] 사제 — 약식 소생")
p = player(spd=1.0)
s = session(p, [mob("사제", "사제", hp=200, spd=20), mob("고블린", "고블린", hp=300, spd=5)])
pr, ally = s.enemies; ally.hp = 0
st = s._state()
check("배지: 안 썼을 때 '약식 소생' 1/1 idle",
      any(b["label"] == PRIEST_QUICK_REVIVE_SKILL and b["state"] == "idle" for b in st["enemies"][0]["pattern"]),
      st["enemies"][0]["pattern"])
r = s.step("auto")
check("죽은 아군을 maxHP 10%로 즉시 소생", abs(ally.hp - 300 * PRIEST_QUICK_REVIVE_HP_RATIO) < 1e-9, ally.hp)
check("메시지 '사제 → 약식 소생! … 되살아났다'",
      any(m.startswith("사제 → 약식 소생!") and "되살아났다" in m for m in r["messages"]), r["messages"])
check("TurnLog skill/약식 소생, 회복은 음수 피해", s.logs[-1].action_detail == PRIEST_QUICK_REVIVE_SKILL
      and s.logs[-1].damage_dealt == -30)
check("전투당 1회 표시", pr.elite_pattern_used is True)
check("배지 사라짐", not any(b["label"] == PRIEST_QUICK_REVIVE_SKILL for b in s._state()["enemies"][0]["pattern"]))
check("되살아난 개체는 보상 대상 유지(재처치해도 보상은 종료 시 1회 계산)", ally.reward_eligible is True)
check("action_fx 대상은 되살린 슬롯", r.get("action_fx") and any(t.get("slot") == 1 for t in r["action_fx"].get("targets", [])),
      r.get("action_fx"))

ally.hp = 0; s.action_queue = [("enemy", 0)]
with stub_ai(s, Action("attack", "attack")), deterministic():
    r = s.step("auto")
check("두 번째 죽음은 되살리지 않는다(1회 소진)", ally.hp <= 0 and s.logs[-1].action_detail != PRIEST_QUICK_REVIVE_SKILL,
      s.logs[-1])

# 달아난 개체는 소생 대상이 아니다
p = player(spd=1.0)
s = session(p, [mob("사제", "사제", hp=200, spd=20), mob("고블린", "고블린", hp=300, spd=5)])
pr, gone = s.enemies; gone.hp = 0; gone.fled = True
r = s.step("auto")
check("달아난 고블린은 되살리지 않음(소생 미사용)", gone.hp <= 0 and pr.elite_pattern_used is False, r["messages"])

# 되살아난 고블린은 무리 전술에 다시 센다
p = player(spd=1.0)
s = session(p, [mob("사제", "사제", hp=200, spd=20),
                mob("고블린", "고블린", hp=300, spd=5), mob("고블린", "고블린", hp=300, spd=5)])
pr, g1, g2 = s.enemies; g2.hp = 0
s._sync_goblin_pack()      # 시작 동기화는 __init__에서 했으니 죽은 상태를 반영해 다시
check("소생 전: 고블린 1마리라 가산 0", g1.pack_bonus == 0.0)
r = s.step("auto")
check("소생 후: 두 마리 +8%", abs(g1.pack_bonus - 0.08) < 1e-9 and abs(g2.pack_bonus - 0.08) < 1e-9
      and any("무리 전술" in m for m in r["messages"]), (g1.pack_bonus, g2.pack_bonus))

# 엘리트 사제는 여전히 2단계 의식
p = player(spd=1.0)
s = session(p, [mob("타락한 고위 사제", "사제", hp=200, spd=20, elite_leader=True, is_elite=True),
                mob("박쥐", "박쥐", hp=100, spd=5)])
epr, dead2 = s.enemies; dead2.hp = 0
r = s.step("auto")
check("엘리트: 첫 행동은 준비(phase 1), 아직 안 살아남", epr.elite_phase == PRIEST_PHASE_PREPARING and dead2.hp <= 0
      and not epr.elite_pattern_used)
s.action_queue = [("enemy", 0)]
r = s.step("auto")
check("엘리트: 두 번째 행동에 25%로 부활", abs(dead2.hp - 25.0) < 1e-9 and epr.elite_pattern_used, dead2.hp)

# ═══════════════════════════════════════════════════════════
print("\n[7] 불변 확인")
check("고블린 킷은 그대로(강타1)", get_monster_kit("고블린", 1)["skills"] == ["강타1"])
pl = player()
check("플레이어 effective_stg 불변 (pack_bonus 0)", pl.effective_stg() == 60.0)
check("GOBLIN_FLEE_HP_RATIO 0.15", GOBLIN_FLEE_HP_RATIO == 0.15)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
