# -*- coding: utf-8 -*-
"""
test_relics.py — 유물 4종 + 3종 택 1 회귀 테스트 (Combat Content Brief 7장 · 11-1 2차 7번)

검증 대상:
  · 깨진 모래시계 — 전투 종료(승리·도주·패배) 시 잔여 ATB ×2 이월, BattleEngine의 final_player_atb도 동일
  · 탐욕의 인장 — 보상 골드 +40%(서버가 곱함), 포션 슬롯 6 → 5 (Inventory.potion_capacity, 직렬화 왕복)
  · 서리 사냥꾼의 각인 — ice 부착 대상 물리 피해 +15%(파쇄 배율 앞), 파쇄 시 ATB +5 (세션·엔진), 마법엔 없음
  · 사제의 유해 — HP 0에서 전투당 1회 20% 부활 (직접 피해·지속 피해·엔진), 두 번째 죽음은 그대로 패배
  · 제시 규칙 — 아직 없는 유물 중 최대 3개, 전부 가지면 제시 없음. 엘리트·보스 승리 응답에만 relic_offer
  · /api/relic/choose — 티켓 검증(없는 티켓·제시되지 않은 id 거부·티켓 유지), 골드 환전, 중복 지급 거부
  · 상점 — 아직 없는 유물만 진열(type relic · 가격 200), 구매 시 골드 차감·플레이어 유물 추가·재진열에서 사라짐,
    골드 부족·이미 보유 거부, price 조작 무시
  · Player.to_dict/from_dict · 세션 스냅샷의 pending_relic_offer 왕복, _player_dict의 relics 메타
DB는 Flask test_client 경로에서 init_db()만 거친다(실제 행 저장 없음 — 기존 라우트 테스트와 동일).

실행: python3 TestFile/test_relics.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, StatusEffect, Action, BattleEngine, Buff
from ai.battle import Damage as D
from ai.battle.Relics import (
    RELIC_IDS, RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS,
    relic_atb_carry, relic_try_revive, frost_mark_mult, relic_gold_mult, relic_potion_slot_penalty,
)
from game.Relics import (
    RELIC_META, relic_choices, available_relics, shop_relic_items, relic_list_public,
    RELIC_GOLD_CONVERT, RELIC_SHOP_PRICE,
)
from game.Player_Class import Player, create_player_by_job
from game.Inventory import Inventory, SLOT_LIMITS
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
    def __enter__(self):
        self.ru, self.ri = D.uniform, D.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
        return self
    def __exit__(self, *a):
        D.uniform, D.randint = self.ru, self.ri


def ent(name="용사", hp=1000, stg=100, job="전사", skills=None, spd=50.0, relics=None, et="", **kw):
    return EntitySnapshot(name=name, hp=hp, maxhp=hp, mp=200, maxmp=200, stg=stg, arm=0, sparm=0, sp=100,
                          luc=0, lv=10, spd=spd, job=job, learned_skills=list(skills or []), items=[],
                          relics=list(relics or []), enemy_type=et, **kw)


def dummy(hp=5000, spd=1.0, stg=20, **kw):
    return ent("허수아비", hp=hp, stg=stg, job="", spd=spd, et="슬라임", **kw)


# ═══════════════════════════════════════════════════════════
print("\n[1] 메타·제시 규칙")
check("유물 4종 정의, 전부 공용", set(RELIC_META) == set(RELIC_IDS) == {RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS}
      and all(not m["job"] for m in RELIC_META.values()))
random.seed(1)
c = relic_choices([], "전사")
check("없을 때 3개 제시(중복 없음)", len(c) == 3 and len(set(c)) == 3 and all(x in RELIC_IDS for x in c), c)
check("3개 보유 → 남은 1개만", relic_choices([RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK]) == [RELIC_PRIEST_REMAINS])
check("전부 보유 → 제시 없음", relic_choices(list(RELIC_IDS)) == [])
check("상점 진열: 아직 없는 것만, type relic, 가격 200", [x["id"] for x in shop_relic_items([RELIC_GREED_SEAL])] ==
      [r for r in RELIC_IDS if r != RELIC_GREED_SEAL] and all(x["type"] == "relic" and x["price"] == RELIC_SHOP_PRICE
                                                             for x in shop_relic_items([])))
check("상점 행: effect는 짧은 문구(≤20자), desc는 전체 설명", all(len(x["effect"]) <= 20 and x["desc"] == RELIC_META[x["id"]]["desc"]
      for x in shop_relic_items([])), [x["effect"] for x in shop_relic_items([])])
check("relic_list_public: id·name·icon·desc", relic_list_public([RELIC_HOURGLASS])[0]["name"] == "깨진 모래시계"
      and set(relic_list_public([RELIC_HOURGLASS])[0]) >= {"id", "name", "icon", "desc"})

# ═══════════════════════════════════════════════════════════
print("\n[2] 깨진 모래시계 — ATB 이월 ×2")
check("relic_atb_carry: 없으면 그대로, 있으면 2배", relic_atb_carry(ent(), 37.0) == 37.0
      and relic_atb_carry(ent(relics=[RELIC_HOURGLASS]), 37.0) == 74.0)
p = ent(relics=[RELIC_HOURGLASS], stg=10000)
s = BattleSession(p, enemies=[dummy(hp=10)])
s.player_atb = 40.0
with deterministic():
    s.step("attack")                       # 처치 → 승리 (행동 뒤 SPD 50 누적 전에 종료 판정)
check("승리 시 atb_remainder = 잔여 40 × 2 = 80", s.done and s.winner == "player" and s.player.atb_remainder == 80.0,
      (s.done, s.player.atb_remainder))
p2 = ent(relics=[RELIC_HOURGLASS])
s = BattleSession(p2, enemies=[dummy()])
s.player_atb = 10.0
_old = __import__("ai.battle_session.Player_Actions", fromlist=["_random"])._random
import ai.battle_session.Player_Actions as PA
PA._random = lambda: 0.0
try:
    r = s.step("escape")
finally:
    PA._random = _old
check("도주 성공 시에도 ×2 (20)", s.winner == "escaped" and s.player.atb_remainder == 20.0, (s.winner, s.player.atb_remainder))
eng = BattleEngine(ent(relics=[RELIC_HOURGLASS], stg=10000), dummy(hp=10))
eng.atb.player_pt = 33.0
res = eng._make_result("player")
check("BattleEngine.final_player_atb도 ×2 (66)", res.final_player_atb == 66.0, res.final_player_atb)
check("유물 없는 플레이어는 그대로", BattleEngine(ent(), dummy())._make_result("player").final_player_atb == 0.0)

# ═══════════════════════════════════════════════════════════
print("\n[3] 탐욕의 인장 — 골드 +40% · 포션 슬롯 −1")
check("relic_gold_mult 1.4 / 1.0", relic_gold_mult([RELIC_GREED_SEAL]) == 1.4 and relic_gold_mult([]) == 1.0)
check("relic_potion_slot_penalty 1 / 0", relic_potion_slot_penalty([RELIC_GREED_SEAL]) == 1 and relic_potion_slot_penalty([]) == 0)
inv = Inventory.new()
check("기본 포션 용량 6", inv.potion_capacity() == SLOT_LIMITS["potion"] == 6)
inv.potion_penalty = 1
for _ in range(5):
    inv.add("HP_S_potion")
r6 = inv.add("HP_S_potion")
check("페널티 1: 5개까지, 6번째는 potion_full", r6["ok"] is False and r6["reason"] == "potion_full" and inv.potion_capacity() == 5)
check("to_response_dict potion_capacity 5", inv.to_response_dict()["potion_capacity"] == 5)
inv2 = Inventory.from_dict(inv.to_dict())
check("직렬화 왕복에 페널티 유지", inv2.potion_penalty == 1 and inv2.potion_capacity() == 5)
check("특수 슬롯은 무관(3)", inv.to_response_dict()["special_capacity"] == 3)

# ═══════════════════════════════════════════════════════════
print("\n[4] 서리 사냥꾼의 각인 — ice 대상 물리 +15% · 파쇄 ATB +5")
w = ent(relics=[RELIC_FROST_MARK]); t = dummy(); t.element_queue = ["ice"]
check("frost_mark_mult: ice 대상 1.15, 원소 없으면 1.0, 유물 없으면 1.0", frost_mark_mult(w, t) == 1.15
      and frost_mark_mult(w, dummy()) == 1.0 and frost_mark_mult(ent(), t) == 1.0)
s = BattleSession(w, enemies=[dummy(hp=100000)]); s.enemies[0].element_queue = ["ice"]
s.player_atb = 0.0
with deterministic():
    r = s.step("attack")
# 200 × 1.15 = 229.99…(부동소수 절삭 229) → 파쇄 +20%: 229 + 45 = 274
check("일반공격: 200 → 각인 229 → 파쇄 274", s.logs[-1].damage_dealt == 274, s.logs[-1].damage_dealt)
check("메시지: 각인 +15% · 파쇄 ATB +5", any("각인 — 물리 피해 +15%" in m for m in r["messages"])
      and any("파쇄! ATB +5" in m for m in r["messages"]), r["messages"])
check("행동 뒤 ATB = SPD 50 + 5 = 55 (엔티티 보너스가 세션 ATB로 옮겨짐)", s.player_atb == 55.0 and s.player._pending_atb_bonus == 0,
      s.player_atb)
s = BattleSession(ent(relics=[RELIC_FROST_MARK]), enemies=[dummy(hp=100000)])   # ice 없음
with deterministic():
    s.step("attack")
check("ice 없으면 보정 없음(200)", s.logs[-1].damage_dealt == 200)
m = ent(job="마법사", relics=[RELIC_FROST_MARK], skills=["파이어볼1"])
s = BattleSession(m, enemies=[dummy(hp=100000)]); s.enemies[0].element_queue = ["ice"]
with deterministic():
    s.step("skill:파이어볼1")
check("마법(융해)에는 각인 없음: 300 + 융해(1.5+0.05) = 465", s.logs[-1].damage_dealt == 465, s.logs[-1].damage_dealt)
# ★ 튜너 엔진의 일반공격 경로는 apply_element_and_react를 거치지 않는다(기존 Digital Twin 공백 —
#   실전은 일반공격도 파쇄가 난다). 그래서 엔진은 스킬 경로(강타1 → execute_skill)로 각인을 확인한다.
eng = BattleEngine(ent(relics=[RELIC_FROST_MARK], skills=["강타1"]), dummy(hp=100000))
eng.enemy.element_queue = ["ice"]; eng.atb.player_pt = 0.0
with deterministic():
    eng._execute_action(Action("skill", "강타1"), eng.player, eng.enemy, "player")
# 310 × 1.15 = 356.5 → 356 → 파쇄 +71 = 427
check("BattleEngine(스킬 경로): 강타1 310 → 각인 356 → 파쇄 427 + ATB +5", eng.logs[-1].damage_dealt == 427 and eng.atb.player_pt == 5.0,
      (eng.logs[-1].damage_dealt, eng.atb.player_pt))

# ═══════════════════════════════════════════════════════════
print("\n[5] 사제의 유해 — 전투당 1회 부활")
e = ent(relics=[RELIC_PRIEST_REMAINS]); e.hp = 0
check("relic_try_revive: 0 → 200(20%), 표시", relic_try_revive(e) == 200.0 and e.hp == 200.0 and e.relic_revive_used)
e.hp = 0
check("두 번째는 발동 안 함", relic_try_revive(e) == 0.0 and e.hp == 0)
check("유물 없으면 발동 안 함", relic_try_revive(ent()) == 0.0)
p = ent(relics=[RELIC_PRIEST_REMAINS], spd=1.0); p.hp = 10
s = BattleSession(p, enemies=[dummy(spd=20, stg=500)])
s._enemy_ai = lambda *a, **k: Action("attack", "attack")
with deterministic():
    r = s.step("auto")
check("적 공격으로 죽으면 20%로 부활, 전투 계속", not s.done and s.player.hp == 200.0
      and any("사제의 유해" in m for m in r["messages"]), (s.done, s.player.hp, r["messages"]))
s.action_queue = [("enemy", 0)]
with deterministic():
    r = s.step("auto")
check("같은 전투의 두 번째 죽음은 패배", s.done and s.winner == "enemy", (s.done, s.winner))
p = ent(relics=[RELIC_PRIEST_REMAINS]); p.hp = 5
p.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈", stacks=3))
s = BattleSession(p, enemies=[dummy()])
with deterministic():
    r = s.step("attack")                   # 플레이어 차례 시작 틱(출혈 90)으로 사망 → 부활 → 행동 진행
check("지속 피해 사망도 부활 뒤 행동을 이어간다", not s.done and s.player.hp > 0 and s.logs[-1].action == "attack", (s.done, s.player.hp))
eng = BattleEngine(ent(relics=[RELIC_PRIEST_REMAINS], spd=1.0), dummy(spd=200, stg=5000))
eng.player.hp = 10
res = eng.run(lambda p_, e_, **k: Action("attack", "attack"), lambda a, d, **k: Action("attack", "attack"))
check("BattleEngine: 한 번 부활한 뒤 두 번째 죽음에 패배(전투 종료)", res.winner == "enemy" and eng.player.relic_revive_used)

# ═══════════════════════════════════════════════════════════
print("\n[6] Player 직렬화 · _player_dict · 스냅샷")
pl = create_player_by_job("테스터", "전사")
check("새 플레이어 relics []", pl.relics == [])
pl.relics.append(RELIC_GREED_SEAL)
pl2 = Player.from_dict(pl.to_dict())
check("to_dict/from_dict 왕복", pl2.relics == [RELIC_GREED_SEAL])
check("옛 저장(relics 없음)도 복구", Player.from_dict({k: v for k, v in pl.to_dict().items() if k != "relics"}).relics == [])
from app.Shared import _player_dict, _snapshot_dict, _gs_from_snapshot, _player_to_snap, _grant_relic
gs = make_session_dict(player=pl, gold=100)
d = _player_dict(pl, gs["inventory"])
check("_player_dict.relics 메타", d["relics"][0]["id"] == RELIC_GREED_SEAL and d["relics"][0]["name"] == "탐욕의 인장")
check("_player_to_snap.relics", _player_to_snap(pl, gs["inventory"]).relics == [RELIC_GREED_SEAL])
gs["pending_relic_offer"] = {"ticket_id": "abc", "choices": [RELIC_HOURGLASS]}
snap = _snapshot_dict(gs)
gs2 = _gs_from_snapshot("test-uid", snap)
check("스냅샷 왕복: pending_relic_offer · 인벤토리 포션 페널티(탐욕의 인장)",
      gs2["pending_relic_offer"] == gs["pending_relic_offer"] and gs2["inventory"].potion_penalty == 1)
gs3 = make_session_dict()
check("_grant_relic: 지급 + 인벤토리 동기화, 중복 거부", _grant_relic(gs3, RELIC_GREED_SEAL) and gs3["inventory"].potion_penalty == 1
      and not _grant_relic(gs3, RELIC_GREED_SEAL))

# ═══════════════════════════════════════════════════════════
print("\n[7] /api/relic/choose")
gs = make_session_dict(gold=100)
client, uid, store = inject_test_session(gs)
from app.Shared import _register_relic_offer
tid = _register_relic_offer(gs, [RELIC_HOURGLASS, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS])
r = client.post("/api/relic/choose", json={"ticket_id": "nope", "relic_id": RELIC_HOURGLASS})
check("없는 티켓 400", r.status_code == 400 and gs["pending_relic_offer"] is not None)
r = client.post("/api/relic/choose", json={"ticket_id": tid, "relic_id": RELIC_GREED_SEAL})
check("제시되지 않은 id 400 + 티켓 유지", r.status_code == 400 and gs["pending_relic_offer"]["ticket_id"] == tid)
r = client.post("/api/relic/choose", json={"ticket_id": tid, "relic_id": RELIC_FROST_MARK})
j = r.get_json()
check("선택 성공: 유물 추가, player.relics 메타, 티켓 소진", r.status_code == 200 and j["ok"] and gs["player"].relics == [RELIC_FROST_MARK]
      and j["player"]["relics"][0]["id"] == RELIC_FROST_MARK and gs["pending_relic_offer"] is None, j)
r = client.post("/api/relic/choose", json={"ticket_id": tid, "relic_id": RELIC_FROST_MARK})
check("같은 티켓 재사용 400", r.status_code == 400)
tid2 = _register_relic_offer(gs, [RELIC_HOURGLASS])
r = client.post("/api/relic/choose", json={"ticket_id": tid2, "relic_id": "gold"})
check("골드 환전 +60, 유물 그대로", r.status_code == 200 and gs["gold"] == 100 + RELIC_GOLD_CONVERT and gs["player"].relics == [RELIC_FROST_MARK])

# ═══════════════════════════════════════════════════════════
print("\n[8] 상점 — 유물 판매")
gs = make_session_dict(gold=1000)
client, uid, store = inject_test_session(gs)
from app.Map import _shop_items_for
items = _shop_items_for(gs["player"])
relic_rows = [it for it in items if it.get("type") == "relic"]
check("진열: 4종 relic, 가격 200, 아이콘 포함", len(relic_rows) == 4 and all(it["price"] == RELIC_SHOP_PRICE and it.get("icon") for it in relic_rows))
r = client.post("/api/shop/buy", json={"item_id": RELIC_GREED_SEAL, "price": 0})
j = r.get_json()
check("구매: 골드 1000 → 800(요청 price 무시), 유물 추가, 재진열에서 제외",
      r.status_code == 200 and j["ok"] and gs["gold"] == 800 and gs["player"].relics == [RELIC_GREED_SEAL]
      and all(it["id"] != RELIC_GREED_SEAL for it in j["shop_items"]), j)
check("구매 후 포션 슬롯 5", gs["inventory"].potion_capacity() == 5 and j["player"]["inventory"]["potion_capacity"] == 5)
r = client.post("/api/shop/buy", json={"item_id": RELIC_GREED_SEAL, "price": 200})
check("이미 가진 유물은 판매 목록에 없음 → 400", r.status_code == 400)
gs["gold"] = 50
r = client.post("/api/shop/buy", json={"item_id": RELIC_HOURGLASS, "price": 0})
check("골드 부족 400", r.status_code == 400 and gs["player"].relics == [RELIC_GREED_SEAL])

# ═══════════════════════════════════════════════════════════
print("\n[9] 전투 종료 — 엘리트·보스 승리에만 relic_offer, 탐욕의 인장 골드")
from app.Battle import _finish_battle
def finish(gs, node_type, is_boss=False, gold_relic=False):
    if gold_relic:
        gs["player"].relics = [RELIC_GREED_SEAL]
    gs["battle_node_type"] = node_type
    p = _player_to_snap(gs["player"], gs["inventory"])
    en = dummy(hp=10)
    bs = BattleSession(p, enemy=en, items=[], is_boss=is_boss)
    bs.enemies[0].hp = 0
    bs.done, bs.winner = True, "player"
    result = {"player_hp": bs.player.hp, "player_mp": bs.player.mp, "messages": [], "done": True, "winner": "player"}
    random.seed(3)
    _finish_battle(gs, bs, result, "player")
    return result
gs = make_session_dict(gold=0); gs["hook"] = type("H", (), {"check_level_up": lambda self: None, "after_battle": lambda self, r: None})()
res = finish(gs, "battle")
check("일반 노드 승리: relic_offer 없음", "relic_offer" not in res)
res = finish(gs, "elite")
check("엘리트 승리: relic_offer(티켓·3개·환전 60) + 세션 티켓", "relic_offer" in res and len(res["relic_offer"]["choices"]) == 3
      and res["relic_offer"]["gold_alt"] == RELIC_GOLD_CONVERT and gs["pending_relic_offer"]["ticket_id"] == res["relic_offer"]["ticket_id"],
      res.get("relic_offer"))
gs["player"].relics = list(RELIC_IDS)
res = finish(gs, "elite")
check("전부 보유하면 엘리트 승리에도 제시 없음", "relic_offer" not in res)
gs["player"].relics = []
gs["gold"] = 0
res = finish(gs, "battle", gold_relic=True)
check("탐욕의 인장: 골드 +40% 메시지와 실제 지급 일치", res["gold_gained"] == gs["gold"] and any("탐욕의 인장" in m for m in res["messages"])
      and res["gold_gained"] > 0, (res["gold_gained"], gs["gold"], res["messages"]))

print(f"\n결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
