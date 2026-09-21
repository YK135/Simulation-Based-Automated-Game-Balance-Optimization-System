# -*- coding: utf-8 -*-
"""
test_final_boss.py — 최종 보스 4페이즈 회귀 테스트 (Combat Content Brief 4장 · 11-1 2차 8번)

검증 대상:
  · 페이즈 경계 100~70 / 70~40 / 40~15 / 15~0, 내려가지 않음, 전투 시작 시 페이즈 1(화염 부착)
  · 1 원소 순환 — 3회 행동마다 fire→ice→lightning, 같은 원소 공격 −40%, 반응으로 벗겨지면 즉시 다음 원소
  · 2 소환 — 그림자 2마리(보스 maxHP 8%·스탯 40%·보상 없음), 생존 중 보스 피해 −25%, 전멸 시 경감 해제 +
    2회 무방비 + 5회 뒤 재소환(죽은 칸 재사용 — 적 3명 한도), 보스가 죽으면 그림자도 정리
  · 3 잠식 — MP 8% 흡수(절반 회복), MP 0이면 HP 4%(죽지 않음), 손아귀 예고 → 다음 행동 2.5배 + ATB 0,
    예고 보장(플레이어가 행동하기 전엔 일반공격)
  · 4 종언 — 진입 시 방어 −40%·회복 −50%, 플레이어 행동 3회 뒤 maxHP 75%(실드로 버팀), 다음은 2회 뒤 즉사,
    사제의 유해는 즉사에도 발동
  · 배지, 보스 스탯 불변, 중간 보스 경로 영향 없음
DB를 쓰지 않는다.

실행: python3 TestFile/test_final_boss.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, Action, Buff, execute_skill
from ai.battle import Damage as D
from ai.battle import Skills as SK
from ai.battle.BossKit import (
    is_finalboss, is_shadow, finalboss_phase_for, finalboss_sync_phase, finalboss_decide,
    finalboss_cycle_tick, finalboss_element_resist, FINALBOSS_ELEMENTS, SHADOW_TYPE, GRASP_SKILL, GRASP_DETAIL,
)
from game.Enemy_Class import Make_FinalBoss

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
        self.o = (D.uniform, D.randint, SK.random, SK.randint)
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        SK.random = lambda: 1.0
        SK.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint, SK.random, SK.randint = self.o


def boss():
    return EntitySnapshot.from_enemy(Make_FinalBoss(25))


def player(job="", hp=5000, mp=300, spd=30.0, stg=100, sp=100, skills=None, **kw):
    return EntitySnapshot(name="용사", hp=hp, maxhp=hp, mp=mp, maxmp=mp, stg=stg, arm=40, sparm=40, sp=sp,
                          luc=0, lv=25, spd=spd, job=job, learned_skills=list(skills or []), items=[], **kw)


def session(p=None):
    return BattleSession(p or player(), enemy=boss(), is_boss=True)


def set_hp(ent, ratio):
    ent.hp = ent.maxhp * ratio


def boss_turn(s, idx=0, stub=None):
    """보스(또는 idx 적) 차례를 강제로 한 번 돌린다."""
    s.action_queue = [("enemy", idx)]
    if stub is not None:
        old = s._enemy_ai
        s._enemy_ai = lambda *a, **k: stub
    try:
        with deterministic():
            return s.step("auto")
    finally:
        if stub is not None:
            s._enemy_ai = old


def player_turn(s, action="attack"):
    s.action_queue = [("player", -1)]
    with deterministic():
        return s.step(action)


# ═══════════════════════════════════════════════════════════
print("\n[0] 식별·스탯 불변")
b = boss()
check("enemy_type 최종 보스", is_finalboss(b) and b.enemy_type == "최종 보스")
# 6차 조정(2026-09-21): 실제 도착 레벨(중앙값 Lv20)에 맞춰 hp·stg·arm·sparm·sp를 ×0.72.
# spd·luc·mp는 그대로 — game/Enemy_Class.Make_FinalBoss의 주석에 근거가 있다.
check("스탯 (HP 2484 / STG 46 / ARM 37 / SPARM 42 / SPD 34 / 디버프저항 0.25)",
      (b.maxhp, b.stg, b.arm, b.sparm, b.spd) == (2484, 46, 37, 42, 34)
      and abs(getattr(b, "debuff_resist", 0) - 0.25) < 1e-9)
check("페이즈 경계", [finalboss_phase_for(x) for x in (1.0, 0.71, 0.70, 0.41, 0.40, 0.16, 0.15, 0.0)] == [1, 1, 2, 2, 3, 3, 4, 4])

# ═══════════════════════════════════════════════════════════
print("\n[1] 페이즈 1 — 원소 순환")
s = session()
B = s.enemies[0]
check("전투 시작: 페이즈 1 + 화염 부착", B.boss_phase == 1 and B.element_queue == ["fire"])
st = s._state()["enemies"][0]["pattern"]
check("배지: 원소 순환 1/4 + '화염 → 다음 빙결'", st[0]["label"] == "원소 순환" and st[0]["max"] == 4
      and any(x["label"] == "화염 → 다음 빙결" for x in st), st)
atk = Action("attack", "attack")
seq = []
for _ in range(6):
    r = boss_turn(s, stub=None)
    seq.append(B.element_queue[-1] if B.element_queue else "")
check("3회 행동마다 순환: fire fire ice ice ice lightning", seq == ["fire", "fire", "ice", "ice", "ice", "lightning"], seq)
check("전환 메시지", any("번개" in m and "바뀐다" in m for m in r["messages"]), r["messages"])
check("같은 원소 저항: lightning 대상에 lightning 0.6, fire 1.0", finalboss_element_resist(B, "lightning") == 0.6
      and finalboss_element_resist(B, "fire") == 1.0)
# 반응으로 벗겨지면 즉시 다음 원소
m = player(job="", skills=["파이어볼1"])
s = session(m); B = s.enemies[0]
B.element_queue = ["lightning"]; B.boss_element_idx = 2
r = player_turn(s, "skill:파이어볼1")          # lightning + fire = 과부하 → 큐 비움 → 다음(fire) 즉시
check("과부하로 벗겨짐 → 곧바로 다음 원소(fire) 부착 + 메시지", B.element_queue == ["fire"] and B.boss_element_idx == 0
      and any("곧바로" in x for x in r["messages"]), (B.element_queue, r["messages"]))
s = session(player(job="", skills=["파이어볼1"])); B = s.enemies[0]
hp0 = B.hp
r = player_turn(s, "skill:파이어볼1")          # fire 대상에 fire → −40%
check("같은 원소(fire→fire) 피해 −40% + 메시지", any("흘려낸다" in x for x in r["messages"]), r["messages"])

# ═══════════════════════════════════════════════════════════
print("\n[2] 페이즈 2 — 소환·경감·무방비·재소환")
s = session(player(stg=100)); B = s.enemies[0]
set_hp(B, 0.72)
r = player_turn(s)                               # 70% 아래로 → 페이즈 2 + 소환
check("페이즈 2 진입 + 그림자 2마리, 순환 원소 해제", B.boss_phase == 2 and len(s.enemies) == 3
      and all(is_shadow(e) for e in s.enemies[1:]) and B.element_queue == [], (B.boss_phase, [e.name for e in s.enemies]))
sh = s.enemies[1]
check("그림자: HP 198.7(8%), STG 18.4(40%), MP 0, 보상 없음, ATB 칸 추가", abs(sh.maxhp - 2484 * 0.08) < 1e-6 and abs(sh.stg - 46 * 0.40) < 1e-6
      and sh.maxmp == 0 and sh.reward_eligible is False and len(s.enemy_atbs) == 3 and len(s._origins) == 3)
check("보스 경감 0.25 + 배지", B.boss_guard == 0.25 and any("그림자 경감" in x["label"] for x in s._state()["enemies"][0]["pattern"]))
hp0 = B.hp
player_turn(s, "attack:0")
check("경감 중 보스 피해 −25% (200 × 200/151 … × 0.75)", B.hp < hp0)
dmg_guarded = hp0 - B.hp
B.boss_guard = 0.0; hp1 = B.hp
player_turn(s, "attack:0")
dmg_open = hp1 - B.hp
B.boss_guard = 0.25
check("경감 없는 피해 대비 75%", abs(dmg_guarded - int(dmg_open * 0.75)) <= 1, (dmg_guarded, dmg_open))
# 그림자 처치
for i in (1, 2):
    s.enemies[i].hp = 1
player_turn(s, "attack:1")
check("한 마리 남으면 경감 유지", B.boss_guard == 0.25)
r = player_turn(s, "attack:2")
check("전멸 → 경감 해제 + 무방비 2 + 재소환 대기 5 + 메시지", B.boss_guard == 0.0 and B.boss_stunned == 2
      and B.boss_summon_cd == 5 and any("무방비" in x for x in r["messages"]), (B.boss_guard, B.boss_stunned, r["messages"]))
r1 = boss_turn(s); r2 = boss_turn(s)
check("무방비 2회: 보스 행동 없음(watch boss_stunned)", s.logs[-1].action_detail == "boss_stunned"
      and B.boss_stunned == 0 and any("무방비" in x for x in r1["messages"]))
for _ in range(4):
    boss_turn(s)
check("4회 뒤 아직 재소환 전(cd 1)", B.boss_summon_cd == 1 and all(e.hp <= 0 for e in s.enemies[1:]))
r = boss_turn(s)
check("5회째 재소환 — 죽은 칸 재사용(적 3명 유지), 경감 복구", len(s.enemies) == 3 and all(e.hp > 0 for e in s.enemies[1:])
      and B.boss_guard == 0.25 and any("불러냈다" in x for x in r["messages"]), r["messages"])
# 보스 사망 → 그림자 정리
B.hp = 1
r = player_turn(s, "attack:0")
check("보스가 쓰러지면 그림자도 사라지고 승리", s.done and s.winner == "player" and all(e.hp <= 0 for e in s.enemies)
      and any("흩어졌다" in x for x in r["messages"]), (s.done, s.winner, r["messages"]))

# ═══════════════════════════════════════════════════════════
print("\n[3] 페이즈 3 — 잠식·손아귀")
s = session(player(mp=300)); B = s.enemies[0]
set_hp(B, 0.39); s._check_boss_phase(B, [])
for e in s.enemies[1:]:
    e.hp = 0
s._check_boss_phase(B, []); B.boss_stunned = 0
check("페이즈 3 (소환은 2에서만 1회)", B.boss_phase == 3)
boss_hp = B.hp
r = boss_turn(s)
check("MP 8%(24) 흡수 → 보스 HP +12 + 메시지", s.player.mp == 276 and abs(B.hp - (boss_hp + 12)) < 1e-6
      and any("MP 24" in x for x in r["messages"]), (s.player.mp, B.hp - boss_hp, r["messages"]))
s.player.mp = 0
hp_p = s.player.hp
B.boss_cycle = 0
r = boss_turn(s, stub=None)
check("MP 0 → HP 4%(200) 흡수", any("HP 200" in x for x in r["messages"]), r["messages"])
# 손아귀 주기: 3회 정규 행동째 예고
s = session(player(mp=0, hp=100000)); B = s.enemies[0]
set_hp(B, 0.39); s._check_boss_phase(B, [])
for e in s.enemies[1:]:
    e.hp = 0
s._check_boss_phase(B, []); B.boss_stunned = 0
acts = []
for _ in range(3):
    boss_turn(s)
    acts.append(s.logs[-1].action_detail)
check("3번째 행동이 예고(grasp_telegraph)", acts[2] == GRASP_DETAIL and B.boss_telegraph_at >= 0, acts)
check("배지: 손아귀 armed", any(x["label"] == "심연의 손아귀" and x["state"] == "armed" for x in s._state()["enemies"][0]["pattern"]))
boss_turn(s)
check("플레이어가 행동하기 전엔 일반공격으로 보류", s.logs[-1].action == "attack" and B.boss_telegraph_at >= 0)
player_turn(s)
s.player_atb = 80.0
hp_p = s.player.hp
r = boss_turn(s)
check("다음 보스 행동에 손아귀 + ATB 0 + 메시지", s.logs[-1].action_detail == GRASP_SKILL and s.player_atb <= 34.0
      and any("ATB가 0" in x for x in r["messages"]), (s.logs[-1].action_detail, s.player_atb, r["messages"]))
grasp = s.logs[-1].damage_dealt                 # 같은 행동의 HP 흡수(MP 0 → 4%)는 따로 — 손아귀 피해만 본다
check("손아귀 피해 = STG 46 × 2.5 기준 (ARM 40: 46×200/140×2.5 = 164)", grasp == 164, grasp)
check("같은 행동에서 흡수 4000도 따로 들어감", hp_p - s.player.hp == 164 + 4000, hp_p - s.player.hp)

# ═══════════════════════════════════════════════════════════
print("\n[4] 페이즈 4 — 종언")
p = player(hp=10000, mp=0)
s = session(p); B = s.enemies[0]
arm0, sparm0 = B.arm, B.sparm
set_hp(B, 0.14)
r = player_turn(s)
check("페이즈 4 진입: 방어 −40%, 플레이어 회복 ×0.5, 카운트 = 행동 수 + 3", B.boss_phase == 4 and abs(B.arm - arm0 * 0.6) < 1e-6
      and abs(B.sparm - sparm0 * 0.6) < 1e-6 and s.player.heal_taken_mult == 0.5
      and B.boss_doom_at == s._player_action_count + 3 - 1, (B.arm, s.player.heal_taken_mult, B.boss_doom_at, s._player_action_count))
check("진입 메시지", any("종언" in x for x in r["messages"]))
# 이 시나리오는 「종언」 카운트만 본다 — 아래 스크립트된 플레이어 턴이 보스를 먼저
# 죽이면 안 된다. 6차 조정으로 보스 HP가 3450 → 2484가 되면서 14% 잔여(348)가
# 실제로 킬 사정권에 들어왔다. 공격력을 죽여 카운트만 흐르게 한다.
s.player.stg = s.player.sp = 1
check("회복 반감 heal_value(1000) = 500", s.player.heal_value(1000) == 500.0)
s.player.hp = 5000
s.player.items = ["HP_M_potion"]; s.items = ["HP_M_potion"]
r = player_turn(s, "item:HP_M_potion")           # max(300, 10000×20%) = 2000 → 반감 1000
check("포션 회복도 반감 (5000 → 6000)", s.player.hp == 6000, s.player.hp)
s.player.hp = 9000
badge = [x for x in s._state()["enemies"][0]["pattern"] if x["kind"] == "telegraph" and x["label"].startswith("종언")]
check("배지: 종언 2/3 (포션까지 2회 행동 소진)", badge and badge[0]["cur"] == 2 and badge[0]["max"] == 3, badge)
player_turn(s)
hp_before = s.player.hp
s.player.shield = 1000
r = boss_turn(s)
check("카운트 끝 → 75%(7500) 고정 피해, 실드 1000 흡수 → HP −6500", s.logs[-1].action_detail == "종언"
      and hp_before - s.player.hp == 6500 and B.boss_doom_count == 1, (hp_before - s.player.hp, r["messages"]))
check("재시작 안내 + 카운트 2", any("재시작" in x for x in r["messages"]) and B.boss_doom_at == s._player_action_count + 2)
s.player.hp = 9999
boss_turn(s)
check("카운트 전에는 일반공격", s.logs[-1].action == "attack")
player_turn(s); player_turn(s)
r = boss_turn(s)
check("두 번째 종언 = 즉사 → 패배", s.done and s.winner == "enemy" and s.player.hp == 0, (s.done, s.winner))
# 사제의 유해는 즉사도 막는다
p = player(hp=10000, mp=0, relics=["priest_remains"])
s = session(p); B = s.enemies[0]
set_hp(B, 0.14); player_turn(s)
B.boss_doom_count = 1; B.boss_doom_at = s._player_action_count
r = boss_turn(s)
check("사제의 유해: 즉사 → 20% 부활, 전투 계속", not s.done and s.player.hp == 2000 and s.player.relic_revive_used, (s.done, s.player.hp))

# ═══════════════════════════════════════════════════════════
print("\n[5] 판단 함수 · 다른 경로 불변")
b = boss(); finalboss_sync_phase(b)
check("sync: 0 → 1, fire", b.boss_phase == 1 and b.element_queue == ["fire"])
b.hp = b.maxhp * 0.1
check("한 번에 여러 구간 → [2,3,4]", finalboss_sync_phase(b, player(), 7) == [2, 3, 4] and b.boss_doom_at == 10)
b.hp = b.maxhp
check("페이즈는 내려가지 않음", finalboss_sync_phase(b) == [] and b.boss_phase == 4)
b = boss(); finalboss_sync_phase(b)
check("페이즈 1 행동: 일반공격/원소탄만", {finalboss_decide(b, 0, rng=lambda: v).action_type for v in (0.1, 0.9)} == {"attack", "skill"}
      and finalboss_decide(b, 0, rng=lambda: 0.9).detail == "파이어볼1")
from game.Enemy_Class import Make_MidBoss
ms = BattleSession(player(), enemy=EntitySnapshot.from_enemy(Make_MidBoss(15)), is_boss=True)
check("중간 보스 세션은 최종 보스 필드를 건드리지 않음", ms.enemies[0].boss_element_idx == 0 and ms.enemies[0].element_queue == []
      and ms.enemies[0].boss_guard == 0.0)

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
