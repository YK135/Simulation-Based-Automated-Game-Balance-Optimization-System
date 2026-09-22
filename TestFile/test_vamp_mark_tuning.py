# -*- coding: utf-8 -*-
"""
test_vamp_mark_tuning.py — 흡혈 버프·약점 표식 지속 재조정 회귀 테스트 (후속 ①)
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_vamp_mark_tuning.py

「피의 격노」·「피의 맹세」·「약점 표식」은 문서 수치(지속 3턴)에서 수지가 안 맞았다.
3턴 버프는 시전 행동에서 1턴이 줄어 실제로 덮는 행동이 2회뿐이고, 2행동마다 다시
걸어야 해서 전투 하나에 3~5회를 시전하게 된다 — 실측에서 묶인 비용은 HP·MP가 아니라
**행동**이었다(TestFile/vamp_mark_measure.py). 그래서 비용·비율·상한은 그대로 두고
지속만 8턴으로 늘렸다. 이 파일이 고정하는 계약:

  1) 세 스킬의 지속은 8턴이다 (비율 25%/40%/8%와 비용 15%/20%/MP 11은 불변)
  2) 버프는 시전 행동에서 1턴이 줄어 (turns − 1)회 행동을 덮는다 — 이 규칙 자체는
     바꾸지 않았다(바꾸면 강화·약화 등 기존 3턴 버프가 전부 같이 움직인다)
  3) 「피의 맹세」의 만료 지불은 **전투가 버프보다 먼저 끝나도** 정산된다
     (지속을 8턴으로 늘리면 짧은 전투에서 대가를 안 내고 끝나는 구멍이 생긴다)
  4) 정산은 전투가 끝나는 모든 분기에서 일어나고, 같은 대가를 두 번 받지 않는다
  5) 쓰러진 뒤에는 정산하지 않는다 (시체에서 더 받지 않는다)
  6) ATB 이월(_close_out_battle로 합친 기존 동작)이 그대로 남아 있다
  7) 측정용 AI의 흡혈 버프 손익 판단은 "적이 곧 죽는 짧은 전투"를 음수로 본다
"""
import sys, os, io, random, contextlib, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fd, _db = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db

from ai.battle import EntitySnapshot, SKILL_META, Buff, Debuff      # noqa: E402
from ai.Battlesession import BattleSession                          # noqa: E402
from ai.Auto_AI import PlayerAI                                     # noqa: E402
from game.Enemy_Class import Make_Goblin, Make_FinalBoss            # noqa: E402
from game.Player_Class import create_player_by_job                  # noqa: E402
from game.Lv import LV_, Allocate_Stat_Points, auto_resolve_skill_choices  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name}  {detail}")


def ent(**kw):
    base = dict(name="P", hp=1000, maxhp=1000, mp=100, maxmp=100,
                stg=40, arm=15, sparm=15, sp=30, luc=10, lv=20, spd=20)
    base.update(kw)
    return EntitySnapshot(**base)


def build(job, level):
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("측정", job)
        lv = LV_(p); guard = 0
        while p.lv < level and guard < 300:
            lv.Get_exp(p, reward_exp=p.maxexp); guard += 1
        if getattr(p, "pending_points", 0) > 0:
            Allocate_Stat_Points(p, {"stg": p.pending_points})
        auto_resolve_skill_choices(p, "new")
    return p


# ─────────────────────────────────────────────
def test_numbers():
    print("\n[1] 확정 수치 — 지속만 바꿨고 비용·비율은 그대로")
    rage, oath, mark = SKILL_META["피의 격노"], SKILL_META["피의 맹세"], SKILL_META["약점 표식"]

    check("피의 격노 지속 8턴", rage["buff_turns"] == 8, rage["buff_turns"])
    check("피의 맹세 지속 8턴", oath["buff_turns"] == 8, oath["buff_turns"])
    check("약점 표식 지속 8턴", mark["debuff_turns"] == (8, 8), mark["debuff_turns"])

    check("피의 격노 흡혈 25% 불변", rage["buff_amount"] == 0.25, rage["buff_amount"])
    check("피의 격노 HP 지불 15% 불변", rage["hp_cost_ratio"] == 0.15, rage["hp_cost_ratio"])
    check("피의 격노 MP 0 불변", rage["mp"] == 0, rage["mp"])
    check("피의 맹세 흡혈 40% 불변", oath["buff_amount"] == 0.40, oath["buff_amount"])
    check("피의 맹세 만료 지불 20% 불변", oath["expire_hp_cost"] == 0.20, oath["expire_hp_cost"])
    check("약점 표식 받는 피해 +8% 불변", mark["debuff_amount"] == (0.08, 0.08), mark["debuff_amount"])
    check("약점 표식 MP 11 불변", mark["mp"] == 11, mark["mp"])

    # 지속 규칙 자체는 안 건드렸다 — 기존 3턴 버프가 같이 움직이면 안 된다
    check("강화1은 3턴 그대로", SKILL_META["강화1"]["buff_turns"] == 3)
    check("약화1은 (3,4) 그대로", SKILL_META["약화1"]["debuff_turns"] == (3, 4))


