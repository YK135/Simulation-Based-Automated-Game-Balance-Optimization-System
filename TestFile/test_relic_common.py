# -*- coding: utf-8 -*-
"""
test_relic_common.py — 유물 확장 1단계(공용 8종) + 탱커 잠금 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_relic_common.py

브리프 7장 「유물 확장」의 공용 추가 4종과, 그 범위를 정한 탱커 비활성화를 고정한다.

  1) 거울 파편 — 디버프·상태이상 지속이 거는 쪽/받는 쪽 각각 1턴 짧아지고, 최소 1턴은 남는다
  2) 예언서   — 예고 배지가 한 행동 먼저 armed가 된다 (표시 전용 — 적 행동은 불변)
  3) 전리품 자루 — 포션 슬롯 +1, 탐욕의 인장과 함께 가지면 정확히 상쇄
  4) 여행자의 지도 — 상점 "아이템"만 −20%, 유물 가격은 그대로
  5) 유물 풀이 공용 8종이고 제시·상점이 전부 그 풀에서 나온다
  6) 탱커는 /api/new_game이 거부한다 (버튼만 잠그면 요청을 직접 만들 수 있다)
"""
import sys, os, io, contextlib, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

PASS = FAIL = 0
_buf = io.StringIO()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}  {detail}")


def _ent(relics=None):
    from ai.battle import EntitySnapshot
    return EntitySnapshot(
        name="E", hp=100, maxhp=100, mp=50, maxmp=50,
        stg=10, arm=10, sparm=10, sp=10, luc=10, lv=5, spd=10,
        relics=list(relics or []))


# ─────────────────────────────────────────────
def test_mirror_shard():
    print("\n[1] 거울 파편 — 디버프 지속 ±1턴")
    from ai.battle import Debuff, StatusEffect
    from ai.battle.Relics import RELIC_MIRROR_SHARD

    plain, holder = _ent(), _ent([RELIC_MIRROR_SHARD])
    plain.apply_debuff(Debuff(stat="stg", amount=0.2, turns=3, name="약화"))
    check("유물 없음 → 3턴 그대로", plain.debuffs[0].turns == 3, f"{plain.debuffs[0].turns}")

    holder.apply_debuff(Debuff(stat="stg", amount=0.2, turns=3, name="약화"))
    check("받는 쪽이 가짐 → 2턴", holder.debuffs[0].turns == 2, f"{holder.debuffs[0].turns}")

    tgt = _ent()
    tgt.apply_debuff(Debuff(stat="spd", amount=0.2, turns=3, name="둔화"), caster=_ent([RELIC_MIRROR_SHARD]))
    check("거는 쪽이 가짐 → 2턴 (대가)", tgt.debuffs[0].turns == 2, f"{tgt.debuffs[0].turns}")

    both = _ent([RELIC_MIRROR_SHARD])
    both.apply_debuff(Debuff(stat="arm", amount=0.2, turns=3, name="미약화"), caster=_ent([RELIC_MIRROR_SHARD]))
    check("양쪽 다 가짐 → 1턴", both.debuffs[0].turns == 1, f"{both.debuffs[0].turns}")

    floor = _ent([RELIC_MIRROR_SHARD])
    floor.apply_debuff(Debuff(stat="stg", amount=0.2, turns=1, name="한턴"), caster=_ent([RELIC_MIRROR_SHARD]))
    check("1턴짜리는 그대로 (최소 1턴)", floor.debuffs[0].turns == 1, f"{floor.debuffs[0].turns}")

    # 상태이상도 같은 규칙 — 도적 출혈은 "내가 거는" 쪽이라 대가가 된다
    bleed_tgt = _ent()
    eff = bleed_tgt.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"),
                                        caster=_ent([RELIC_MIRROR_SHARD]))
    check("출혈 3턴 → 2턴 (거는 쪽 대가)", eff.turns == 2, f"{eff.turns}")

    burn_me = _ent([RELIC_MIRROR_SHARD])
    eff2 = burn_me.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="fire"))
    check("점화 3턴 → 2턴 (받는 쪽 이득)", eff2.turns == 2, f"{eff2.turns}")


