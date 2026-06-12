"""
test_battle_lock.py — 전투 시스템 회귀 테스트 (전투 잠금)
─────────────────────────────────────────────
실제 전투(BattleSession)와 시뮬레이터(BattleEngine)가 공유하는
Battle_Engine.py 공통 로직을 검증한다.

실행:
    python3 test_battle_lock.py
또는:
    pytest test_battle_lock.py -v

모든 테스트가 통과해야 전투 시스템을 "잠금"으로 간주하고
다음 기능 개발로 넘어간다.
"""
import sys
import os

# ai/ 경로 추가 (프로젝트 루트에서 실행 가정)
_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (_HERE, os.path.join(_HERE, "ai"), os.path.join(_HERE, "game"),
          os.path.join(_HERE, "core")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from ai.battle.Battle_Engine import (
        EntitySnapshot, StatusEffect, Debuff, Buff,
        execute_skill, use_item, apply_element_and_react,
        _apply_damage_with_shield, SKILL_META, ITEM_META, REACTIONS,
    )
except ModuleNotFoundError:
    from ai.battle.Battle_Engine import (
        EntitySnapshot, StatusEffect, Debuff, Buff,
        execute_skill, use_item, apply_element_and_react,
        _apply_damage_with_shield, SKILL_META, ITEM_META, REACTIONS,
    )


# ─────────────────────────────────────────────
# 헬퍼: 테스트용 엔티티 생성
# ─────────────────────────────────────────────

def make_player(hp=500, mp=300, stg=40, sp=40, skills=None, items=None,
                element_queue=None):
    return EntitySnapshot(
        name="플레이어", hp=hp, maxhp=hp, mp=mp, maxmp=mp,
        stg=stg, arm=10, sparm=10, sp=sp, luc=10, lv=10, spd=15,
        learned_skills=skills or [], items=items or [],
        debuffs=[], buffs=[], element_queue=element_queue or [],
        status_effects=[],
    )


def make_enemy(hp=300, element_queue=None, attack_element=""):
    return EntitySnapshot(
        name="적", hp=hp, maxhp=hp, mp=50, maxmp=50,
        stg=10, arm=5, sparm=5, sp=5, luc=0, lv=5, spd=8,
        learned_skills=[], items=[], debuffs=[], buffs=[],
        element_queue=element_queue or [], status_effects=[],
        attack_element=attack_element,
    )


# ─────────────────────────────────────────────
# 테스트 러너 (pytest 없이도 동작)
# ─────────────────────────────────────────────

_results = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    _results.append((name, cond, detail))
    mark = "✅" if cond else "❌"
    print(f"  {mark} [{status}] {name}" + (f"  — {detail}" if detail else ""))
    return cond


# ─────────────────────────────────────────────
# 1. 일반 공격 (기본 데미지 발생)
# ─────────────────────────────────────────────

def test_basic_attack():
    print("\n[1] 일반 공격")
    p = make_player()
    e = make_enemy(hp=300)
    before = e.hp
    # 기본 공격은 BattleSession이 처리하지만, 데미지 적용 함수로 검증
    dmg = 50
    actual = _apply_damage_with_shield(e, dmg)
    check("기본 공격 데미지 적용", e.hp < before, f"{before}→{e.hp}")
    check("데미지 반환값 정상", actual == 50, f"actual={actual}")


# ─────────────────────────────────────────────
# 2. 물리/마법 스킬
# ─────────────────────────────────────────────

def test_physical_magical_skill():
    print("\n[2] 물리/마법 스킬")
    p = make_player(skills=["강타1", "파이어볼1"])
    e = make_enemy(hp=500)

    # 물리 스킬
    dmg_p, lack_p, info_p = execute_skill("강타1", p, e)
    check("물리 스킬(강타1) 데미지 > 0", dmg_p > 0, f"dmg={dmg_p}")
    check("물리 스킬 MP 충분", not lack_p)

    # 마법 스킬
    p2 = make_player(skills=["파이어볼1"])
    e2 = make_enemy(hp=500)
    dmg_m, lack_m, info_m = execute_skill("파이어볼1", p2, e2)
    check("마법 스킬(파이어볼1) 데미지 > 0", dmg_m > 0, f"dmg={dmg_m}")
    check("마법 스킬 원소 부착됨", e2.element_queue == ["fire"],
          f"queue={e2.element_queue}")


# ─────────────────────────────────────────────
# 3. AoE 스킬 (SKILL_META aoe 플래그)
# ─────────────────────────────────────────────

def test_aoe_skill():
    print("\n[3] AoE 스킬")
    # 슬래시1, 난사1이 aoe=True
    check("슬래시1 AoE 플래그", SKILL_META.get("슬래시1", {}).get("aoe") == True)
    check("난사1 AoE 플래그", SKILL_META.get("난사1", {}).get("aoe") == True)

    # AoE 스킬 단일 실행 데미지 확인
    p = make_player(skills=["슬래시1"], stg=50)
    e = make_enemy(hp=500)
    dmg, lack, info = execute_skill("슬래시1", p, e)
    check("AoE 스킬 데미지 > 0", dmg > 0, f"dmg={dmg}")


# ─────────────────────────────────────────────
# 4. target_index 단일 공격 (use_item element 단일 타깃)
# ─────────────────────────────────────────────

def test_target_index():
    print("\n[4] target_index 단일 공격")
    p = make_player(items=["fire_vial"])
    e1 = make_enemy(hp=200)
    e2 = make_enemy(hp=200)
    # 원소병은 첫 alive에게만 (단일 타깃)
    use_item("fire_vial", p, enemies=[e1, e2])
    check("단일 타깃만 원소 부착", e1.element_queue == ["fire"] and e2.element_queue == [],
          f"e1={e1.element_queue}, e2={e2.element_queue}")


# ─────────────────────────────────────────────
# 5. HP/MP 포션
# ─────────────────────────────────────────────

def test_potions():
    print("\n[5] HP/MP 포션")
    p = make_player(hp=500, mp=300)
    p.hp = 100
    p.mp = 50
    p.items = ["HP_M_potion", "MP_M_potion"]

    use_item("HP_M_potion", p)
    check("HP 포션 회복", p.hp > 100, f"hp={p.hp}")

    use_item("MP_M_potion", p)
    check("MP 포션 회복", p.mp > 50, f"mp={p.mp}")

    check("HP 포션 maxhp 초과 안 함", p.hp <= p.maxhp)


# ─────────────────────────────────────────────
# 6. bomb, web_bomb (AoE 데미지)
# ─────────────────────────────────────────────

def test_bombs():
    print("\n[6] bomb / web_bomb")
    p = make_player(items=["bomb", "web_bomb"])
    e1 = make_enemy(hp=400)
    e2 = make_enemy(hp=400)

    use_item("bomb", p, enemies=[e1, e2])
    # bomb = 25% maxhp
    check("bomb 적1 25% 피해", e1.hp == 300, f"e1={e1.hp} (기대 300)")
    check("bomb 적2 25% 피해", e2.hp == 300, f"e2={e2.hp} (기대 300)")

    e3 = make_enemy(hp=400)
    use_item("web_bomb", p, enemies=[e3])
    # web_bomb = 18% maxhp + spd 디버프
    check("web_bomb 18% 피해", e3.hp == int(400 - 400*0.18), f"e3={e3.hp}")
    check("web_bomb 속도 디버프", any(d.stat == "spd" for d in e3.debuffs),
          f"debuffs={[d.stat for d in e3.debuffs]}")


# ─────────────────────────────────────────────
# 7. 원소병 (fire/ice/lightning vial)
# ─────────────────────────────────────────────

def test_element_vials():
    print("\n[7] 원소병 (fire/ice/lightning)")
    for vial, elem in [("fire_vial", "fire"), ("ice_vial", "ice"),
                       ("lightning_crystal", "lightning")]:
        p = make_player(items=[vial])
        e = make_enemy(hp=300)
        use_item(vial, p, enemies=[e])
        check(f"{vial} → {elem} 부착", e.element_queue == [elem],
              f"queue={e.element_queue}")
        check(f"{vial} 직접 피해", e.hp < 300, f"hp={e.hp}")


# ─────────────────────────────────────────────
# 8. focus_drug (다음 스킬 강화)
# ─────────────────────────────────────────────

def test_focus_drug():
    print("\n[8] focus_drug")
    p = make_player(items=["focus_drug"])
    use_item("focus_drug", p)
    check("focus_drug 보너스 세팅", p._next_skill_bonus == 1.5,
          f"bonus={p._next_skill_bonus}")


# ─────────────────────────────────────────────
# 9. haste_drug (ATB 추가)
# ─────────────────────────────────────────────

def test_haste_drug():
    print("\n[9] haste_drug")
    p = make_player(items=["haste_drug"])
    use_item("haste_drug", p)
    check("haste_drug ATB 보너스 세팅", p._pending_atb_bonus == 50,
          f"atb={p._pending_atb_bonus}")


# ─────────────────────────────────────────────
# 10. 원소 부착 (큐)
# ─────────────────────────────────────────────

def test_element_attach():
    print("\n[10] 원소 부착")
    e = make_enemy(hp=300)
    msgs = []
    apply_element_and_react(None, e, "fire", 100, msgs)
    check("빈 큐에 fire 부착", e.element_queue == ["fire"],
          f"queue={e.element_queue}")


# ─────────────────────────────────────────────
# 11. 원소 반응: 융해 / 과부하 / 파쇄
# ─────────────────────────────────────────────

def test_reactions():
    print("\n[11] 원소 반응")

    # 융해: ice 큐 + fire 공격 = 1.5x
    e1 = make_enemy(hp=500, element_queue=["ice"])
    msgs1 = []
    dmg1 = apply_element_and_react(None, e1, "fire", 100, msgs1)
    check("융해 (ice+fire) 1.5x", dmg1 == 150, f"dmg={dmg1} (기대 150)")
    check("융해 후 큐 초기화", e1.element_queue == [], f"queue={e1.element_queue}")

    # 과부하: fire 큐 + lightning 공격 = 1.3x
    e2 = make_enemy(hp=500, element_queue=["fire"])
    msgs2 = []
    dmg2 = apply_element_and_react(None, e2, "lightning", 100, msgs2)
    check("과부하 (fire+lightning) 1.3x", dmg2 == 130, f"dmg={dmg2} (기대 130)")

    # 과부하: lightning 큐 + fire 공격 = 1.3x
    e3 = make_enemy(hp=500, element_queue=["lightning"])
    msgs3 = []
    dmg3 = apply_element_and_react(None, e3, "fire", 100, msgs3)
    check("과부하 (lightning+fire) 1.3x", dmg3 == 130, f"dmg={dmg3} (기대 130)")

    # 파쇄: ice 큐 + physical 공격 = 1.2x
    e4 = make_enemy(hp=500, element_queue=["ice"])
    msgs4 = []
    dmg4 = apply_element_and_react(None, e4, "physical", 100, msgs4)
    # 1.2배 = +20이지만 부동소수점(0.2*100=19.99..) 때문에 119~120 허용
    check("파쇄 (ice+physical) ~1.2x", dmg4 in (119, 120), f"dmg={dmg4} (기대 119~120)")
    check("파쇄 후 큐 초기화", e4.element_queue == [], f"queue={e4.element_queue}")


# ─────────────────────────────────────────────
# 12. 상태이상: 화상 / 동상 / 마비
# ─────────────────────────────────────────────

def test_status_effects():
    print("\n[12] 상태이상")

    # 화상 (점화): tick 시 maxhp 비례 데미지
    e = make_enemy(hp=500)
    e.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="fire"))
    before = e.hp
    msgs = e.tick_status_effects()
    check("화상 점화 데미지", e.hp < before, f"{before}→{e.hp}")

    # 동상 (frostbite): effective_spd 50% 감소
    e2 = make_enemy(hp=500)
    base_spd = e2.effective_spd()
    e2.apply_status_effect(StatusEffect(effect_type="frostbite", turns=2, name="ice"))
    slowed_spd = e2.effective_spd()
    check("동상 SPD 50% 감소", slowed_spd < base_spd,
          f"{base_spd}→{slowed_spd}")

    # 마비 (paralyze): is_paralyzed 메서드 존재 + 확률 동작
    e3 = make_enemy(hp=500)
    e3.apply_status_effect(StatusEffect(effect_type="paralyze", turns=3, name="lightning", fail_prob=100))
    check("마비 100% 행동 실패", e3.is_paralyzed() == True)