def test_tick_rule():
    print("\n[2] 시전 행동에서 1턴 줄어 (turns − 1)회를 덮는다")
    p = ent()
    p.apply_buff(Buff(stat="lifesteal", amount=0.25, turns=8, name="피의 격노"))
    p.tick_buffs()                                    # 시전 행동의 틱
    check("8턴으로 걸면 시전 직후 7턴", p.buffs[0].turns == 7, p.buffs[0].turns)

    covered = 0
    while any(b.stat == "lifesteal" for b in p.buffs):
        covered += 1                                  # 흡혈이 살아 있는 행동
        p.tick_buffs()
    check("덮는 행동 7회 (turns − 1)", covered == 7, covered)


def test_settle_costs():
    print("\n[3] 만료 전에 전투가 끝나면 대가를 정산한다")
    p = ent(hp=1000)
    p.apply_buff(Buff(stat="lifesteal_oath", amount=0.40, turns=8,
                      name="피의 맹세", expire_hp_cost=0.20))
    msgs = p.settle_buff_costs()
    check("현재 HP 20%를 지불", abs(p.hp - 800) < 1e-6, p.hp)
    check("정산 메시지가 나온다", any("피의 맹세" in m for m in msgs), msgs)
    check("버프 목록이 비워진다", p.buffs == [], p.buffs)
    check("두 번 정산해도 더 받지 않는다",
          (p.settle_buff_costs() == [] and abs(p.hp - 800) < 1e-6), p.hp)

    # 대가 없는 버프는 그냥 사라진다
    q = ent(hp=500)
    q.apply_buff(Buff(stat="stg", amount=0.15, turns=3, name="강화1"))
    q.settle_buff_costs()
    check("대가 없는 버프는 HP를 안 깎는다", abs(q.hp - 500) < 1e-6, q.hp)

    # 쓰러진 뒤에는 받지 않는다
    d = ent(hp=0)
    d.apply_buff(Buff(stat="lifesteal_oath", amount=0.40, turns=8,
                      name="피의 맹세", expire_hp_cost=0.20))
    check("hp ≤ 0이면 정산하지 않는다", d.settle_buff_costs() == [] and d.hp == 0, d.hp)

    # 정상 만료는 여전히 tick_buffs가 받는다 (이중 청구 없음)
    r = ent(hp=1000)
    r.apply_buff(Buff(stat="lifesteal_oath", amount=0.40, turns=2,
                      name="피의 맹세", expire_hp_cost=0.20))
    r.tick_buffs()                                    # 2 → 1
    paid = r.tick_buffs()                             # 만료 + 지불
    check("정상 만료는 tick_buffs가 지불", abs(r.hp - 800) < 1e-6 and paid, r.hp)
    check("만료 후 정산은 아무것도 안 받는다",
          r.settle_buff_costs() == [] and abs(r.hp - 800) < 1e-6, r.hp)


def _run_battle(player_snap, enemy_unit, actions, seed=11):
    """주어진 행동 순서대로 전투를 돌린다 — 적 차례는 auto."""
    random.seed(seed)
    bs = BattleSession(player_snap, enemy=EntitySnapshot.from_enemy(enemy_unit),
                       items=[], enemy_origins=[enemy_unit])
    bs.battle_meta = {"source": "test", "battle_type": "1v1", "chapter": 1}
    it = iter(actions)
    steps = 0
    while not bs.done and steps < 200:
        steps += 1
        na, _ = bs._peek_next_actor()
        if na == "player":
            bs.step(next(it, "attack"))
        else:
            bs.step("auto")
    return bs


def test_session_settles_on_victory():
    print("\n[4] 세션 — 승리로 끝나도 맹세의 대가가 정산된다")
    p = build("전사", 25)
    snap = EntitySnapshot.from_player(p)
    snap.hp, snap.mp = snap.maxhp, snap.maxmp
    check("Lv25 전사가 피의 맹세를 배운다", "피의 맹세" in snap.learned_skills)

    # 약한 적 — 맹세(8턴)가 만료되기 전에 전투가 끝난다
    goblin = Make_Goblin(3, "하")
    bs = _run_battle(snap, goblin, ["skill:피의 맹세"] + ["attack"] * 30)
    check("전투가 승리로 끝났다", bs.done and bs.winner == "player", bs.winner)
    check("전투가 8행동보다 짧았다 (구멍이 생기는 조건)", bs.turn < 8, bs.turn)
    paid = bs.player.maxhp - bs.player.hp
    check("맹세 대가가 지불됐다 (HP가 줄어 있다)", paid > 0, paid)
    check("정산 후 버프가 남아 있지 않다",
          not any(b.stat == "lifesteal_oath" for b in bs.player.buffs), bs.player.buffs)


