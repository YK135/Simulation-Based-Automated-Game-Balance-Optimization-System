# -*- coding: utf-8 -*-
"""
test_debuff_resist.py — 보스 디버프 저항 회귀 테스트 (밸런스 5차)
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_debuff_resist.py

`Unit.debuff_resist`는 중간 보스 0.30 · 최종 보스 0.50으로 선언돼 있었지만
5차 전까지 어디서도 읽지 않는 죽은 필드였다(EntitySnapshot.from_enemy가
옮기지도 않았다). 5차에서 실제로 동작하게 만들면서 고정하는 계약:

  1) "남이" 거는 디버프·상태이상만 저항한다 — caster가 None이거나 자기 자신이면
     저항하지 않는다(서리 결계·격노·그로기처럼 자기에게 거는 디버프가 실제로 있다)
  2) 저항하면 apply_debuff는 False, apply_status_effect는 None을 돌려준다
  3) 호출부가 그 결과를 읽어 "저항했다" 메시지를 낸다 — 안 걸렸는데
     "방어력 감소!"라고 찍던 거짓 메시지가 없어야 한다
  4) 기본값 0.0 — 일반 몬스터·플레이어는 이 분기를 타도 아무 일이 없다
  5) 실제 보스 수치: 최종 0.25 / 중간 0.0 (선언값을 그대로 켜면 밸런스가
     나빠진다는 실측 때문 — BALANCE_PATCH_5.md 2장)
"""
import sys, os, io, random, contextlib, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.battle import EntitySnapshot, Debuff, StatusEffect        # noqa: E402
from ai.battle.Elements import apply_element_and_react            # noqa: E402
from game.Enemy_Class import Make_FinalBoss, Make_MidBoss, Make_Goblin  # noqa: E402

PASS = FAIL = 0
_buf = io.StringIO()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}  {detail}")


def ent(resist=0.0, **kw):
    base = dict(name="E", hp=1000, maxhp=1000, mp=100, maxmp=100,
                stg=30, arm=10, sparm=10, sp=30, luc=10, lv=20, spd=10)
    base.update(kw)
    return EntitySnapshot(debuff_resist=resist, **base)


# ─────────────────────────────────────────────
def test_who_resists():
    print("\n[1] 누가 거는 것을 저항하는가")
    random.seed(7)

    # caster를 안 넘기면 저항하지 않는다 — 서리 결계·격노·그로기 경로
    boss = ent(resist=1.0)
    landed = [boss.apply_debuff(Debuff(stat="stg", amount=0.1, turns=2, name="x"))
              for _ in range(30)]
    check("caster=None이면 저항 안 함 (자기·환경 디버프 보호)", all(landed))

    # 자기 자신이 거는 것도 저항하지 않는다
    boss2 = ent(resist=1.0)
    check("caster=self여도 저항 안 함",
          boss2.apply_debuff(Debuff(stat="arm", amount=0.1, turns=2, name="y"), caster=boss2))

    # 남이 걸면 저항한다
    boss3, player = ent(resist=1.0), ent()
    check("저항 1.0이면 남이 거는 건 전부 막는다",
          not boss3.apply_debuff(Debuff(stat="spd", amount=0.1, turns=2, name="z"), caster=player))

    # 기본값 0 — 일반 몬스터는 기존과 동일
    mob = ent()
    check("저항 0(일반 몬스터)이면 그대로 걸린다",
          mob.apply_debuff(Debuff(stat="stg", amount=0.1, turns=2, name="w"), caster=player))


def test_probability():
    print("\n[2] 확률대로 막는가")
    player = ent()
    for r in (0.25, 0.50):
        random.seed(20260921)
        blocked = 0
        for _ in range(4000):
            t = ent(resist=r)
            if not t.apply_debuff(Debuff(stat="stg", amount=0.1, turns=2, name="x"), caster=player):
                blocked += 1
        rate = blocked / 4000
        check(f"저항 {r} → 차단율 {rate:.3f} (±0.03)", abs(rate - r) < 0.03, f"{rate}")


def test_return_values():
    print("\n[3] 반환값 계약")
    player = ent()
    t = ent(resist=1.0)
    eff = t.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"), caster=player)
    check("저항하면 apply_status_effect가 None", eff is None, f"{eff}")
    check("상태이상 목록도 비어 있다", not t.status_effects)

    t2 = ent()
    eff2 = t2.apply_status_effect(StatusEffect(effect_type="bleed", turns=3, name="출혈"), caster=player)
    check("안 막으면 효과 객체를 그대로 돌려준다", eff2 is not None and eff2.stacks == 1)

    t3 = ent(resist=1.0)
    check("저항하면 apply_debuff가 False",
          t3.apply_debuff(Debuff(stat="stg", amount=0.1, turns=2, name="x"), caster=player) is False)
    check("디버프 목록도 비어 있다", not t3.debuffs)