# ─────────────────────────────────────────────
# 13. HP 0 미만 방지
# ─────────────────────────────────────────────

def test_hp_clamp():
    print("\n[13] HP 0 미만 방지")
    e = make_enemy(hp=30)
    _apply_damage_with_shield(e, 999)
    check("과다 데미지 후 HP == 0", e.hp == 0, f"hp={e.hp}")
    check("HP 음수 아님", e.hp >= 0)


# ─────────────────────────────────────────────
# 14. Auto_AI 특수 아이템 선택
# ─────────────────────────────────────────────

def test_auto_ai_special():
    print("\n[14] Auto_AI 특수 아이템 선택")
    try:
        try:
            from ai.Auto_AI import PlayerAI
        except ModuleNotFoundError:
            from ai.Auto_AI import PlayerAI
    except Exception as ex:
        check("Auto_AI import", False, f"import 실패: {ex}")
        return

    ai = PlayerAI()

    # ice 적 + 화염병 → fire_vial 선택 (융해 노림)
    p = make_player(skills=["파이어볼1"], items=["fire_vial", "HP_M_potion"])
    e = make_enemy(hp=300, element_queue=["ice"])
    act = ai.decide(p, e)
    check("ice 적 + 화염병 → fire_vial", act.detail == "fire_vial",
          f"선택={act.action_type}:{act.detail}")

    # 아이템 없음 → 스킬 또는 공격
    p2 = make_player(skills=["강타1"], items=[])
    e2 = make_enemy(hp=300)
    act2 = ai.decide(p2, e2)
    check("아이템 없음 → 스킬/공격", act2.action_type in ("skill", "attack"),
          f"선택={act2.action_type}:{act2.detail}")


