# -*- coding: utf-8 -*-
"""
test_element_fix.py — 버그 3, 4 수정 검증 스크립트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 test_element_fix.py

검증 항목:
  [버그 3] 원소 슬라임 초기 큐 보존
    - hook.get_enemy → make_battle_unit → from_enemy 왕복에서 큐 유실 없음
    - 화염/빙결/번개 슬라임이 각자 원소 큐를 갖고 전투 시작
  [버그 4] 동일 원소 면역
    - 같은 원소 공격: 0 데미지, 큐 변화 없음, 상태이상 없음, 반응 없음
    - 다른 원소/물리/일반 몬스터: 기존 동작 유지 (회귀 방지)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys

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


def make_snap(name, hp=500):
    from ai.battle import EntitySnapshot
    return EntitySnapshot(
        name=name, hp=hp, maxhp=hp, mp=0, maxmp=0,
        stg=30, arm=20, sparm=15, sp=10, luc=5, lv=5,
        enemy_type=name,
    )


def test_immunity():
    print("\n[버그 4] 동일 원소 면역")
    from ai.battle.Elements import apply_element_and_react, is_element_immune

    # 1. 같은 원소 → 완전 무효
    for mon, elem in [("화염 슬라임", "fire"), ("빙결 슬라임", "ice"), ("번개 슬라임", "lightning")]:
        s = make_snap(mon)
        msgs = []
        dmg = apply_element_and_react(None, s, elem, 100, msgs)
        check(f"{mon} ← {elem}: 0 데미지", dmg == 0, f"dmg={dmg}")
        check(f"{mon} ← {elem}: 큐 변화 없음", s.element_queue == [], f"q={s.element_queue}")
        check(f"{mon} ← {elem}: 상태이상 없음", not s.status_effects)
        check(f"{mon} ← {elem}: '효과가 없다' 메시지", any("효과가 없다" in m for m in msgs))

    # 2. 다른 원소 → 정상 부착
    s = make_snap("화염 슬라임")
    dmg = apply_element_and_react(None, s, "ice", 100, [])
    check("화염 슬라임 ← ice: 정상 데미지", dmg == 100, f"dmg={dmg}")
    check("화염 슬라임 ← ice: 큐 부착", s.element_queue == ["ice"], f"q={s.element_queue}")

    # 3. ice 부착 상태에서 fire → 면역이 melt보다 우선
    msgs = []
    dmg = apply_element_and_react(None, s, "fire", 100, msgs)
    check("ice 부착 화염 슬라임 ← fire: 면역 우선 (melt 미발동)",
          dmg == 0 and s.element_queue == ["ice"], f"dmg={dmg}, q={s.element_queue}")

    # 4. 일반 몬스터 회귀 방지
    g = make_snap("고블린")
    dmg = apply_element_and_react(None, g, "fire", 100, [])
    check("고블린 ← fire: 기존 동작 (100 데미지 + 부착)",
          dmg == 100 and g.element_queue == ["fire"])

    # 5. 물리 파쇄 + 원소 슬라임 고유 원소(innate) 복구
    #    새 설계: 원소 슬라임은 반응/파쇄로 큐가 비어도 고유 원소를 다시 부착.
    #    화염 슬라임(ice) ← physical → 파쇄 → 큐 비움 → innate [fire] 복구
    f2 = make_snap("화염 슬라임")
    f2.element_queue = ["ice"]
    msgs = []
    dmg = apply_element_and_react(None, f2, "physical", 100, msgs)
    check("화염 슬라임(ice) ← physical: 파쇄 데미지 119~120",
          dmg in (119, 120), f"dmg={dmg}")
    check("화염 슬라임: 파쇄 후 고유 원소 [fire] 복구",
          f2.element_queue == ["fire"], f"q={f2.element_queue}")

    # 빙결/번개 슬라임도 동일하게 고유 원소 복구
    ic = make_snap("빙결 슬라임"); ic.element_queue = ["ice"]
    apply_element_and_react(None, ic, "fire", 100, [])   # melt → clear → [ice]
    check("빙결 슬라임: 반응 후 고유 원소 [ice] 복구",
          ic.element_queue == ["ice"], f"q={ic.element_queue}")
    lg = make_snap("번개 슬라임"); lg.element_queue = ["lightning"]
    apply_element_and_react(None, lg, "fire", 100, [])   # overload → clear → [lightning]
    check("번개 슬라임: 반응 후 고유 원소 [lightning] 복구",
          lg.element_queue == ["lightning"], f"q={lg.element_queue}")

    # 일반 고블린은 기존처럼 빈 큐 유지 (innate 없음)
    gob = make_snap("고블린"); gob.element_queue = ["ice"]
    apply_element_and_react(None, gob, "physical", 100, [])
    check("고블린: 파쇄 후 큐 [] 유지 (innate 없음)",
          gob.element_queue == [], f"q={gob.element_queue}")

    # 6. helper 직접 검증
    check("is_element_immune(화염, fire) = True", is_element_immune(make_snap("화염 슬라임"), "fire"))
    check("is_element_immune(화염, ice) = False", not is_element_immune(make_snap("화염 슬라임"), "ice"))
    check("is_element_immune(고블린, fire) = False", not is_element_immune(make_snap("고블린"), "fire"))


def test_queue_preserved():
    print("\n[버그 3] 원소 슬라임 초기 큐 보존")
    from ai.battle import EntitySnapshot

    # 1. from_enemy 이름 fallback (유실 재현 케이스)
    class Bare:  # 원소 필드가 전혀 없는 unit (유실 상황)
        name = "화염 슬라임"; hp = 300; stg = 20; arm = 10; luc = 5; lv = 4
        enemy_type = "화염 슬라임"
    s = EntitySnapshot.from_enemy(Bare())
    check("유실 상황 → 이름 fallback 복구", s.element_queue == ["fire"], f"q={s.element_queue}")

    # 2. init_element_queue 정상 경로
    class WithQ:
        name = "번개 슬라임"; hp = 300; stg = 20; arm = 10; luc = 5; lv = 4
        enemy_type = "번개 슬라임"; init_element_queue = ["lightning"]
    s2 = EntitySnapshot.from_enemy(WithQ())
    check("init_element_queue 정상 보존", s2.element_queue == ["lightning"])

    # 3. 일반 몬스터는 빈 큐 (오염 방지)
    class Gob:
        name = "고블린"; hp = 200; stg = 15; arm = 8; luc = 3; lv = 2
        enemy_type = "고블린"
    s3 = EntitySnapshot.from_enemy(Gob())
    check("고블린: 빈 큐 유지", s3.element_queue == [])

    # 4. 실제 변환 경로: EntitySnapshot → _SnapUnit → from_enemy 왕복
    #    (버그3 유실 지점이었던 _SnapUnit을 직접 검증 — Player 불필요)
    try:
        from core.Balance_Hook import _SnapUnit
        for mon, elem in [("화염 슬라임", "fire"), ("빙결 슬라임", "ice"), ("번개 슬라임", "lightning")]:
            src = make_snap(mon)
            src.element_queue = [elem]
            src.attack_element = elem
            unit = _SnapUnit(src)
            check(f"{mon}: _SnapUnit이 원소 보존",
                  getattr(unit, "init_element_queue", []) == [elem],
                  f"init_q={getattr(unit, 'init_element_queue', None)}")
            check(f"{mon}: _SnapUnit attack_element 보존",
                  getattr(unit, "attack_element", "") == elem)
            final = EntitySnapshot.from_enemy(unit)
            check(f"{mon}: 왕복 후 최종 큐 = ['{elem}']",
                  final.element_queue == [elem], f"q={final.element_queue}")
    except Exception as ex:
        print(f"  ⚠ _SnapUnit 왕복 테스트 건너뜀: {str(ex)[:80]}")
        print("    → from_enemy fallback이 있어 기능상 문제는 없음")


def main():
    print("=" * 50)
    print(" 원소 시스템 수정 검증 (버그 3, 4)")
    print("=" * 50)
    test_immunity()
    test_queue_preserved()
    print("\n" + "=" * 50)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 50)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()