def test_messages():
    print("\n[4] 저항 메시지 — 안 걸렸는데 걸렸다고 하지 않는다")
    from ai.battle_session.Player_Actions import PlayerActionsMixin
    from ai.battle.Skills import maybe_hit_bleed

    class _S(PlayerActionsMixin):
        def __init__(self, p):
            self.player = p

    player = ent(job="도적")
    s = _S(player)

    tgt = ent(resist=1.0)
    msgs = []
    stacks = s._apply_bleed(tgt, msgs)
    check("출혈 저항 → 스택 0 + 저항 메시지",
          stacks == 0 and any("저항" in m for m in msgs), f"{stacks} {msgs}")

    tgt2 = ent()
    msgs2 = []
    st2 = s._apply_bleed(tgt2, msgs2)
    check("안 막으면 기존 출혈 메시지 그대로",
          st2 == 1 and any("출혈!" in m for m in msgs2), f"{st2} {msgs2}")

    # 칼날 폭풍 — 저항하면 "걸었다"가 아니다
    random.seed(1)
    meta = {"hit_bleed_chance": 1.0}
    check("maybe_hit_bleed: 저항하면 False",
          maybe_hit_bleed(meta, ent(resist=1.0), attacker=player) is False)
    check("maybe_hit_bleed: 안 막으면 True",
          maybe_hit_bleed(meta, ent(), attacker=player) is True)

    # 원소 상태이상 — 저항 메시지
    random.seed(3)
    caster = ent(job="마법사", sp=200)
    burned = ent(resist=1.0)
    m3 = []
    for _ in range(12):
        apply_element_and_react(caster, burned, "fire", 100, m3)
    check("원소 상태이상 저항 메시지", any("저항" in x for x in m3), f"{m3[:4]}")
    check("저항 대상에 상태이상이 안 남는다", not burned.status_effects)


def test_snapshot_and_bosses():
    print("\n[5] 스냅샷 전달 + 실제 보스 수치")
    with contextlib.redirect_stdout(_buf):
        fb = Make_FinalBoss(player_lv=25)
        mb = Make_MidBoss(player_lv=15)
        gob = Make_Goblin(10, "중")

    check("최종 보스 debuff_resist 0.25", abs(fb.debuff_resist - 0.25) < 1e-9, f"{fb.debuff_resist}")
    check("중간 보스 debuff_resist 0.0 (되살리려면 Lv8 벽 결정부터)",
          abs(mb.debuff_resist - 0.0) < 1e-9, f"{mb.debuff_resist}")
    check("일반 몬스터는 0", abs(getattr(gob, "debuff_resist", 0.0)) < 1e-9)

    snap = EntitySnapshot.from_enemy(fb)
    check("from_enemy가 debuff_resist를 옮긴다", abs(snap.debuff_resist - 0.25) < 1e-9,
          f"{snap.debuff_resist}")
    check("일반 몬스터 스냅샷은 0",
          abs(EntitySnapshot.from_enemy(gob).debuff_resist) < 1e-9)


def test_final_boss_stats():
    print("\n[6] 최종 보스 6차 수치 (실제 도착 레벨 기준)")
    with contextlib.redirect_stdout(_buf):
        b = Make_FinalBoss(player_lv=25)
    check("HP 2484 / STG 46 / ARM 37 / SPARM 42 / SP 45",
          (b.hp, b.stg, b.arm, b.sparm, b.sp) == (2484, 46, 37, 42, 45),
          f"{(b.hp, b.stg, b.arm, b.sparm, b.sp)}")
    check("SPD 34 · LUC 40 · MP 220은 그대로",
          (b.spd, b.luc, b.mp) == (34, 40, 220), f"{(b.spd, b.luc, b.mp)}")
    with contextlib.redirect_stdout(_buf):
        m = Make_MidBoss(player_lv=15)
    check("중간 보스 수치는 불변 (HP 1200 / STG 36 / ARM 27)",
          (m.hp, m.stg, m.arm) == (1200, 36, 27), f"{(m.hp, m.stg, m.arm)}")


def main():
    print("=" * 52)
    print(" 보스 디버프 저항 + 최종 보스 6차 수치")
    print("=" * 52)
    test_who_resists()
    test_probability()
    test_return_values()
    test_messages()
    test_snapshot_and_bosses()
    test_final_boss_stats()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    try:
        os.unlink(_db)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


main()