# ─────────────────────────────────────────────
# 15. 전투 로그 필드 (action, target, damage, reaction, status)
# ─────────────────────────────────────────────

def test_battle_log():
    print("\n[15] 전투 로그 기록")
    try:
        try:
            from ai.battle.Battle_Engine import TurnLog
        except ModuleNotFoundError:
            from ai.battle.Battle_Engine import TurnLog
    except Exception as ex:
        check("TurnLog import", False, f"{ex}")
        return

    import dataclasses
    fields = {f.name for f in dataclasses.fields(TurnLog)}
    check("로그에 action 필드", "action" in fields, f"fields={sorted(fields)}")
    check("로그에 데미지 필드", "damage_dealt" in fields)
    check("로그에 action_detail 필드", "action_detail" in fields)


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  전투 시스템 잠금 회귀 테스트 (test_battle_lock)")
    print("=" * 55)

    test_basic_attack()
    test_physical_magical_skill()
    test_aoe_skill()
    test_target_index()
    test_potions()
    test_bombs()
    test_element_vials()
    test_focus_drug()
    test_haste_drug()
    test_element_attach()
    test_reactions()
    test_status_effects()
    test_hp_clamp()
    test_auto_ai_special()
    test_battle_log()

    print("\n" + "=" * 55)
    passed = sum(1 for _, c, _ in _results if c)
    total = len(_results)
    print(f"  결과: {passed}/{total} 통과")
    if passed == total:
        print("  ✅ 전투 시스템 잠금 — 모든 테스트 통과")
    else:
        print("  ❌ 실패한 테스트:")
        for name, cond, detail in _results:
            if not cond:
                print(f"     - {name}  {detail}")
    print("=" * 55)
    return 0 if passed == total else 1


# ── pytest 호환 ──
def test_all():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())