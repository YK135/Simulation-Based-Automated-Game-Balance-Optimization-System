# -*- coding: utf-8 -*-
"""
test_hit_ledger.py — 피격 장부(hit_ledger) · reaction_count · action_fx 검증
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_hit_ledger.py

hits는 원래 step 전후의 "순변화량"이라 같은 step의 피해와 회복이 서로
지워졌다(출혈 16 + 흡혈 23.4 → heal 7 하나). 이제 피해·회복이 적용되는
지점에서 장부에 한 줄씩 남기고, 「대상 × 이벤트 종류」별로 합친다.

  1. 같은 step의 피해와 회복이 따로 나온다 (상쇄 버그 수정)
  2. 실드 흡수 + HP 피해가 damage 하나로 합쳐진다
  3. 연타 반응은 reaction_count에 횟수로 남는다
  4. action_fx — 버프(대상 0 → 자신), AoE(시전 시점 생존 적 전원),
     이번 공격으로 죽은 적도 대상에 포함, 적 행동, 상태 조회는 None,
     사제가 다른 적에게 건 회복·축복·부활 의식의 대상
  5. step 밖에서는 장부가 꺼져 있다 (시뮬 경로 비용 0)
  6. ★ 실제 전투를 무작위로 돌렸을 때 장부 잔차가 항상 0
     — 잔차는 "기록 훅 없이 HP/실드가 바뀐 곳"이 있다는 뜻이다
"""
import os
import sys
import io
import contextlib
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.Player_Class import create_player_by_job                       # noqa: E402
from game.Lv import LV_                                                  # noqa: E402
from game import Enemy_Class as EC                                       # noqa: E402
from ai.Battlesession import BattleSession                               # noqa: E402
from ai.Auto_AI import PlayerAI                                          # noqa: E402
from ai.battle import EntitySnapshot                                     # noqa: E402
from ai.battle.Entity import StatusEffect                                # noqa: E402
from ai.Simulator import _unit_to_snap                                   # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def player(job="전사", lv=1):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("테스터", job)
        for _ in range(lv - 1):
            p.exp = 10 ** 9
            LV_.Lv_up(p)
    return p


def session(job="전사", lv=1, enemies=None, items=None):
    p = player(job, lv)
    units = enemies or [EC.Make_Goblin(lv, "중")]
    # ★ 실전과 같은 변환 순서를 그대로 쓴다:
    #   hook.get_enemy()가 _unit_to_snap(maxhp = hp)으로 만든 스냅샷을
    #   app/Battle.py._start_battle이 다시 from_enemy()에 넣어 원소 슬라임의
    #   고유 원소를 복구한다. from_enemy(Unit)만 쓰면 _apply_grade가 hp만 곱하고
    #   maxhp를 안 맞춘 값이 그대로 와서, 상급 고레벨이면 hp가 maxhp의 2배를
    #   넘는 — 실전에는 없는 — 개체가 된다.
    snaps = [EntitySnapshot.from_enemy(_unit_to_snap(u)) for u in units]
    with contextlib.redirect_stdout(io.StringIO()):
        s = BattleSession(EntitySnapshot.from_player(p), enemies=snaps,
                          items=list(items or []), enemy_origins=units,
                          is_boss=False, player_original=p)
    return s


def of(hits, target, kind, slot=None):
    return [h for h in hits if h["target"] == target and h["kind"] == kind
            and (slot is None or h["slot"] == slot)]


# ═══════════════════════════════════════════════════════════
print("\n[1] 같은 step의 피해와 회복이 서로 지우지 않는다 (출혈 + 흡혈)")
s = session(enemies=[EC.Make_Bat(10, "상")])
bat = s.enemies[0]
bat.elite_leader = True
bat.hp = bat.maxhp * 0.5                        # 회복 여유
bat.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
before = s._hp_snapshot()
msgs = []
bat.tick_status_effects()                       # 출혈 틱 (피해, via=dot)
s._elite_bat_lifesteal(bat, 200, msgs)          # 흡혈 (회복)
hits = s._hits_from_snapshot(before)
dmg, heal = of(hits, "enemy", "damage", 0), of(hits, "enemy", "heal", 0)
check("damage 이벤트가 남는다", len(dmg) == 1, f"hits={hits}")
check("heal 이벤트도 따로 남는다", len(heal) == 1, f"hits={hits}")
if dmg:
    check("출혈 피해는 via=dot, element=bleed",
          dmg[0]["via"] == "dot" and dmg[0]["element"] == "bleed", f"{dmg[0]}")
