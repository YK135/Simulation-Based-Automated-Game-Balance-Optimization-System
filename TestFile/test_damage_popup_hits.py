# -*- coding: utf-8 -*-
"""
test_damage_popup_hits.py — 데미지 숫자 팝업용 hits 필드 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_damage_popup_hits.py

검증 대상 (ai/battle_session/State.py의 _hp_snapshot / _hits_from_snapshot,
ai/Battlesession.py의 step):
  전투 응답에 실린 구조화 필드 hits로 프론트가 데미지 숫자를 띄운다.
  이 필드가 없거나 형태가 바뀌면 UI는 조용히 숫자를 안 띄우므로(예외 없음)
  회귀를 눈으로 잡기 어렵다 — 그래서 여기서 계약을 고정한다.

  1. _state()는 항상 hits 키를 갖는다 (step 밖에서 만든 초기 상태 포함)
  2. 플레이어가 때리면 해당 적 슬롯에 kind=damage 이벤트가 생긴다
  3. 적이 때리면 target=player 이벤트가 생긴다
  4. 실드가 흡수한 피해도 damage로 집계된다 (HP가 안 줄어도)
  5. 회복은 kind=heal, 실드 획득은 kind=shield
  6. 전투 중 새로 생긴 개체(분열/부활)가 있어도 인덱스 매핑이 깨지지 않는다
  7. 모든 이벤트는 crit 키를 갖는다 (프론트가 존재 여부를 안 따져도 되게)
"""
import sys, os, io, contextlib
from random import seed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.Player_Class import create_player_by_job
from game.Enemy_Class import Make_Goblin
from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot

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


def _make_session(job="전사", items=None):
    """레벨업/전투 시작 print를 삼키고 세션 하나를 만든다."""
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("테스터", job)
        g = Make_Goblin(p.lv, "중")
        s = BattleSession(
            EntitySnapshot.from_player(p),
            enemy=EntitySnapshot.from_enemy(g),
            items=list(items or []),
            enemy_origins=[g],
            is_boss=False,
            player_original=p,
        )
    return s


def _damage_events(hits, target=None, kind=None):
    out = hits
    if target is not None:
        out = [h for h in out if h["target"] == target]
    if kind is not None:
        out = [h for h in out if h["kind"] == kind]
    return out


# ═══════════════════════════════════════════════
def test_state_always_has_hits():
    print("\n[1] _state()는 항상 hits 키를 갖는다")
    s = _make_session()
    with contextlib.redirect_stdout(io.StringIO()):
        st = s._state(messages=["시작"])
    check("step 밖에서 만든 상태에도 hits 키 존재", "hits" in st)
    check("초기값은 빈 리스트", st.get("hits") == [], f"hits={st.get('hits')}")


def test_player_hit_produces_enemy_damage_event():
    print("\n[2] 플레이어 공격 → 적 슬롯 damage 이벤트")
    s = _make_session()
    hp_before = s.enemies[0].hp
    with contextlib.redirect_stdout(io.StringIO()):
        out = s.step("attack")
    hits = out.get("hits", [])
    dmg = _damage_events(hits, "enemy", "damage")
    check("적 damage 이벤트 1건", len(dmg) == 1, f"hits={hits}")
    if dmg:
        check("슬롯 인덱스는 0", dmg[0]["slot"] == 0, f"slot={dmg[0]['slot']}")
        check("amount > 0", dmg[0]["amount"] > 0, f"amount={dmg[0]['amount']}")
        actual = int(round(hp_before - s.enemies[0].hp))
        check("amount가 실제 HP 감소량과 일치",
              dmg[0]["amount"] == actual,
              f"event={dmg[0]['amount']} actual={actual}")
    check("모든 이벤트에 crit 키 존재", all("crit" in h for h in hits), f"hits={hits}")


def test_enemy_hit_produces_player_event():
    print("\n[3] 적 공격 → target=player 이벤트")
    # ★ 결정적으로 만든다 — 예전엔 시드 없이 최대 8턴만 돌려서, 회피가
    #   연달아 터지거나 적이 먼저 죽으면 간헐적으로 실패했다(실제로 발생).
    #   시드 고정 + 적을 못 죽게 만들고 충분히 돌린다.
    seed(20260916)
    s = _make_session()
    s.enemies[0].hp = 10_000_000.0
    s.enemies[0].maxhp = 10_000_000.0
    found = None
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(40):
            if s.done:
                break
            actor = s._peek_next_actor()[0]
            out = s.step("attack" if actor == "player" else "auto")
            ev = _damage_events(out.get("hits", []), "player", "damage")
            if ev:
                found = ev[0]
                break
    check("플레이어 피격 damage 이벤트 발생", found is not None)
    if found:
        check("target=player, slot=-1",
              found["target"] == "player" and found["slot"] == -1,
              f"ev={found}")
        check("amount > 0", found["amount"] > 0, f"amount={found['amount']}")