def test_prophecy_badge_lead():
    print("\n[2] 예언서 — 예고 배지를 한 행동 먼저")
    from ai.battle import EntitySnapshot
    from ai.battle.EliteKit import BAT_SCREAM_INTERVAL, FIRE_SLIME_STACK_THRESHOLD
    from ai.battle_session.State import StateMixin
    from game.Enemy_Class import Make_Bat, Make_FireSlime
    from ai.battle.Relics import relic_telegraph_lead, RELIC_PROPHECY_BOOK

    with contextlib.redirect_stdout(_buf):
        bat = EntitySnapshot.from_enemy(Make_Bat(5, "중"))
    bat.elite_leader = True
    bat.elite_phase = 0
    bat.elite_pattern_turn = BAT_SCREAM_INTERVAL - 1      # 다음 행동이 예고 턴

    def state_of(en, lead, kind):
        for b in StateMixin._pattern_badges(en, 0, lead):
            if b["kind"] == kind:
                return b["state"]
        return None

    check("유물 없음 → 아직 charging", state_of(bat, 0, "telegraph") == "charging")
    check("예언서 → 한 행동 먼저 armed", state_of(bat, 1, "telegraph") == "armed")

    with contextlib.redirect_stdout(_buf):
        fs = EntitySnapshot.from_enemy(Make_FireSlime(5, "중"))
    fs.elite_leader = True
    fs.elite_pattern_turn = FIRE_SLIME_STACK_THRESHOLD - 2
    check("스택 게이지도 한 칸 먼저 armed",
          state_of(fs, 0, "stack") == "charging" and state_of(fs, 1, "stack") == "armed")

    check("lead 값은 유물에서만 나온다",
          relic_telegraph_lead([]) == 0 and relic_telegraph_lead([RELIC_PROPHECY_BOOK]) == 1)


def test_potion_slots():
    print("\n[3] 전리품 자루 · 탐욕의 인장 — 포션 슬롯")
    from game.Inventory import Inventory, SLOT_LIMITS
    from ai.battle.Relics import (relic_potion_slot_penalty, RELIC_GREED_SEAL, RELIC_LOOT_SACK)

    base = SLOT_LIMITS["potion"]

    def cap(relics):
        inv = Inventory()
        inv.potion_penalty = relic_potion_slot_penalty(relics)
        return inv.potion_capacity()

    check(f"유물 없음 → {base}칸", cap([]) == base, f"{cap([])}")
    check(f"탐욕의 인장 → {base - 1}칸", cap([RELIC_GREED_SEAL]) == base - 1, f"{cap([RELIC_GREED_SEAL])}")
    check(f"전리품 자루 → {base + 1}칸", cap([RELIC_LOOT_SACK]) == base + 1, f"{cap([RELIC_LOOT_SACK])}")
    check("둘 다 → 정확히 상쇄", cap([RELIC_GREED_SEAL, RELIC_LOOT_SACK]) == base,
          f"{cap([RELIC_GREED_SEAL, RELIC_LOOT_SACK])}")

    # 실제로 6개까지 들어가는지 (용량 계산만 맞고 add가 막으면 의미 없다)
    inv = Inventory()
    inv.potion_penalty = relic_potion_slot_penalty([RELIC_LOOT_SACK])
    added = sum(1 for _ in range(base + 2) if inv.add("HP_M_potion").get("ok"))
    check(f"전리품 자루로 포션 {base + 1}개까지 실제로 들어간다", added == base + 1, f"{added}")


def test_shop_discount():
    print("\n[4] 여행자의 지도 — 상점 아이템만 −20%")
    from app.Map import _get_shop_items
    from ai.battle.Relics import RELIC_TRAVELERS_MAP
    from game.Relics import RELIC_SHOP_PRICE

    plain = {i["id"]: i["price"] for i in _get_shop_items(5, [], "전사")}
    disc  = {i["id"]: i["price"] for i in _get_shop_items(5, [RELIC_TRAVELERS_MAP], "전사")}

    check("HP 중형 포션 50 → 40", plain["HP_M_potion"] == 50 and disc["HP_M_potion"] == 40,
          f"{plain['HP_M_potion']} → {disc['HP_M_potion']}")
    check("폭탄 120 → 96", plain["bomb"] == 120 and disc["bomb"] == 96,
          f"{plain['bomb']} → {disc['bomb']}")
    relic_ids = [i["id"] for i in _get_shop_items(5, [RELIC_TRAVELERS_MAP], "전사") if i["type"] == "relic"]
    check("유물 가격은 그대로",
          all(disc[r] == RELIC_SHOP_PRICE for r in relic_ids), f"{[disc[r] for r in relic_ids]}")
    # 지도를 가진 뒤에는 지도 자신만 진열에서 빠진다 (이미 가진 유물은 안 판다)
    check("할인 외에 목록 변화는 '가진 유물 제외'뿐",
          set(plain) - set(disc) == {RELIC_TRAVELERS_MAP} and not set(disc) - set(plain),
          f"{set(plain) ^ set(disc)}")