check("장부 잔차 0", s._last_hit_residual == 0, f"residual={s._last_hit_residual}")
s._close_hit_ledgers()

# ═══════════════════════════════════════════════════════════
print("\n[2] 실드 흡수 + HP 피해 → damage 하나")
s = session()
s.player.shield = 30.0
before = s._hp_snapshot()
s._apply_dmg_shielded(s.player, 50, [])
dmg = of(s._hits_from_snapshot(before), "player", "damage")
check("damage 1개, amount = 흡수 30 + HP 20",
      len(dmg) == 1 and dmg[0]["amount"] == 50, f"{dmg}")
check("장부 잔차 0", s._last_hit_residual == 0)
s._close_hit_ledgers()

# ═══════════════════════════════════════════════════════════
print("\n[3] 연타 반응은 reaction_count로 센다 (연속공격2 → 빙결 슬라임)")
random.seed(3)
found = None
for trial in range(40):
    s = session("전사", 13, enemies=[EC.Make_IceSlime(13, "중")])
    s.player.luc = 0
    s.player.mp = s.player.maxmp
    s.enemies[0].luc = 0                        # 회피 제거 → 전부 명중
    if s._peek_next_actor()[0] != "player":
        continue
    out = s.step("skill:연속공격2")
    dmg = of(out["hits"], "enemy", "damage", 0)
    if dmg:
        found = dmg[0]
        break
check("연속공격2 피해 이벤트 확보", found is not None)
if found:
    n = found["reaction_count"].get("shatter", 0)
    check("파쇄 횟수가 2회 이상으로 집계된다 (고유 ice가 즉시 복구되므로 타마다 파쇄)",
          n >= 2, f"reaction_count={found['reaction_count']}")
    check("대표 반응 라벨 = shatter", found["reaction"] == "shatter")
    check("숫자는 여전히 대상당 1개", len(of(out["hits"], "enemy", "damage", 0)) == 1)

# ═══════════════════════════════════════════════════════════
print("\n[4] action_fx — 시전 이펙트 데이터")


def player_turn(s):
    """적이 선공이면 플레이어 차례가 올 때까지 적 행동을 넘긴다."""
    for _ in range(10):
        if s.done or s._peek_next_actor()[0] == "player":
            return
        s.step("auto")


s = session("전사", 5)
player_turn(s)
s.player.mp = s.player.maxmp
out = s.step("skill:강화1")
fx = out.get("action_fx")
check("버프 — hits는 비어도 action_fx는 있다",
      fx is not None and not of(out["hits"], "enemy", "damage"), f"fx={fx}")
if fx:
    check("버프 — scope=self, 대상=플레이어 자신",
          fx["scope"] == "self" and fx["targets"] == [{"side": "player", "slot": -1}], f"{fx}")
    check("버프 — stype=buff, name=강화1", fx["stype"] == "buff" and fx["name"] == "강화1", f"{fx}")

# AoE: 적 3마리, 그중 하나는 이번 공격으로 죽는다
s = session("도적", 8, enemies=[EC.Make_Goblin(8, "하") for _ in range(3)])
player_turn(s)
s.player.mp = s.player.maxmp
s.enemies[1].hp = 1                              # 이번 난사로 확실히 죽을 개체
for e in s.enemies:
    e.luc = 0