def test_shield_absorbed_counts_as_damage():
    print("\n[4] 실드가 흡수한 피해도 damage로 집계")
    s = _make_session()
    en = s.enemies[0]
    en.shield = 10_000.0          # 이번 공격을 전부 흡수
    hp_before = en.hp
    with contextlib.redirect_stdout(io.StringIO()):
        out = s.step("attack")
    dmg = _damage_events(out.get("hits", []), "enemy", "damage")
    check("HP는 안 줄었다", en.hp == hp_before, f"hp {hp_before}→{en.hp}")
    check("그래도 damage 이벤트가 있다", len(dmg) == 1, f"hits={out.get('hits')}")
    if dmg:
        check("흡수량이 amount로 집계", dmg[0]["amount"] > 0, f"amount={dmg[0]['amount']}")


def test_heal_and_shield_kinds():
    print("\n[5] 회복=heal / 실드 획득=shield")
    s = _make_session()
    # ★ 풀피에서는 회복이 maxhp에 걸려 0이 되므로, 먼저 HP를 깎아 여유를 만든다
    #   (스냅샷은 깎은 뒤에 떠야 이 단계가 damage로 잡히지 않는다)
    s.player.hp = max(1.0, s.player.hp - 100)
    before = s._hp_snapshot()
    s.player.hp = min(s.player.maxhp, s.player.hp + 40)   # 회복
    s.player.shield = getattr(s.player, "shield", 0.0) + 25  # 실드 획득
    hits = s._hits_from_snapshot(before)
    heal = _damage_events(hits, "player", "heal")
    shield = _damage_events(hits, "player", "shield")
    check("heal 이벤트 존재", len(heal) == 1, f"hits={hits}")
    check("shield 이벤트 존재", len(shield) == 1, f"hits={hits}")
    if heal:
        check("heal amount == 40", heal[0]["amount"] == 40, f"amount={heal[0]['amount']}")
    if shield:
        check("shield amount == 25", shield[0]["amount"] == 25, f"amount={shield[0]['amount']}")


def test_new_entity_midbattle_does_not_break_mapping():
    print("\n[6] 전투 중 개체 추가(분열/부활)에도 인덱스 매핑 안전")
    s = _make_session()
    before = s._hp_snapshot()          # 적 1마리 기준 스냅샷
    # 분열/부활처럼 스냅샷 이후 적이 늘어난 상황을 재현
    extra = EntitySnapshot.from_enemy(Make_Goblin(1, "하"))
    s.enemies.append(extra)
    s.enemies[0].hp = max(0.0, s.enemies[0].hp - 15)
    try:
        hits = s._hits_from_snapshot(before)
        ok = True
    except Exception as e:                       # noqa: BLE001
        ok = False
        hits = []
        print(f"     예외: {e!r}")
    check("예외 없이 처리", ok)
    dmg = _damage_events(hits, "enemy", "damage")
    check("기존 슬롯(0)의 피해만 집계", len(dmg) == 1 and dmg[0]["slot"] == 0, f"hits={hits}")


def test_crit_attribution_single_target_only():
    print("\n[7] 크리 귀속은 피해 대상이 1마리일 때만")
    s = _make_session()
    before = s._hp_snapshot()
    # 크리 로그를 가짜로 넣고, 적 2마리가 동시에 피해를 입은 상황을 만든다
    from ai.battle.Engine import TurnLog
    s.logs.append(TurnLog(turn=1, actor="player", action="attack",
                          action_detail="attack", is_crit=True))
    s.enemies.append(EntitySnapshot.from_enemy(Make_Goblin(1, "하")))
    before["enemies"].append((s.enemies[1].hp, getattr(s.enemies[1], "shield", 0.0)))
    s.enemies[0].hp -= 10
    s.enemies[1].hp -= 10
    hits_multi = s._hits_from_snapshot(before)
    dmg_multi = _damage_events(hits_multi, "enemy", "damage")
    check("2마리 피해 시 crit 표시 안 함",
          len(dmg_multi) == 2 and all(h["crit"] is False for h in dmg_multi),
          f"hits={hits_multi}")

    # 1마리만 맞은 경우엔 crit 귀속
    s2 = _make_session()
    before2 = s2._hp_snapshot()
    s2.logs.append(TurnLog(turn=1, actor="player", action="attack",
                           action_detail="attack", is_crit=True))
    s2.enemies[0].hp -= 10
    dmg_single = _damage_events(s2._hits_from_snapshot(before2), "enemy", "damage")
    check("1마리 피해 시 crit=True",
          len(dmg_single) == 1 and dmg_single[0]["crit"] is True,
          f"hits={dmg_single}")


def main():
    print("=" * 56)
    print(" 데미지 숫자 팝업 hits 필드 회귀 테스트")
    print("=" * 56)

    test_state_always_has_hits()
    test_player_hit_produces_enemy_damage_event()
    test_enemy_hit_produces_player_event()
    test_shield_absorbed_counts_as_damage()
    test_heal_and_shield_kinds()
    test_new_entity_midbattle_does_not_break_mapping()
    test_crit_attribution_single_target_only()

    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