def test_relic_pool():
    print("\n[5] 공용 풀 8종")
    # 직업 전용 12종과 제시 규칙은 TestFile/test_relic_job.py — 여기는 공용 풀만 본다
    from game.Relics import RELIC_META, available_relics, relic_choices, shop_relic_items
    from ai.battle.Relics import COMMON_RELIC_IDS, JOB_RELIC_IDS, RELIC_IDS

    check("공용이 8종", len(COMMON_RELIC_IDS) == 8, f"{len(COMMON_RELIC_IDS)}")
    check("공용은 전부 job 빈 값", all(not RELIC_META[r]["job"] for r in COMMON_RELIC_IDS))
    check("메타와 RELIC_IDS가 일치", set(RELIC_META) == set(RELIC_IDS))
    check("공용 8종이 전부 메타에 있다", set(COMMON_RELIC_IDS) <= set(RELIC_META))
    check("아무것도 안 가졌으면 공용 8 + 내 직업 4 = 12종이 후보",
          len(available_relics([], "전사")) == 8 + len(JOB_RELIC_IDS["전사"]),
          f"{len(available_relics([], '전사'))}")
    owned = list(COMMON_RELIC_IDS[:6])
    check("가진 것은 후보에서 빠진다",
          set(available_relics(owned, "전사")) == set(COMMON_RELIC_IDS[6:]) | set(JOB_RELIC_IDS["전사"]))
    check("제시는 최대 3장", len(relic_choices([], "전사")) == 3)
    check("공용만 남았고 2종뿐이면 2장만",
          len(relic_choices(list(COMMON_RELIC_IDS[:6]) + list(JOB_RELIC_IDS["전사"]), "전사")) == 2)
    check("전부 가지면 제시 없음", relic_choices(list(RELIC_IDS), "전사") == [])
    check("상점은 안 가진 공용만 진열", len(shop_relic_items(owned, "전사")) == 2)


def test_tanker_locked():
    print("\n[6] 탱커 — 서버가 새 게임을 거부한다")
    from app import create_app

    with contextlib.redirect_stdout(_buf):
        app = create_app()
        app.config["TESTING"] = True
        c = app.test_client()
        r_bad  = c.post("/api/new_game", json={"name": "T", "job": "탱커"})
        r_junk = c.post("/api/new_game", json={"name": "T", "job": "없는직업"})
        r_ok   = c.post("/api/new_game", json={"name": "T", "job": "전사"})

    check("탱커 → 400", r_bad.status_code == 400, f"{r_bad.status_code}")
    check("탱커 거부 사유가 '준비 중'", "준비 중" in (r_bad.get_json() or {}).get("error", ""),
          f"{r_bad.get_json()}")
    check("모르는 직업 → 400", r_junk.status_code == 400, f"{r_junk.status_code}")
    check("전사는 정상 생성", r_ok.status_code == 200 and (r_ok.get_json() or {}).get("ok"),
          f"{r_ok.status_code}")

    # 탱커의 스탯·스킬 자체는 남아 있어야 한다 (골렘·유령 킷이 탱커 스킬을 쓴다)
    from game.Player_Class import JOB_BASE_STATS
    check("탱커 직업 데이터는 그대로 있다", "탱커" in JOB_BASE_STATS)


def main():
    print("=" * 52)
    print(" 유물 확장 1단계(공용 8종) + 탱커 잠금")
    print("=" * 52)
    test_mirror_shard()
    test_prophecy_badge_lead()
    test_potion_slots()
    test_shop_discount()
    test_relic_pool()
    test_tanker_locked()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    try:
        os.unlink(_db)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


main()