out = s.step("skill:난사1")
fx = out.get("action_fx") or {}
slots = sorted(t["slot"] for t in fx.get("targets", []) if t["side"] == "enemy")
check("AoE — scope=aoe", fx.get("scope") == "aoe", f"{fx}")
check("AoE — 시전 시점 생존 적 3마리가 전부 대상 (죽은 1번 포함)",
      slots == [0, 1, 2], f"slots={slots} alive_after={[e.hp > 0 for e in s.enemies]}")
check("AoE — 1번은 실제로 이번 공격에 죽었다", s.enemies[1].hp <= 0)

# 단일 공격으로 대상 처치
s = session("전사", 5, enemies=[EC.Make_Goblin(5, "하"), EC.Make_Goblin(5, "하")])
player_turn(s)
s.enemies[1].hp = 1
s.enemies[1].luc = 0
out = s.step("attack:1")
fx = out.get("action_fx") or {}
check("단일 공격 — 겨눈 1번 슬롯이 대상 (처치돼도 빠지지 않음)",
      {"side": "enemy", "slot": 1} in fx.get("targets", []), f"{fx}")
check("단일 공격 — kind=attack, scope=single",
      fx.get("kind") == "attack" and fx.get("scope") == "single", f"{fx}")

# 적 행동
s = session("전사", 3)
for _ in range(10):
    if s._peek_next_actor()[0] == "enemy":
        break
    s.step("attack")
if not s.done and s._peek_next_actor()[0] == "enemy":
    idx = s._peek_next_actor()[1]
    out = s.step("auto")
    fx = out.get("action_fx") or {}
    check("적 행동 — actor=enemy, actor_slot=행동한 슬롯",
          fx.get("actor") == "enemy" and fx.get("actor_slot") == idx, f"{fx}")
    if fx.get("scope") != "self":
        check("적 행동 — 대상에 플레이어", {"side": "player", "slot": -1} in fx.get("targets", []), f"{fx}")

out = s.step("status")
check("상태 조회 — action_fx는 None", out.get("action_fx") is None, f"{out.get('action_fx')}")

# ═══════════════════════════════════════════════════════════
print("\n[4b] action_fx — 사제가 '다른 적'에게 건 회복·축복·부활 의식")
import ai.battle_session.Enemy_Actions as EA                            # noqa: E402


def priest_fx(setup, force_roll=None):
    """[고블린, 사제] 전투에서 사제 행동 1회의 action_fx를 돌려준다."""
    s = session("전사", 12, enemies=[EC.Make_Goblin(12, "중"), EC.Make_Priest(12, "중")])
    ally, priest = s.enemies
    priest.mp = priest.maxmp
    setup(s, ally, priest)
    before = s._hp_snapshot()
    before["actor"], before["actor_idx"] = "enemy", 1       # 사제가 행동하는 step으로 고정
    orig = EA._random
    if force_roll is not None:
        EA._random = lambda: force_roll
    try:
        s._priest_action(priest, [])
    finally:
        EA._random = orig
    fx = s._action_fx(before)
    s._close_hit_ledgers()
    return fx, s


fx, _s = priest_fx(lambda s, a, p: setattr(a, "hp", a.maxhp * 0.3))
check("사제힐 — 대상은 치료받은 고블린(슬롯 0), 사제 자신이 아님",
      fx and fx["name"] == "사제힐" and fx["targets"] == [{"side": "enemy", "slot": 0}], f"{fx}")
check("사제힐 — 남에게 건 회복이므로 scope=single", fx and fx["scope"] == "single", f"{fx}")

fx, _s = priest_fx(lambda s, a, p: None, force_roll=0.0)
check("사제축복 — HP 변화가 없어도 대상(슬롯 0)이 잡힌다",
      fx and fx["name"] == "사제축복" and fx["targets"] == [{"side": "enemy", "slot": 0}], f"{fx}")


def ritual(s, ally, priest):
    priest.elite_leader = True
    ally.hp = 0


fx, s_r = priest_fx(ritual)
check("부활 의식 시작 — TurnLog가 없어도 action_fx가 나온다",
      fx and fx["name"] == "부활 의식 준비" and fx["stype"] == "ritual", f"{fx}")
