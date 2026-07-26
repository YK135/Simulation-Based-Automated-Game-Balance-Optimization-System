# -*- coding: utf-8 -*-
"""
test_job_passives.py — 직업 패시브 개편 검증 (전사/마법사/탱커/도적)
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 test_job_passives.py

검증 항목:
  전사  : 공격 3회 회복 / 카운트 규칙 / step 중복 카운트 제거
  마법사: 융해·과부하 +5% / 파쇄 제외 / 반응 시 MP 8% / MP 30% 감소 제거
  탱커  : 물리→MP, 마법→HP 회복 / 데미지 0이면 미발동
  도적  : 주사위 배율 테이블 / 자연 크리 억제 / 반격 크리 허용 / 출혈 / 방무 삭제
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
import inspect
from random import seed

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2705 {name}")
    else:
        FAIL += 1
        print(f"  \u274c {name}  {detail}")


def mk(name, job="", hp=1000, mp=100, luc=10, arm=20):
    from ai.battle.Entity import EntitySnapshot
    return EntitySnapshot(
        name=name, hp=hp, maxhp=hp, mp=mp, maxmp=100,
        stg=50, arm=arm, sparm=15, sp=40, luc=luc, lv=5,
        job=job, enemy_type=name,
    )


# ═══════════════════════════════════════════════════
def test_warrior():
    print("\n[전사]")
    # 1. 회복량: passive_on_turn_start = maxhp 10%
    w = mk("전사", job="전사"); w.hp = 500
    msg = w.passive_on_turn_start()
    check("passive_on_turn_start: +10% (500→600)", w.hp == 600, f"hp={w.hp}")
    check("회복 메시지", "전사 패시브" in msg)

    # 2. step의 구 카운터(행동마다 증가) 제거 확인 — 소스 검사
    import ai.Battlesession as BS
    src = inspect.getsource(BS)
    check("Battlesession: 구 카운터(_warrior_action_count) 제거",
          "_warrior_action_count" not in src)
    check("Battlesession: 새 카운터(_warrior_attack_count) init",
          "_warrior_attack_count = 0" in src)

    # 3. Player_Actions의 카운트 규칙 — 공격형 타입만
    from ai.battle_session.Player_Actions import PlayerActionsMixin
    types = PlayerActionsMixin._ATTACK_SKILL_TYPES
    check("공격형 타입 = physical/magical/tank_attack/counter/multi_hit",
          set(types) == {"physical", "magical", "tank_attack", "counter", "multi_hit"})
    psrc = inspect.getsource(PlayerActionsMixin._count_warrior_attack)
    check("_count_warrior_attack: 3회마다 발동 (% 3)", "% 3" in psrc)

    # 4. 카운트 동작 (가짜 self)
    class Fake:
        _count_warrior_attack = PlayerActionsMixin._count_warrior_attack
    f = Fake(); f.player = mk("워리어", job="전사"); f.player.hp = 100
    msgs = []
    for i in range(3):
        f._count_warrior_attack(msgs)
    check("공격 3회 → 회복 발동 (100→200)", f.player.hp == 200, f"hp={f.player.hp}")
    check("공격 2회째까지는 미발동 카운터", f._warrior_attack_count == 3)
    # 비전사는 무시
    f2 = Fake(); f2.player = mk("법사", job="마법사"); f2.player.hp = 100
    for i in range(6):
        f2._count_warrior_attack([])
    check("비전사: 카운트/회복 없음", f2.player.hp == 100 and not hasattr(f2, "_warrior_attack_count"))


# ═══════════════════════════════════════════════════
def test_mage():
    print("\n[마법사]")
    from ai.battle.Elements import apply_element_and_react

    # 1. MP 30% 감소 제거
    m = mk("법사", job="마법사")
    check("mp_cost_multiplier == 1.0 (30% 감소 제거)", m.mp_cost_multiplier() == 1.0,
          f"mult={m.mp_cost_multiplier()}")
    w = mk("전사", job="전사")
    check("타 직업과 동일 비용", m.mp_cost_multiplier() == w.mp_cost_multiplier())

    # 2. 융해 +5% + MP 8%
    m2 = mk("법사", job="마법사", mp=50)
    t = mk("고블린"); t.element_queue = ["ice"]
    msgs = []
    dmg = apply_element_and_react(m2, t, "fire", 100, msgs)
    check("융해(melt): 155 (기본 150 +5%p)", dmg == 155, f"dmg={dmg}")
    check("반응 시 MP 8% 회복 (50→58)", m2.mp == 58, f"mp={m2.mp}")

    # 3. 과부하 +5%
    m3 = mk("법사", job="마법사", mp=50)
    t2 = mk("박쥐"); t2.element_queue = ["fire"]
    dmg2 = apply_element_and_react(m3, t2, "lightning", 100, [])
    check("과부하(overload): 135 (기본 130 +5%p)", dmg2 == 135, f"dmg={dmg2}")
    check("과부하 MP 회복", m3.mp == 58, f"mp={m3.mp}")

    # 4. 파쇄 제외
    m4 = mk("법사", job="마법사", mp=50)
    t3 = mk("유령"); t3.element_queue = ["ice"]
    dmg3 = apply_element_and_react(m4, t3, "physical", 100, [])
    check("파쇄(shatter): 119~120 (5% 미적용)", dmg3 in (119, 120), f"dmg={dmg3}")
    check("파쇄 시 MP 회복 없음", m4.mp == 50, f"mp={m4.mp}")

    # 5. 비마법사 반응은 기존 그대로
    n = mk("전사", job="전사", mp=50)
    t4 = mk("슬라임"); t4.element_queue = ["ice"]
    dmg4 = apply_element_and_react(n, t4, "fire", 100, [])
    check("비마법사 융해: 150 유지", dmg4 == 150, f"dmg={dmg4}")
    check("비마법사 MP 회복 없음", n.mp == 50)


# ═══════════════════════════════════════════════════
def test_tanker():
    print("\n[탱커]")
    t = mk("탱커", job="탱커", mp=50); t.hp = 500
    m1 = t.passive_on_hit_received("physical")
    check("물리 피격 → MP +10 (50→60)", t.mp == 60 and "MP" in m1, f"mp={t.mp}")
    m2 = t.passive_on_hit_received("magical")
    check("마법 피격 → HP +100 (500→600)", t.hp == 600 and "HP" in m2, f"hp={t.hp}")
    n = mk("도적", job="도적", mp=50)
    check("비탱커: 미발동", n.passive_on_hit_received("physical") == "" and n.mp == 50)


# ═══════════════════════════════════════════════════
def test_rogue():
    print("\n[도적]")
    from ai.battle.Damage import DamageCalc
    from ai.battle.Entity import StatusEffect
    from ai.battle_session.Player_Actions import PlayerActionsMixin

    # 1. 주사위 배율 테이블 (명세 대조)
    mult = PlayerActionsMixin._ROGUE_DICE_MULT
    check("주사위 배율 {1:0.75, 2:0.90, 3:1.0, 4:1.15, 5:1.25, 6:1.0(+크리)}",
          mult == {1: 0.75, 2: 0.90, 3: 1.00, 4: 1.15, 5: 1.25, 6: 1.00}, f"{mult}")

    # 2. 자연 크리 억제 (_suppress_crit)
    r = mk("도적이", job="도적", luc=80)  # 크리율 상한 40%
    g = mk("고블린")
    r._suppress_crit = True
    crits = 0
    for _ in range(300):
        r.has_attacked = True
        _, _, c = DamageCalc.physical(50, 80, 20, 5, attacker=r, defender=g)
        crits += c
    check("주사위 공격: 자연 크리 0회 (300번)", crits == 0, f"crits={crits}")

    # 3. 반격: 억제 해제 → 일반 luc 크리 허용
    r._suppress_crit = False
    crits2 = 0
    for _ in range(300):
        _, _, c = DamageCalc.physical(50, 80, 20, 5, attacker=r, defender=g)
        crits2 += c
    check("반격: 일반 크리 발생 (300번 중 다수)", crits2 > 50, f"crits={crits2}")

    # 4. 방무 삭제 — 실측 (크리/논크리 비율 = 순수 1.5x)
    import statistics, random as _rnd
    _rnd.seed(7)
    golem = mk("골렘", arm=200)
    cd, nd = [], []
    for _ in range(2000):
        r.has_attacked = True
        d, dodge, c = DamageCalc.physical(50, 80, 200, 5, attacker=r, defender=golem)
        if dodge:
            continue
        (cd if c else nd).append(d)
    ratio = statistics.mean(cd) / statistics.mean(nd)
    check("방무 삭제: 크리 배율 순수 1.5x (1.4~1.6)", 1.40 < ratio < 1.60, f"ratio={ratio:.3f}")

    # 5. 출혈: 3턴, 매턴 maxhp 4~7%
    tgt = mk("골렘2")
    tgt.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"))
    ticks = 0
    ok_range = True
    for _ in range(5):
        before = tgt.hp
        tgt.tick_status_effects()
        d = before - tgt.hp
        if d > 0:
            ticks += 1
            if not (40 <= d <= 70):
                ok_range = False
    check("출혈: 정확히 3턴 발동", ticks == 3, f"ticks={ticks}")
    check("출혈: 매턴 maxhp 4~7% 범위", ok_range)

    # 6. Damage.py에 구 방무 코드 없음 (소스 검사)
    import ai.battle.Damage as DMod
    dsrc = inspect.getsource(DMod)
    check("Damage.py: pen_ratio(방무 로직) 삭제", "pen_ratio" not in dsrc)

    # 7. Enemy_Actions 반격 훅 존재 (소스 검사)
    from ai.battle_session import Enemy_Actions as EA
    esrc = inspect.getsource(EA)
    check("Enemy_Actions: _rogue_counter 존재", "_rogue_counter" in esrc)
    check("반격: 회피 3지점 연결", esrc.count("self._rogue_counter(") >= 3,
          f"count={esrc.count('self._rogue_counter(')}")
    check("반격: ATB 획득 코드", "player_atb +=" in inspect.getsource(EA.EnemyActionsMixin._rogue_counter))


def main():
    print("=" * 52)
    print(" 직업 패시브 개편 검증 (전사/마법사/탱커/도적)")
    print("=" * 52)
    seed(20260703)
    test_warrior()
    test_mage()
    test_tanker()
    test_rogue()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()