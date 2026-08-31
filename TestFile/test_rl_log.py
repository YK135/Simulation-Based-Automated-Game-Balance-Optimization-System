# -*- coding: utf-8 -*-
"""
test_rl_log.py — RL/행동 로그 (state, action, result) 회귀 테스트

검증:
  · RL 로그가 BattleLog 테이블에 저장됨 (예전엔 data/RL_LOG/ 로컬 파일)
  · DB 유저 없어도(게스트) 로그 저장
  · 실드 데미지가 로그에 분리 기록 (shield_damage / hp_damage)
  · 아이템 사용 후 available_actions 갱신 (전투 인벤토리 기준)
  · 버프/디버프 턴 값이 실제 turns를 기록 (0 고정 버그 회귀 방지)
  · 개인정보(email/nickname) 미저장

실행: python3 test_rl_log.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import sys

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, Buff
from app.Shared import _save_rl_log
from DB import get_session as db_session
from DB.Models import BattleLog

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def make_player(job="전사", items=None):
    return EntitySnapshot(
        name="RL테스트", hp=1000, maxhp=1000, mp=200, maxmp=200,
        stg=50, arm=20, sparm=10, sp=10, luc=10, lv=10, spd=99.0,
        job=job, learned_skills=["슬래시1"],
        items=list(items or []))


def make_enemy(hp=100000, shield=0.0):
    e = EntitySnapshot(
        name="더미", hp=hp, maxhp=hp, mp=0, maxmp=0,
        stg=30, arm=0, sparm=0, sp=0, luc=0, lv=1, spd=1.0,
        enemy_type="고블린")
    e.shield = shield
    return e


def main():
    from DB import init_db
    init_db()   # player_states/battle_logs 등 신규 테이블이 없으면 생성

    print("=" * 52)
    print(" RL 행동 로그 회귀 테스트")
    print("=" * 52)

    print("\n[1] 기본 기록 구조")
    bs = BattleSession(make_player(), enemies=[make_enemy()],
                       items=["HP_S_potion"])   # 전투 인벤은 별도 인자
    bs.battle_meta = {"node_type": "battle", "chapter": 1, "battle_type": "1v1",
                      "source": "human"}
    bs.step("attack")
    check("step 1회 → 레코드 1개", len(bs.rl_log) == 1)
    rec = bs.rl_log[0]
    check("state/action/result 3키", set(rec.keys()) == {"state", "action", "result"},
          str(rec.keys()))
    st, ac, rs = rec["state"], rec["action"], rec["result"]
    check("state: 플레이어 HP/MP/ATB/실드/버프/디버프/상태이상",
          all(k in st["player"] for k in
              ("hp", "mp", "atb", "shield", "buffs", "debuffs", "status")))
    check("state: 적 HP/ATB/실드/원소큐",
          all(k in st["enemies"][0] for k in
              ("hp", "atb", "shield", "element_queue")))
    check("action: actor/type/detail/target/available/source",
          all(k in ac for k in
              ("actor", "type", "detail", "target_idx", "available", "source")))
    check("result: damage/hp_damage/shield_damage/killed/winner 스키마",
          all(k in rs for k in
              ("damage", "hp_damage", "shield_damage", "killed", "winner")))

    print("\n[2] 실드 데미지 분리 기록")
    e = make_enemy(shield=100000)   # 거대 실드 — 전부 실드로 흡수
    bs2 = BattleSession(make_player(), enemies=[e])
    bs2.step("attack")
    rs2 = bs2.rl_log[0]["result"]
    check("실드 흡수 시 shield_damage > 0", rs2["shield_damage"] > 0,
          str(rs2))
    check("hp_damage == 0 (전부 흡수)", rs2["hp_damage"] == 0)
    check("damage == hp + shield 합", abs(rs2["damage"] - (rs2["hp_damage"] + rs2["shield_damage"])) < 0.11)

    print("\n[3] 아이템 사용 후 available_actions 갱신")
    p = make_player()
    bs3 = BattleSession(p, enemies=[make_enemy()], items=["HP_S_potion"])
    bs3.player.hp = 500   # 회복 여지
    r1_avail = None
    bs3.step("item:HP_S_potion")
    rec3 = bs3.rl_log[0]
    check("사용 전 available에 item:HP_S_potion 포함",
          "item:HP_S_potion" in rec3["action"]["available"],
          str(rec3["action"]["available"]))
    bs3.step("attack")
    rec4 = bs3.rl_log[1]
    check("사용 후 available에서 사라짐 (전투 인벤 기준)",
          "item:HP_S_potion" not in rec4["action"]["available"],
          str(rec4["action"]["available"]))

    print("\n[4] 버프 턴 값 (turns 실기록 — 0 고정 회귀 방지)")
    p4 = make_player()
    bs4 = BattleSession(p4, enemies=[make_enemy()])
    bs4.player.buffs.append(Buff(name="힘의 축복", stat="stg", amount=0.2, turns=3))
    bs4.step("attack")
    buffs = bs4.rl_log[0]["state"]["player"]["buffs"]
    check("버프 turns=3 기록", buffs and buffs[0]["turns"] == 3, str(buffs))

    print("\n[5] DB 저장 (BattleLog 테이블) — DB 유저 없이(게스트)")
    with db_session() as db:
        before_max_id = db.query(BattleLog.id).order_by(BattleLog.id.desc()).first()
        before_max_id = before_max_id[0] if before_max_id else 0

    gs = {"player": p4, "db_user_id": None}   # DB 유저 없음
    _save_rl_log(gs, bs4)

    with db_session() as db:
        new_rows = db.query(BattleLog).filter(BattleLog.id > before_max_id).all()
        check("게스트도 row 생성", len(new_rows) == 1, str(new_rows))
        if new_rows:
            row = new_rows[0]
            check("게스트는 user_id=None", row.user_id is None, str(row.user_id))
            meta = json.loads(row.meta_json)
            check("meta: job/level/enemy_count/enemies",
                  all(k in meta for k in ("job", "level", "enemy_count", "enemies")),
                  str(meta))
            records = json.loads(row.records_json)
            check("records_json이 rl_log 레코드 그대로", len(records) == len(bs4.rl_log),
                  f"{len(records)} vs {len(bs4.rl_log)}")
            blob = row.meta_json + row.records_json
            check("개인정보 미저장 (email/nickname 없음)",
                  "email" not in blob and "nickname" not in blob)

    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()