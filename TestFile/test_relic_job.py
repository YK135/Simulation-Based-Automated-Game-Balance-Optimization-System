# -*- coding: utf-8 -*-
"""
test_relic_job.py — 유물 확장 2단계(직업 전용 12종) + 제시 규칙 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_relic_job.py

브리프 7장 「유물 확장」의 직업 전용 12종(전사·마법사·도적 각 4). 탱커는 생성
화면에서 잠겨 있어 전용 유물을 만들지 않는다(사용자 결정 2026-09-20).
설계 규칙 ①대로 전부 "이미 있는 기계의 상한·대가"만 건드리므로, 각 검사도
그 기계의 값이 실제로 달라지는지를 본다.

  1) 전사   무쇠 심장 · 굶주린 칼날 · 처형인의 각인 · 짐승의 피
  2) 마법사 공명의 수정 · 마나 회로 · 얼어붙은 시간 · 화염의 잔재
  3) 도적   납으로 만든 주사위 · 사혈 단검 · 그림자 걸음 · 표적 안내서
  4) 제시 규칙 — 3장 중 1장은 내 직업 전용, 남의 직업 유물은 안 나온다, 상점은 공용만
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


def ent(relics=None, **kw):
    from ai.battle import EntitySnapshot
    base = dict(name="E", hp=100, maxhp=100, mp=50, maxmp=50,
                stg=30, arm=10, sparm=10, sp=30, luc=10, lv=5, spd=10)
    base.update(kw)
    return EntitySnapshot(relics=list(relics or []), **base)


def session(player_snap, enemy_snap):
    """실전과 같은 BattleSession 하나 (enemy_origins 없이 스냅샷만)."""
    from ai.Battlesession import BattleSession
    with contextlib.redirect_stdout(_buf):
        return BattleSession(player_snap, enemies=[enemy_snap], items=[])


# ═════════════════════════════════════════════
def test_warrior():
    print("\n[1] 전사 전용 4종")
    from ai.battle.Relics import (
        RELIC_IRON_HEART, RELIC_HUNGRY_BLADE, RELIC_EXECUTIONER_MARK, RELIC_BEAST_BLOOD,
        IRON_HEART_SHIELD_RATIO, HUNGRY_BLADE_KILL_HEAL, EXECUTIONER_BONUS,
        relic_execute_mult, relic_lifesteal_hit_cap, relic_maxhp_cost_mult,
    )
    from ai.battle.Damage import LIFESTEAL_HIT_CAP_RATIO

    # ── 무쇠 심장: 전투 시작 실드, 전투마다 다시 ──
    bs = session(ent([RELIC_IRON_HEART], maxhp=1000, hp=1000), ent(name="적"))
    check("무쇠 심장 — 전투 시작 실드 maxHP 12%",
          abs(bs.player.shield - 1000 * IRON_HEART_SHIELD_RATIO) < 0.01, f"{bs.player.shield}")
    check("무쇠 심장 — 시작 메시지", any("무쇠 심장" in m for m in bs.relic_start_messages),
          f"{bs.relic_start_messages}")
    plain = session(ent(maxhp=1000, hp=1000), ent(name="적"))
    check("유물 없으면 실드 0", plain.player.shield == 0 and plain.relic_start_messages == [])

    # ── 굶주린 칼날: 획득 시 최대 HP 대가 + 처치 시 회복 ──
    check("굶주린 칼날 — 획득 배율 0.9", abs(relic_maxhp_cost_mult(RELIC_HUNGRY_BLADE) - 0.9) < 1e-9)
    check("다른 유물은 배율 1.0", relic_maxhp_cost_mult(RELIC_IRON_HEART) == 1.0)

    from _helpers import make_session_dict
    from app.Shared import _grant_relic
    gs = make_session_dict()
    gs["player"].maxhp, gs["player"].hp = 1000, 1000
    _grant_relic(gs, RELIC_HUNGRY_BLADE)
    check("굶주린 칼날 — 획득 시 최대 HP 1000 → 900",
          gs["player"].maxhp == 900 and gs["player"].hp == 900,
          f"{gs['player'].maxhp}/{gs['player'].hp}")

    bs = session(ent([RELIC_HUNGRY_BLADE], maxhp=1000, hp=500), ent(name="적", hp=1, maxhp=100))
    msgs = []
    bs._player_hit(bs.enemies[0], 50, msgs)
    check("굶주린 칼날 — 처치 시 maxHP 8% 회복",
          abs(bs.player.hp - (500 + 1000 * HUNGRY_BLADE_KILL_HEAL)) < 1.0, f"{bs.player.hp}")
    check("굶주린 칼날 — 메시지", any("굶주린 칼날" in m for m in msgs), f"{msgs}")

    bs2 = session(ent([RELIC_HUNGRY_BLADE], maxhp=1000, hp=500), ent(name="적", hp=900, maxhp=1000))
    bs2._player_hit(bs2.enemies[0], 50, [])
    check("안 죽으면 회복 없음", bs2.player.hp == 500, f"{bs2.player.hp}")

    # ── 처형인의 각인 ──
    holder, low, high = ent([RELIC_EXECUTIONER_MARK]), ent(hp=20, maxhp=100), ent(hp=30, maxhp=100)
    check(f"처형인의 각인 — HP 25% 이하 ×{1 + EXECUTIONER_BONUS}",
          abs(relic_execute_mult(holder, low) - (1 + EXECUTIONER_BONUS)) < 1e-9)
    check("HP 25% 초과면 1.0", relic_execute_mult(holder, high) == 1.0)
    check("유물 없으면 1.0", relic_execute_mult(ent(), low) == 1.0)

    # ── 짐승의 피 ──
    check("짐승의 피 — 흡혈 상한 4% → 6%",
          relic_lifesteal_hit_cap(ent([RELIC_BEAST_BLOOD]), LIFESTEAL_HIT_CAP_RATIO) == 0.06
          and relic_lifesteal_hit_cap(ent(), LIFESTEAL_HIT_CAP_RATIO) == LIFESTEAL_HIT_CAP_RATIO)


def test_damage_hooks():
    print("\n[1-b] 처형인의 각인 · 표적 안내서가 실제 피해 계산에 걸리는가")
    import ai.battle.Damage as D
    from ai.battle.Relics import (RELIC_EXECUTIONER_MARK, RELIC_TARGET_MANUAL,
                                  EXECUTIONER_BONUS)

    old_u, old_r = D.uniform, D.randint
    D.uniform = lambda a, b: 1.0        # 난수 고정
    D.randint = lambda a, b: b         # 회피 X · 자연 크리 X (100 > 상한)
    try:
        dead = ent(hp=20, maxhp=100)
        base, _, _ = D.DamageCalc.physical(30, 10, 10, 10, defender=dead, attacker=ent())
        mark, _, _ = D.DamageCalc.physical(30, 10, 10, 10, defender=dead,
                                           attacker=ent([RELIC_EXECUTIONER_MARK]))
        # 절삭은 마지막에 한 번뿐이라 int(base)×1.2와 1~2 다를 수 있다 — 비율로 본다
        check("처형인의 각인 — 실제 피해 +20%",
              mark > base and abs(mark / base - (1 + EXECUTIONER_BONUS)) < 0.03,
              f"{base} → {mark} (×{mark / base:.3f})")

        tgt = ent(hp=100, maxhp=100)
        armed = ent([RELIC_TARGET_MANUAL]); armed.relic_crit_armed = True
        _, _, crit1 = D.DamageCalc.physical(30, 10, 10, 10, defender=tgt, attacker=armed)
        _, _, crit2 = D.DamageCalc.physical(30, 10, 10, 10, defender=tgt, attacker=armed)
        check("표적 안내서 — 장전된 공격만 확정 치명타", crit1 and not crit2, f"{crit1}/{crit2}")
        check("소비 후 '이번 전투 사용' 표시", armed.relic_crit_used and not armed.relic_crit_armed)

        # 주사위 억제(도적)보다 우선한다
        armed2 = ent([RELIC_TARGET_MANUAL]); armed2.relic_crit_armed = True
        armed2._suppress_crit = True
        _, _, crit3 = D.DamageCalc.physical(30, 10, 10, 10, defender=tgt, attacker=armed2)
        check("주사위 억제 중에도 확정 치명타", crit3)
    finally:
        D.uniform, D.randint = old_u, old_r


def test_mage():
    print("\n[2] 마법사 전용 4종")
    from ai.battle import Debuff, StatusEffect
    from ai.battle.Elements import (mage_resonance_on_cast, mage_resonance_mult,
                                    RESONANCE_MAX_STACK, RESONANCE_STEP)
    from ai.battle.Relics import (RELIC_RESONANCE_CRYSTAL, RELIC_MANA_CIRCUIT,
                                  RELIC_FROZEN_TIME, RELIC_EMBER_REMNANT,
                                  RESONANCE_CRYSTAL_MAX_STACK, MANA_CIRCUIT_MP,
                                  relic_mana_circuit)

    def stack_up(relics, n):
        m = ent(relics, job="마법사")
        for _ in range(n):
            mage_resonance_on_cast(m, "fire", "magical")
        return m

    plain = stack_up([], 5)
    crys  = stack_up([RELIC_RESONANCE_CRYSTAL], 5)
    check(f"공명 기본 상한 {RESONANCE_MAX_STACK}", plain.resonance_stack == RESONANCE_MAX_STACK,
          f"{plain.resonance_stack}")
    check(f"공명의 수정 — 상한 {RESONANCE_CRYSTAL_MAX_STACK}",
          crys.resonance_stack == RESONANCE_CRYSTAL_MAX_STACK, f"{crys.resonance_stack}")
    check("4단계 배율 1.30",
          abs(mage_resonance_mult(crys, "fire") - (1 + RESONANCE_STEP * 3)) < 1e-9,
          f"{mage_resonance_mult(crys, 'fire')}")

    m = ent([RELIC_MANA_CIRCUIT], mp=10, maxmp=50)
    check(f"마나 회로 — MP +{MANA_CIRCUIT_MP}",
          relic_mana_circuit(m) == MANA_CIRCUIT_MP and m.mp == 10 + MANA_CIRCUIT_MP, f"{m.mp}")
    full = ent([RELIC_MANA_CIRCUIT], mp=50, maxmp=50)
    check("MP가 가득 차면 0", relic_mana_circuit(full) == 0)
    check("유물 없으면 0", relic_mana_circuit(ent(mp=10, maxmp=50)) == 0)

    tgt = ent()
    tgt.apply_debuff(Debuff(stat="spd", amount=0.2, turns=2, name="둔화"),
                     caster=ent([RELIC_FROZEN_TIME]))
    check("얼어붙은 시간 — 둔화 2턴 → 3턴", tgt.debuffs[0].turns == 3, f"{tgt.debuffs[0].turns}")
    tgt2 = ent()
    tgt2.apply_debuff(Debuff(stat="stg", amount=0.2, turns=2, name="약화"),
                      caster=ent([RELIC_FROZEN_TIME]))
    check("둔화가 아닌 디버프는 그대로", tgt2.debuffs[0].turns == 2, f"{tgt2.debuffs[0].turns}")

    burn = ent()
    eff = burn.apply_status_effect(StatusEffect(effect_type="ignite", turns=3, name="fire"),
                                   caster=ent([RELIC_EMBER_REMNANT]))
    check("화염의 잔재 — 점화 3틱 → 4틱", eff.turns == 4, f"{eff.turns}")
    frost = ent()
    eff2 = frost.apply_status_effect(StatusEffect(effect_type="frostbite", turns=3, name="ice"),
                                     caster=ent([RELIC_EMBER_REMNANT]))
    check("점화가 아닌 상태이상은 그대로", eff2.turns == 3, f"{eff2.turns}")


def test_rogue():
    print("\n[3] 도적 전용 4종")
    from ai.battle import StatusEffect, BLEED_STACK_MAX
    from ai.battle.Relics import (RELIC_LOADED_DICE, RELIC_BLEED_DAGGER, RELIC_SHADOW_STEP,
                                  RELIC_TARGET_MANUAL, LOADED_DICE_FLOOR, BLEED_DAGGER_STACK_MAX,
                                  SHADOW_STEP_DODGE_ATB, relic_dice_roll, relic_dodge_atb,
                                  relic_arm_kill_crit)

    dicer = ent([RELIC_LOADED_DICE])
    check(f"납으로 만든 주사위 — 1 → {LOADED_DICE_FLOOR}",
          relic_dice_roll(dicer, 1) == LOADED_DICE_FLOOR)
    check("2~6은 그대로", all(relic_dice_roll(dicer, d) == d for d in range(2, 7)))
    check("유물 없으면 1도 그대로", relic_dice_roll(ent(), 1) == 1)

    def bleed_to(relics, n):
        t = ent()
        eff = None
        for _ in range(n):
            eff = t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"),
                                        caster=ent(relics))
        return eff.stacks
    check(f"출혈 기본 상한 {BLEED_STACK_MAX}", bleed_to([], 6) == BLEED_STACK_MAX)
    check(f"사혈 단검 — 상한 {BLEED_DAGGER_STACK_MAX}",
          bleed_to([RELIC_BLEED_DAGGER], 6) == BLEED_DAGGER_STACK_MAX)

    check(f"그림자 걸음 — ATB {int(SHADOW_STEP_DODGE_ATB)}",
          relic_dodge_atb(ent([RELIC_SHADOW_STEP])) == SHADOW_STEP_DODGE_ATB
          and relic_dodge_atb(ent()) == 0.0)

    bs = session(ent([RELIC_SHADOW_STEP], job="도적"), ent(name="적"))
    bs.player_atb = 0.0
    msgs = []
    bs._relic_on_dodge(msgs)
    check("회피 훅이 세션 ATB를 올린다", bs.player_atb == SHADOW_STEP_DODGE_ATB, f"{bs.player_atb}")

    r = ent([RELIC_TARGET_MANUAL])
    check("표적 안내서 — 처치로 장전", relic_arm_kill_crit(r) and r.relic_crit_armed)
    check("이미 장전돼 있으면 중복 장전 안 함", not relic_arm_kill_crit(r))
    r.relic_crit_armed, r.relic_crit_used = False, True
    check("전투당 1회 — 다 쓰면 다시 장전 안 됨", not relic_arm_kill_crit(r))


def test_offer_rules():
    print("\n[4] 제시 규칙 — 3장 중 1장은 내 직업")
    import random
    from game.Relics import relic_choices, shop_relic_items, RELIC_META, RELIC_OFFER_COUNT
    from ai.battle.Relics import COMMON_RELIC_IDS, JOB_RELIC_IDS, RELIC_IDS, relic_job_of

    check("총 20종 (공용 8 + 직업 4×3)", len(RELIC_META) == 20 == len(RELIC_IDS), f"{len(RELIC_META)}")
    check("탱커 전용은 없다", "탱커" not in JOB_RELIC_IDS)

    for job in ("전사", "마법사", "도적"):
        random.seed(7)
        ok_own = ok_other = True
        for _ in range(40):
            picks = relic_choices([], job)
            if len(picks) != RELIC_OFFER_COUNT:
                ok_own = False; break
            mine = [r for r in picks if relic_job_of(r) == job]
            if len(mine) != 1:
                ok_own = False; break
            if any(relic_job_of(r) not in ("", job) for r in picks):
                ok_other = False; break
        check(f"{job} — 40회 모두 3장 중 정확히 1장이 직업 전용", ok_own)
        check(f"{job} — 남의 직업 유물은 안 나온다", ok_other)

    # 직업 유물을 다 가지면 공용으로만 채운다
    random.seed(11)
    picks = relic_choices(list(JOB_RELIC_IDS["도적"]), "도적")
    check("직업 유물 소진 → 공용 3장", len(picks) == 3 and all(relic_job_of(r) == "" for r in picks),
          f"{picks}")

    # 공용을 다 가지면 직업 전용으로 채운다
    random.seed(13)
    picks = relic_choices(list(COMMON_RELIC_IDS), "전사")
    check("공용 소진 → 직업 전용 3장",
          len(picks) == 3 and all(relic_job_of(r) == "전사" for r in picks), f"{picks}")

    check("전부 가지면 제시 없음", relic_choices(list(RELIC_IDS), "전사") == [])

    rows = shop_relic_items([], "도적")
    check("상점은 공용 8종만", len(rows) == len(COMMON_RELIC_IDS)
          and all(relic_job_of(r["id"]) == "" for r in rows), f"{[r['id'] for r in rows]}")


def main():
    print("=" * 52)
    print(" 유물 확장 2단계 — 직업 전용 12종 + 제시 규칙")
    print("=" * 52)
    test_warrior()
    test_damage_hooks()
    test_mage()
    test_rogue()
    test_offer_rules()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    try:
        os.unlink(_db)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


main()