check("부활 의식 시작 — 대상은 되살릴 고블린(슬롯 0)",
      fx and fx["targets"] == [{"side": "enemy", "slot": 0}], f"{fx}")
before = s_r._hp_snapshot()
before["actor"], before["actor_idx"] = "enemy", 1
s_r._priest_action(s_r.enemies[1], [])
fx = s_r._action_fx(before)
hits = s_r._hits_from_snapshot(before)
s_r._close_hit_ledgers()
check("부활 의식 완성 — name=부활 의식 완성, 대상 슬롯 0",
      fx and fx["name"] == "부활 의식 완성" and fx["targets"] == [{"side": "enemy", "slot": 0}], f"{fx}")
check("부활 의식 완성 — 되살아난 HP는 heal 이벤트로 보인다",
      len(of(hits, "enemy", "heal", 0)) == 1, f"{hits}")

# ═══════════════════════════════════════════════════════════
print("\n[5] step 밖에서는 장부가 꺼져 있다")
s = session()
check("세션 생성 직후 None", s.player.hit_ledger is None and s.enemies[0].hit_ledger is None)
s.step("attack")
check("step 종료 후 다시 None",
      s.player.hit_ledger is None and all(e.hit_ledger is None for e in s.enemies))
from ai.battle.Damage import _apply_damage_with_shield          # noqa: E402
snap = EntitySnapshot.from_enemy(EC.Make_Goblin(1, "중"))
_apply_damage_with_shield(snap, 5)
check("시뮬 경로(장부 None)에서는 아무것도 기록하지 않는다", snap.hit_ledger is None)

# ═══════════════════════════════════════════════════════════
print("\n[6] 무작위 실전 전투에서 장부 잔차가 항상 0 (기록 훅 누락 검사)")
MAKERS = [EC.Make_Goblin, EC.Make_Bat, EC.Make_Slime, EC.Make_Golem, EC.Make_Ghost,
          EC.Make_Assassin, EC.Make_Priest, EC.Make_FireSlime, EC.Make_IceSlime,
          EC.Make_LightningSlime]
ITEMS = ["HP_S_potion", "HP_M_potion", "MP_S_potion", "bomb", "web_bomb",
         "fire_vial", "ice_vial", "lightning_crystal", "focus_drug", "haste_drug"]
ELITE_TYPES = {"고블린", "박쥐", "슬라임", "골렘", "암살자", "사제", "화염 슬라임", "빙결 슬라임", "번개 슬라임"}

random.seed(20260917)
ai = PlayerAI()
steps = battles = 0
leaks = []
for job in ("전사", "마법사", "도적", "탱커"):
    for lv in (3, 9, 15, 22):
        for _ in range(6):
            n = random.choice((1, 2, 3))
            units = [random.choice(MAKERS)(lv, random.choice("하중상")) for _ in range(n)]
            s = session(job, lv, enemies=units,
                        items=[random.choice(ITEMS) for _ in range(6)])
            lead = s.enemies[0]
            if getattr(lead, "enemy_type", "") in ELITE_TYPES:
                lead.elite_leader = True
            battles += 1
            for _ in range(160):
                if s.done:
                    break
                na, _i = s._peek_next_actor()
                if na == "player":
                    tgt = s._current_target() or s.enemy
                    alive = sum(1 for e in s.enemies if e.hp > 0)
                    a = ai.decide(s.player, tgt, enemy_count=alive)
                    act = {"attack": "attack", "skill": f"skill:{a.detail}",
                           "item": f"item:{a.detail}"}.get(a.action_type, "attack")
                else:
                    act = "auto"
                with contextlib.redirect_stdout(io.StringIO()):
                    out = s.step(act)
                steps += 1
                if s._last_hit_residual:
                    leaks.append((job, lv, act, [u.name for u in units], out.get("messages", [])[:6]))
print(f"     전투 {battles}회 · step {steps}회")
check("잔차가 난 step 0건", not leaks, f"{len(leaks)}건, 첫 사례: {leaks[:2]}")

print(f"\n{'─' * 46}\n총 {PASS + FAIL}건 — 성공 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