def test_session_carries_atb():
    print("\n[5] 세션 — _close_out_battle로 합친 ATB 이월이 그대로다")
    p = build("전사", 20)
    snap = EntitySnapshot.from_player(p)
    snap.hp, snap.mp = snap.maxhp, snap.maxmp
    p.atb_remainder = 0.0
    goblin = Make_Goblin(3, "하")
    random.seed(5)
    bs = BattleSession(snap, enemy=EntitySnapshot.from_enemy(goblin), items=[],
                       enemy_origins=[goblin], player_original=p)
    steps = 0
    while not bs.done and steps < 200:
        steps += 1
        na, _ = bs._peek_next_actor()
        bs.step("attack" if na == "player" else "auto")
    check("승리로 끝났다", bs.winner == "player", bs.winner)
    check("원본 Player에 잔여 ATB가 기록됐다",
          getattr(p, "atb_remainder", None) == bs.player.atb_remainder,
          (getattr(p, "atb_remainder", None), bs.player.atb_remainder))
    check("잔여 ATB는 음수가 아니다", bs.player.atb_remainder >= 0.0, bs.player.atb_remainder)


def test_mark_applies():
    print("\n[6] 약점 표식 — 8턴 취약, 받는 피해 +8%")
    target = ent(name="E")
    caster = ent(name="P")
    meta = SKILL_META["약점 표식"]
    target.apply_debuff(Debuff(stat=meta["debuff_stat"], amount=meta["debuff_amount"][0],
                               turns=meta["debuff_turns"][0], name="약점 표식"), caster=caster)
    vul = [d for d in target.debuffs if d.stat == "vulnerable"]
    check("취약 디버프가 걸린다", len(vul) == 1, target.debuffs)
    check("지속 8턴", vul and vul[0].turns == 8, vul[0].turns if vul else None)
    check("받는 피해 배율 1.08", abs(target.damage_taken_mult() - 1.08) < 1e-9,
          target.damage_taken_mult())
    covered = 0
    while any(d.stat == "vulnerable" for d in target.debuffs):
        covered += 1
        target.tick_debuffs()
    check("대상 행동 8회를 덮는다 (디버프는 대상 행동으로 줄어든다)", covered == 8, covered)


def test_ai_gate_horizon():
    print("\n[7] 측정용 AI — 곧 끝나는 전투에는 흡혈 버프를 걸지 않는다")
    p = build("전사", 20)
    atk = EntitySnapshot.from_player(p)
    atk.hp, atk.mp = atk.maxhp, atk.maxmp

    boss = EntitySnapshot.from_enemy(Make_FinalBoss(20))
    profit_boss = PlayerAI._lifesteal_buff_profit(atk, boss, "피의 격노", 1)
    check("긴 전투(최종 보스)는 손익이 양수", profit_boss > 0, profit_boss)

    # 같은 적인데 HP만 거의 없으면 — 남은 행동이 짧아 회수할 시간이 없다
    dying = EntitySnapshot.from_enemy(Make_FinalBoss(20))
    dying.hp = dying.maxhp * 0.02
    profit_dying = PlayerAI._lifesteal_buff_profit(atk, dying, "피의 격노", 1)
    check("곧 죽는 적에게는 손익이 음수", profit_dying < 0, profit_dying)
    check("적 HP가 많을수록 손익이 크다", profit_boss > profit_dying,
          (profit_boss, profit_dying))

    # 회피가 높으면 기대 회수가 줄어든다
    dodgy = EntitySnapshot.from_enemy(Make_FinalBoss(20))
    dodgy.dodge_bonus = 0.50
    check("회피가 높으면 손익이 작아진다",
          PlayerAI._lifesteal_buff_profit(atk, dodgy, "피의 격노", 1) < profit_boss)


def main():
    print("=" * 52)
    print(" 흡혈 버프·약점 표식 지속 재조정 (후속 ①)")
    print("=" * 52)
    test_numbers()
    test_tick_rule()
    test_settle_costs()
    test_session_settles_on_victory()
    test_session_carries_atb()
    test_mark_applies()
    test_ai_gate_horizon()
    print("\n" + "=" * 52)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 52)
    try:
        os.unlink(_db)
    except OSError:
        pass
    sys.exit(1 if FAIL else 0)


main()
