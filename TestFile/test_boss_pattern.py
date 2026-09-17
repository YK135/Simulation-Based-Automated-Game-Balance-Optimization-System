# -*- coding: utf-8 -*-
"""
test_boss_pattern.py — 중간 보스 3페이즈 + 「대지 균열」 예고 카운터 회귀 테스트 (Combat Brief 4장 · 11-1 3-2)

검증 대상:
  · 페이즈 경계(100~60 / 60~25 / 25~0%)와 진입 효과 — 서리 갑주(ARM +20%, ice 부착), 붕괴(SPD +30%, 방어 −25%)
  · 한 번에 두 구간을 넘으면 진입 효과가 순서대로 전부 적용, 페이즈는 내려가지 않음
  · 「대지 균열」 주기(P1 3회 / P2 4회, 예고·발동 행동은 세지 않음) → 예고(관망) → 다음 행동에 발동
  · 예고 보장 규칙 — 플레이어 행동 횟수가 커지기 전엔 발동하지 않고 그동안은 일반공격(계약 ②)
  · 카운터 계약 ① — 공격/스킬/MP 부족은 세고, 상태 조회·마비 실패는 세지 않음
  · 페이즈 전환 시 예약된 예고 유지 + 주기만 초기화, 페이즈 3은 새 예고 없음(직전 예고는 1회 발동)
  · 서리 갑주 재부착 — 반응으로 ice가 사라지면 2번째 보스 행동에 다시 부착
  · 「대지 균열」 계산 — STG 계수 1.8/2.1, 플레이어 ARM 50% 관통, 명중 시 rift 2턴 (회피 시 없음)
  · 세션 통합 — 메시지·TurnLog·action_fx·hits·RL 레코드·배지, 피해 적용 step 안에서의 페이즈 전환
  · 보스 스탯(Make_MidBoss) 불변, 일반 몬스터 경로에 영향 없음
DB를 쓰지 않는다.

실행: python3 TestFile/test_boss_pattern.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.Battlesession import BattleSession
from ai.battle import EntitySnapshot, StatusEffect, execute_skill, execute_single_hit, MONSTER_SKILL_META
from ai.battle import Damage as D
from ai.battle.BossKit import (
    is_midboss, midboss_phase_for, midboss_sync_phase, midboss_frost_tick, midboss_decide,
    MIDBOSS_TYPE, BOSS_TELEGRAPH_DETAIL, MIDBOSS_RIFT_INTERVAL, RIFT_STATUS,
)
from game.Enemy_Class import Make_MidBoss

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def boss():
    return EntitySnapshot.from_enemy(Make_MidBoss(15))


def player(job="전사", spd=30.0, hp=5000, arm=40, luc=0, stg=1, mp=200, skills=None):
    # SPD 30: 보스(24)보다 빨라 라운드마다 먼저 움직이되, ATB 추가 행동권은 서너 번에 한 번만.
    # (SPD 99를 주면 행동마다 +99 ATB로 매번 추가 행동권이 생겨 보스 차례가 영영 오지 않는다)
    return EntitySnapshot(name="용사", hp=hp, maxhp=hp, mp=mp, maxmp=mp,
                          stg=stg, arm=arm, sparm=20, sp=10, luc=luc, lv=15, spd=spd,
                          job=job, learned_skills=list(skills or ["파이어볼1"]), items=[])


class deterministic:
    """난수·크리·회피를 끈다 — uniform=1.0, randint는 상한(임계 초과)."""
    def __enter__(self):
        self.ru, self.ri = D.uniform, D.randint
        D.uniform = lambda a, b: 1.0
        D.randint = lambda a, b: b
    def __exit__(self, *a):
        D.uniform, D.randint = self.ru, self.ri


def has_rift(ent):
    return any(e.effect_type == "rift" for e in ent.status_effects)


def drive(s, player_action="attack", until=None, max_steps=60):
    """큐 순서대로 step을 진행한다. until(s, out)가 True가 되는 step의 응답을 돌려준다.
    (플레이어 SPD가 높으면 추가 행동권으로 연속 두 번 움직이므로 단순 교대 호출은 안 맞는다)"""
    out = None
    for _ in range(max_steps):
        if s.done:
            break
        na, _i = s._peek_next_actor()
        out = s.step(player_action if na == "player" else "auto")
        if until and until(s, out):
            return out
    return out if until is None else None


def boss_actions(s):
    return sum(1 for l in s.logs if l.actor == "enemy")


def main():
    print("=" * 60)
    print(" 중간 보스 3페이즈 + 대지 균열 예고 (3-2)")
    print("=" * 60)

    # ── [0] 스탯 불변 ─────────────────────────────────────────
    print("\n[0] 보스 스탯 불변 · 식별")
    u = Make_MidBoss(15)
    check("Make_MidBoss 스탯 그대로 (1200/36/27/24/28/24/22)",
          (u.hp, u.stg, u.arm, u.sparm, u.sp, u.spd, u.luc) == (1200, 36, 27, 24, 28, 24, 22))
    b = boss()
    check("enemy_type == '중간 보스' → is_midboss", b.enemy_type == MIDBOSS_TYPE and is_midboss(b))
    check("고블린은 보스가 아님", not is_midboss(EntitySnapshot(name="고블린", hp=1, maxhp=1, mp=0, maxmp=0,
                                                               stg=1, arm=1, sparm=1, sp=1, luc=1, lv=1, enemy_type="고블린")))
    check("초기 필드 (phase 0 / cycle 0 / telegraph -1)",
          (b.boss_phase, b.boss_cycle, b.boss_telegraph_at) == (0, 0, -1))

    # ── [1] 페이즈 경계와 진입 효과 ───────────────────────────
    print("\n[1] 페이즈 경계 · 진입 효과")
    check("경계: 1.0→1, 0.61→1, 0.60→2, 0.26→2, 0.25→3, 0→3",
          [midboss_phase_for(x) for x in (1.0, 0.61, 0.60, 0.26, 0.25, 0.0)] == [1, 1, 2, 2, 3, 3])
    b = boss()
    check("첫 동기화: 진입 없음, phase 1", midboss_sync_phase(b) == [] and b.boss_phase == 1)
    arm0, spd0, sparm0 = b.arm, b.spd, b.sparm
    b.hp = b.maxhp * 0.59
    b.boss_cycle = 2
    check("HP 59% → [2] 진입", midboss_sync_phase(b) == [2] and b.boss_phase == 2)
    check("서리 갑주: ARM +20% (기본 스탯)", abs(b.arm - arm0 * 1.2) < 1e-9, b.arm)
    check("서리 갑주: ice 부착", b.element_queue == ["ice"])
    check("전환 시 주기 카운터 초기화", b.boss_cycle == 0)
    check("다시 동기화해도 진입 없음", midboss_sync_phase(b) == [])
    b.hp = b.maxhp * 0.20
    check("HP 20% → [3] 진입", midboss_sync_phase(b) == [3] and b.boss_phase == 3)
    check("붕괴: SPD +30%", abs(b.spd - spd0 * 1.3) < 1e-9, b.spd)
    check("붕괴: ARM −25% (서리 갑주 위에)", abs(b.arm - arm0 * 1.2 * 0.75) < 1e-9, b.arm)
    check("붕괴: SPARM −25%", abs(b.sparm - sparm0 * 0.75) < 1e-9, b.sparm)
    b.hp = b.maxhp
    check("HP가 올라도 페이즈는 내려가지 않음", midboss_sync_phase(b) == [] and b.boss_phase == 3)
    b = boss(); b.hp = b.maxhp * 0.1
    check("한 번에 두 구간 → [2, 3] 순서대로", midboss_sync_phase(b) == [2, 3]
          and b.element_queue == ["ice"] and abs(b.arm - arm0 * 1.2 * 0.75) < 1e-9)
    b = boss(); b.boss_telegraph_at = 4; b.boss_cycle = 1; b.hp = b.maxhp * 0.5
    midboss_sync_phase(b)
    check("전환 시 예약된 예고는 유지, 주기만 초기화", b.boss_telegraph_at == 4 and b.boss_cycle == 0)

    # ── [2] 행동 결정 ─────────────────────────────────────────
    print("\n[2] 행동 결정 — 주기 · 예고 · 보장 규칙")
    atk = lambda: 0.0
    b = boss(); midboss_sync_phase(b)
    a1 = midboss_decide(b, 5, rng=atk); a2 = midboss_decide(b, 5, rng=atk)
    check("정규 행동 2회 (attack) — cycle 2", a1.action_type == a2.action_type == "attack" and b.boss_cycle == 2)
    a3 = midboss_decide(b, 5, rng=atk)
    check("3번째 → 예고(watch boss_telegraph), telegraph_at = 5, cycle 0",
          (a3.action_type, a3.detail, b.boss_telegraph_at, b.boss_cycle) == ("watch", BOSS_TELEGRAPH_DETAIL, 5, 0))
    a4 = midboss_decide(b, 5, rng=lambda: 0.99)
    check("플레이어가 아직 안 움직임 → 보류: 일반공격 (관망 아님), 예고 유지",
          (a4.action_type, b.boss_telegraph_at) == ("attack", 5))
    a5 = midboss_decide(b, 6, rng=lambda: 0.99)
    check("행동 횟수 6 > 5 → 대지 균열 발동, 예약 해제",
          (a5.action_type, a5.detail, b.boss_telegraph_at) == ("skill", "대지 균열", -1))
    check("발동 행동은 주기에 안 셈 (cycle 0)", b.boss_cycle == 0)
    a6 = midboss_decide(b, 6, rng=lambda: 0.75)
    check("확률 0.75 → 몸통박치기2", (a6.action_type, a6.detail) == ("skill", "몸통박치기2"))
    a7 = midboss_decide(b, 6, rng=lambda: 0.95)
    check("확률 0.95 → 관망(watching)", (a7.action_type, a7.detail) == ("watch", "watching"))
    b.mp = 0; b.boss_cycle = 0                        # 주기가 차서 예고가 나오지 않게
    a8 = midboss_decide(b, 6, rng=lambda: 0.75)
    check("MP 부족이면 몸통박치기2 대신 일반공격", a8.action_type == "attack", a8)
    b.mp = 100
    # 페이즈 2: 주기 4, 강화 계수
    b = boss(); b.hp = b.maxhp * 0.5; midboss_sync_phase(b)
    acts = [midboss_decide(b, 1, rng=atk) for _ in range(4)]
    check("P2: 정규 3회 뒤 4번째에 예고", [a.action_type for a in acts] == ["attack"] * 3 + ["watch"])
    a = midboss_decide(b, 2, rng=atk)
    check("P2 발동 스킬은 대지 균열_강화", a.detail == "대지 균열_강화")
    # 페이즈 3: 예고 없음, 관망 없음
    b = boss(); b.hp = b.maxhp * 0.2; midboss_sync_phase(b)
    acts = [midboss_decide(b, i, rng=lambda: 0.95) for i in range(30)]
    check("P3: 30회 동안 예고 없음, 관망 없음 (0.95 → 몸통박치기2)",
          all(a.action_type == "skill" and a.detail == "몸통박치기2" for a in acts[:10])
          and b.boss_telegraph_at == -1 and b.boss_cycle == 0)
    # 전환 직전 예고 → P3에서 1회 발동 뒤 멈춤
    b = boss(); b.hp = b.maxhp * 0.5; midboss_sync_phase(b)
    for _ in range(4):
        midboss_decide(b, 1, rng=atk)               # 4번째가 예고
    check("P2 예고 세워짐", b.boss_telegraph_at == 1)
    b.hp = b.maxhp * 0.2; midboss_sync_phase(b)
    a = midboss_decide(b, 2, rng=atk)
    check("P3 전환 후 예약분은 1회 발동(강화)", (a.action_type, a.detail) == ("skill", "대지 균열_강화"))
    acts = [midboss_decide(b, 3 + i, rng=atk) for i in range(20)]
    check("그 뒤로는 예고 없음", all(a.action_type == "attack" for a in acts) and b.boss_telegraph_at == -1)

    # ── [3] 서리 갑주 재부착 ──────────────────────────────────
    print("\n[3] 서리 갑주 재부착")
    b = boss(); midboss_sync_phase(b)
    check("P1에서는 아무것도 안 함", midboss_frost_tick(b) is False and b.element_queue == [])
    b.hp = b.maxhp * 0.5; midboss_sync_phase(b)
    check("ice가 붙어 있으면 False, 카운터 0", midboss_frost_tick(b) is False and b.boss_frost_regrow == 0)
    b.element_queue = []                                # 융해로 소모됨
    t1 = midboss_frost_tick(b); t2 = midboss_frost_tick(b)
    check("소모 뒤 1번째 행동: 아직 (False), 2번째 행동: 재부착 (True)", (t1, t2) == (False, True))
    check("재부착 후 큐 ['ice']", b.element_queue == ["ice"])
    b.element_queue = ["lightning"]                     # 다른 원소로 덮인 경우
    midboss_frost_tick(b); midboss_frost_tick(b)
    check("다른 원소가 붙어 있어도 2번째 행동에 ice로 교체", b.element_queue == ["ice"])

    # ── [4] 대지 균열 계산 ────────────────────────────────────
    print("\n[4] 「대지 균열」 계산 — 계수 · ARM 관통 · rift 부여")
    m1, m2 = MONSTER_SKILL_META["대지 균열"], MONSTER_SKILL_META["대지 균열_강화"]
    check("메타: 계수 1.8 / 2.1, ARM 관통 0.5, on_hit_status rift 2턴",
          (m1["mult"], m2["mult"], m1["arm_pen"], m1["on_hit_status"]["effect_type"], m1["on_hit_status"]["turns"])
          == (1.8, 2.1, 0.5, "rift", 2))
    p = player(arm=40); b = boss()
    with deterministic():
        expected, _, _ = D.DamageCalc.physical(36, 22, 40 * 0.5, p.luc, skill_mult=1.8, role="monster")
        dmg, mp_lack, _ = execute_skill("대지 균열", b, p)
    check("execute_skill 피해 = STG 36 × 1.8, ARM 절반 (기준 피해)", dmg == expected, (dmg, expected))
    check("명중 시 rift 2턴 부여", has_rift(p) and next(e for e in p.status_effects if e.effect_type == "rift").turns == 2)
    with deterministic():
        p2 = player(arm=40)
        full, _, _ = D.DamageCalc.physical(36, 22, 40, p2.luc, skill_mult=1.8, role="monster")
        single, _, _ = execute_single_hit("대지 균열", b, p2)
    check("ARM 관통이 실제로 피해를 키움 (관통 > 비관통)", dmg > full, (dmg, full))
    check("execute_single_hit도 같은 관통 계산", single == dmg, (single, dmg))
    p = player(arm=40, luc=10)
    ru, ri = D.uniform, D.randint
    D.uniform, D.randint = (lambda a, b: 1.0), (lambda a, b: a)          # 회피 판정 항상 성공
    try:
        dmg, _, _ = execute_skill("대지 균열", b, p)
    finally:
        D.uniform, D.randint = ru, ri
    check("회피하면 피해 0 + rift 없음", dmg == 0 and not has_rift(p))
    p = player(); p.status_effects.append(StatusEffect(effect_type="ignite", turns=3, name="화상"))
    with deterministic():
        execute_skill("대지 균열", boss(), p)
    check("화상 위에 균열이 별개로 (효과 2개)", len(p.status_effects) == 2)

    # ── [5] 세션 통합 ─────────────────────────────────────────
    print("\n[5] 세션 — 카운터 계약 ①")
    random.seed(20260917)
    s = BattleSession(player(mp=0), enemy=boss(), items=[])
    check("시작 카운터 0", s._player_action_count == 0)
    s.step("attack");            c1 = s._player_action_count
    s.step("auto")
    s.step("status");            c2 = s._player_action_count
    s.step("skill:파이어볼1");    c3 = s._player_action_count     # MP 0 → skill_failed
    check("공격 1 / 상태 조회 0 / MP 부족 1 → 누적 2", (c1, c2, c3) == (1, 1, 2), (c1, c2, c3))
    check("MP 부족은 skill_failed 로그로 차례 소비", s.logs[-1].action == "skill_failed")
    s.step("auto")
    s.player.status_effects.append(StatusEffect(effect_type="paralyze", turns=9, name="lightning", fail_prob=100))
    out = s.step("attack")
    check("마비 실패는 세지 않음 (여전히 2)", s._player_action_count == 2
          and any("마비로 행동에 실패" in m for m in out["messages"]))
    s.player.status_effects = []

    print("\n[5b] 세션 — 예고 → 보류 → 발동 흐름")
    random.seed(20260917)
    s = BattleSession(player(), enemy=boss(), items=[])
    b = s.enemies[0]
    tele_out = drive(s, until=lambda s_, o: b.boss_telegraph_at >= 0)
    check("3번째 보스 행동에서 예고", tele_out is not None and boss_actions(s) == 3, boss_actions(s))
    if tele_out:
        check("예고 메시지", any("「대지 균열」 예고" in m for m in tele_out["messages"]), tele_out["messages"])
        check("예고 TurnLog: watch / boss_telegraph", s.logs[-1].action == "watch" and s.logs[-1].action_detail == BOSS_TELEGRAPH_DETAIL)
        fx = tele_out["action_fx"]
        check("action_fx: enemy · watch · boss_telegraph · self", fx and fx["kind"] == "watch"
              and fx["name"] == BOSS_TELEGRAPH_DETAIL and fx["scope"] == "self" and fx["actor"] == "enemy", fx)
        check("RL 레코드: type watch / detail boss_telegraph",
              s.rl_log[-1]["action"]["type"] == "watch" and s.rl_log[-1]["action"]["detail"] == BOSS_TELEGRAPH_DETAIL)
        badges = tele_out["enemies"][0]["pattern"]
        tb = next((x for x in badges if x["kind"] == "telegraph"), None)
        check("배지: 대지 균열 armed 3/3", tb and (tb["label"], tb["cur"], tb["max"], tb["state"]) == ("대지 균열", 3, 3, "armed"), badges)
        pb = next((x for x in badges if x["kind"] == "phase"), None)
        check("배지: 페이즈 1/3 시험", pb and (pb["label"], pb["cur"], pb["max"]) == ("시험", 1, 3), badges)
        check("예고 시점 telegraph_at == 플레이어 행동 횟수", b.boss_telegraph_at == s._player_action_count)
        # 보류: 플레이어가 마비로 못 움직이면 보스는 일반공격만
        s.player.status_effects.append(StatusEffect(effect_type="paralyze", turns=9, name="lightning", fail_prob=100))
        n_before = boss_actions(s)
        out = drive(s, until=lambda s_, o: boss_actions(s_) > n_before)
        check("보류 중 보스는 일반공격 (→ 공격), 예고 유지",
              any("→ 공격" in m for m in out["messages"]) and b.boss_telegraph_at >= 0, out["messages"])
        check("보류 중 배지는 여전히 armed",
              any(x["kind"] == "telegraph" and x["state"] == "armed" for x in out["enemies"][0]["pattern"]))
        s.player.status_effects = []
        drive(s, until=lambda s_, o: s_._player_action_count > b.boss_telegraph_at)   # 플레이어가 한 번 움직임
        hp0 = s.player.hp
        n_before = boss_actions(s)
        out = drive(s, until=lambda s_, o: boss_actions(s_) > n_before)
        check("플레이어가 움직인 뒤 → 대지 균열 발동", any("→ 대지 균열!" in m for m in out["messages"]), out["messages"])
        check("발동 후 예약 해제, rift 부여 메시지", b.boss_telegraph_at == -1
              and any("「균열」이 새겨졌다" in m for m in out["messages"]))
        check("플레이어에게 rift 2턴", has_rift(s.player))
        check("TurnLog: skill / 대지 균열 / 피해 > 0", s.logs[-1].action == "skill"
              and s.logs[-1].action_detail == "대지 균열" and s.logs[-1].damage_dealt > 0)
        fx = out["action_fx"]
        check("action_fx: skill 대지 균열 → 대상 player", fx and fx["kind"] == "skill" and fx["name"] == "대지 균열"
              and fx["stype"] == "physical" and fx["targets"] == [{"side": "player", "slot": -1}], fx)
        hit = [h for h in out["hits"] if h["target"] == "player" and h["kind"] == "damage"]
        check("hits: 플레이어 damage 이벤트 (via skill)", len(hit) == 1 and hit[0]["via"] == "skill", out["hits"])
        # 순 HP 변화가 아니라 균열이 준 피해와 비교 — 전사 패시브 회복이 같은 step에 겹칠 수 있다
        check("hits 금액 = 균열 TurnLog의 damage_dealt", hit and hit[0]["amount"] == s.logs[-1].damage_dealt,
              (hit, s.logs[-1].damage_dealt))
        check("RL 레코드: skill / 대지 균열 / damage_type physical",
              s.rl_log[-1]["action"]["detail"] == "대지 균열" and s.rl_log[-1]["result"]["damage_type"] == "physical")
        check("잔차 0", getattr(s, "_last_hit_residual", 0) == 0)
        # 다음 플레이어 차례 시작에 균열 틱
        out = drive(s, until=lambda s_, o: any("균열 -" in m for m in o["messages"]), max_steps=4)
        check("다음 플레이어 행동 시작에 균열 틱 (-4% maxHP)", out is not None and
              any("균열 -" in m for m in out["messages"]) and any(h["via"] == "dot" and h["target"] == "player" for h in out["hits"]))

    print("\n[5c] 세션 — 피해 적용 step 안에서의 페이즈 전환 · 실드 흡수")
    random.seed(1)
    s = BattleSession(player(stg=60), enemy=boss(), items=[])   # 한 방 ≈ 95 → 62%에서 54%로
    b = s.enemies[0]
    b.hp = b.maxhp * 0.62
    out = s.step("attack")
    check("플레이어의 step 안에서 서리 갑주 전환 메시지", any("서리 갑주" in m for m in out["messages"]), out["messages"])
    check("같은 응답의 배지가 이미 페이즈 2 / 주기 0/4",
          any(x["kind"] == "phase" and x["cur"] == 2 for x in out["enemies"][0]["pattern"])
          and any(x["kind"] == "telegraph" and x["max"] == 4 for x in out["enemies"][0]["pattern"]), out["enemies"][0]["pattern"])
    check("응답의 enemy element_aura == ice", out["enemies"][0]["element_aura"] == "ice")
    # 실드가 전부 흡수해도 명중이므로 균열은 걸린다
    s = BattleSession(player(spd=1.0), enemy=boss(), items=[])   # 보스가 먼저 움직인다
    b = s.enemies[0]; b.boss_phase = 1; b.boss_telegraph_at = 0
    s._player_action_count = 1
    s.player.shield = 10_000
    with deterministic():
        out = s.step("auto")
    check("실드 완전 흡수: HP 피해 0, rift는 부여", s.player.hp == s.player.maxhp and has_rift(s.player)
          and any("→ 대지 균열!" in m for m in out["messages"]), out["messages"])

    print("\n[6] 일반 몬스터 경로 무영향")
    g = EntitySnapshot(name="고블린", hp=500, maxhp=500, mp=0, maxmp=0, stg=10, arm=5, sparm=5, sp=0, luc=0, lv=5, spd=1.0, enemy_type="고블린")
    s = BattleSession(player(stg=50), enemy=g, items=[])
    out = s.step("attack")
    check("고블린에겐 보스 배지 없음", out["enemies"][0]["pattern"] == [])
    check("고블린 boss_phase 그대로 0", s.enemies[0].boss_phase == 0)

    print("\n" + "=" * 60)
    print(f" 결과: ✅ {PASS}  ❌ {FAIL}")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
