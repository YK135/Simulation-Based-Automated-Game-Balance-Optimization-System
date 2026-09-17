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
  8. 색 구분용 태그(element/reaction/via)가 출처별로 맞게 붙는다
  9. 태그는 step마다 초기화된다 (지난 턴 원소가 이번 DoT에 묻지 않는다)
"""
import sys, os, io, contextlib
from random import seed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.Player_Class import create_player_by_job
from game.Enemy_Class import Make_Goblin
from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot
from ai.battle.Entity import StatusEffect

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
    # ★ 결정적으로 — 시드 없이 한 번만 때리면 고블린 회피(약 2%)에 걸릴 때 이벤트가 없어 간헐 실패했다
    seed(20260917)
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


# ═══════════════════════════════════════════════
# 색 구분용 태그 (element / reaction / via)
# ═══════════════════════════════════════════════
def _tanky(s):
    """양쪽을 안 죽게 만들어 원하는 턴까지 확실히 굴린다."""
    s.player.hp = s.player.maxhp = 999_999.0
    s.player.mp = s.player.maxmp = 999.0
    s.enemies[0].hp = s.enemies[0].maxhp = 999_999.0
    return s


def _player_turn_step(s, action, prep=None):
    """플레이어 차례가 올 때까지 auto로 넘긴 뒤 원하는 행동 1회 → hits 반환.
    (ATB 때문에 첫 step이 적 턴일 수 있어서 그냥 step 한 번은 못 쓴다)"""
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(40):
            if s.done:
                return []
            if s._peek_next_actor()[0] == "player":
                if prep:
                    prep(s)
                return s.step(action)["hits"]
            s.step("auto")
    return []


def _learn(s, *names):
    s.player.learned_skills = list(dict.fromkeys(list(s.player.learned_skills) + list(names)))
    return s


def _first_enemy_damage(hits):
    for h in hits:
        if h["target"] == "enemy" and h["kind"] == "damage":
            return h
    return None


def test_hit_tags_present_on_every_event():
    print("\n[8] 모든 이벤트가 element/reaction/via 키를 갖는다")
    seed(20260917)
    s = _tanky(_make_session())
    hits = _player_turn_step(s, "attack")
    check("피해 이벤트 발생", len(hits) > 0, f"hits={hits}")
    keys = ("element", "reaction", "via", "crit")
    check("모든 이벤트에 태그 키 존재",
          all(all(k in h for k in keys) for h in hits), f"hits={hits}")


def test_tag_physical_attack_vs_skill():
    print("\n[9] 기본 공격 = via:attack / 물리 스킬 = via:skill, 둘 다 element:physical")
    seed(20260917)
    ev = _first_enemy_damage(_player_turn_step(_tanky(_make_session()), "attack"))
    check("기본 공격: element=physical, via=attack",
          ev is not None and ev["element"] == "physical" and ev["via"] == "attack",
          f"ev={ev}")

    seed(20260917)
    s = _learn(_tanky(_make_session("전사")), "강타1")
    ev = _first_enemy_damage(_player_turn_step(s, "skill:강타1"))
    check("물리 스킬: element=physical, via=skill",
          ev is not None and ev["element"] == "physical" and ev["via"] == "skill",
          f"ev={ev}")
    check("반응 없음", ev is not None and ev["reaction"] == "", f"ev={ev}")


def test_tag_elements():
    print("\n[10] 원소 스킬의 element 태그")
    for skill, elem in (("파이어볼1", "fire"), ("아이스볼릿1", "ice"), ("라이트닝1", "lightning")):
        seed(20260917)
        s = _learn(_tanky(_make_session("마법사")), skill)
        ev = _first_enemy_damage(_player_turn_step(s, f"skill:{skill}"))
        check(f"{skill} → element={elem}",
              ev is not None and ev["element"] == elem, f"ev={ev}")


def test_tag_reactions():
    print("\n[11] 원소 반응(융해/과부하/파쇄)의 reaction 태그")

    def attach(elem):
        def _p(s):
            s.enemies[0].element_queue = [elem]
        return _p

    seed(20260917)
    s = _learn(_tanky(_make_session("마법사")), "파이어볼1")
    ev = _first_enemy_damage(_player_turn_step(s, "skill:파이어볼1", attach("ice")))
    check("ice→fire = melt", ev is not None and ev["reaction"] == "melt", f"ev={ev}")
    check("melt에도 element=fire 유지",
          ev is not None and ev["element"] == "fire", f"ev={ev}")

    seed(20260917)
    s = _learn(_tanky(_make_session("마법사")), "라이트닝1")
    ev = _first_enemy_damage(_player_turn_step(s, "skill:라이트닝1", attach("fire")))
    check("fire→lightning = overload",
          ev is not None and ev["reaction"] == "overload", f"ev={ev}")

    # 파쇄는 물리 공격이 ice 큐를 때릴 때 — 마법사 패시브에서 제외된 반응
    seed(20260917)
    ev = _first_enemy_damage(
        _player_turn_step(_tanky(_make_session("전사")), "attack", attach("ice")))
    check("물리 vs ice = shatter",
          ev is not None and ev["reaction"] == "shatter", f"ev={ev}")
    check("shatter는 element=physical",
          ev is not None and ev["element"] == "physical", f"ev={ev}")


def test_tag_dot_is_separated_from_the_attack_in_the_same_step():
    print("\n[12] 같은 step의 DoT와 피격이 각각 자기 태그를 갖는다")
    # ★ 이게 태그를 "행동 로그"가 아니라 "대상별"로 남기는 이유.
    #   적 턴 = (적의 출혈 틱 → 적이 플레이어를 때림) 이 한 step에 같이 일어난다.
    #   로그 한 줄로 색을 정하면 적의 출혈 피해까지 물리색이 된다.
    seed(20260917)
    s = _tanky(_make_session("도적"))
    s.enemies[0].apply_status_effect(StatusEffect(effect_type="bleed", turns=9, name="bleed"))
    found = None
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(40):
            if s.done:
                break
            actor = s._peek_next_actor()[0]
            hits = s.step("attack" if actor == "player" else "auto")["hits"]
            dot = [h for h in hits if h["target"] == "enemy" and h["via"] == "dot"]
            hurt = [h for h in hits if h["target"] == "player" and h["kind"] == "damage"]
            if dot and hurt:
                found = (dot[0], hurt[0])
                break
    check("DoT + 피격이 같은 step에 잡힌 케이스 발견", found is not None)
    if found:
        dot, hurt = found
        check("출혈 DoT: element=bleed, via=dot",
              dot["element"] == "bleed" and dot["via"] == "dot", f"dot={dot}")
        check("같은 step의 플레이어 피격은 물리로 유지",
              hurt["element"] == "physical", f"hurt={hurt}")


def test_tags_reset_each_step():
    print("\n[13] 태그는 step 진입 시 초기화된다")
    seed(20260917)
    s = _learn(_tanky(_make_session("마법사")), "파이어볼1")
    _player_turn_step(s, "skill:파이어볼1")     # 적에게 fire 태그가 남은 상태
    check("직전 step이 fire를 남겼다",
          getattr(s.enemies[0], "last_hit_element", "") == "fire",
          f"tag={getattr(s.enemies[0], 'last_hit_element', None)}")
    s._hp_snapshot()                            # 다음 step 진입
    check("스냅샷 후 element 태그 초기화",
          getattr(s.enemies[0], "last_hit_element", "") == "", )
    check("스냅샷 후 via 태그 초기화",
          getattr(s.enemies[0], "last_hit_via", "") == "", )
    check("플레이어 태그도 초기화",
          getattr(s.player, "last_hit_element", "") == "", )


def test_aura_only_call_does_not_stamp():
    print("\n[14] 피해 0인 원소 부착만으로는 태그를 남기지 않는다")
    # 부착 전용 호출(try_apply_element_aura_and_status)이 태그를 덮어쓰면
    # 같은 step의 DoT 피해가 엉뚱한 색으로 표시된다.
    from ai.battle.Elements import apply_element_and_react
    s = _make_session()
    en = s.enemies[0]
    en.last_hit_element = ""
    apply_element_and_react(s.player, en, "fire", 0, [])
    check("damage=0 → element 태그 없음",
          getattr(en, "last_hit_element", "") == "",
          f"tag={getattr(en, 'last_hit_element', None)}")
    check("큐에는 정상 부착 (기존 동작 불변)",
          en.element_queue == ["fire"], f"q={en.element_queue}")


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
    test_hit_tags_present_on_every_event()
    test_tag_physical_attack_vs_skill()
    test_tag_elements()
    test_tag_reactions()
    test_tag_dot_is_separated_from_the_attack_in_the_same_step()
    test_tags_reset_each_step()
    test_aura_only_call_does_not_stamp()

    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
