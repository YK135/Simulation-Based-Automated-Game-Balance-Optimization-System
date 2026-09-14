# -*- coding: utf-8 -*-
"""
test_balance_patch_3.py — 밸런스 3차 회귀 테스트
─────────────────────────────────────────────
검증 대상 (BALANCE_PATCH_3):
  1) 시뮬레이터 cross-battle ATB 이월
     (EntitySnapshot.atb_remainder → ATBSystem → BattleEngine/BattleResult)
  2) MultiBattleSimulator의 enemy_count 전달 버그 수정
  3) core/Balance_Hook.py의 get_encounter() 그룹 튜닝 (캐시 키 정규화, 큐 포화 폴백)
  4) ai/Simulator.py의 scale_entity_snapshot() 순수 함수 추출이 기존 공식과
     동일한지

전부 순수 인메모리 계산/시뮬레이션이라 DB를 전혀 건드리지 않는다 — 임시 DB
격리가 필요 없음.

실행: python3 TestFile/test_balance_patch_3.py
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


from ai.battle import EntitySnapshot, BattleEngine
from ai.battle.ATB import ATBSystem
from ai.Auto_AI import PlayerAI, EnemyAI
from ai.Simulator import BattleSimulator, MultiBattleSimulator, StatTuner, scale_entity_snapshot
import core.Balance_Hook as BH
from core.Balance_Hook import BalanceHook


def make_snap(**overrides) -> EntitySnapshot:
    base = dict(
        name="테스트", hp=500, maxhp=500, mp=100, maxmp=100,
        stg=20, arm=10, sparm=10, sp=15, luc=10, lv=10, spd=10.0,
        learned_skills=[], items=[], enemy_type="고블린",
    )
    base.update(overrides)
    return EntitySnapshot(**base)


def test_atb_field_and_engine_wiring():
    print("\n[1] EntitySnapshot.atb_remainder → BattleEngine 초기 ATB")
    check("EntitySnapshot 기본 atb_remainder == 0.0", make_snap().atb_remainder == 0.0)

    p0 = make_snap(atb_remainder=0.0)
    e  = make_snap(name="적", enemy_type="고블린")
    eng0 = BattleEngine(p0, e)
    check("atb_remainder=0 → ATBSystem.player_pt 시작값 0.0", eng0.atb.player_pt == 0.0)
    check("적(enemy_pt)은 항상 0에서 시작", eng0.atb.enemy_pt == 0.0)

    p1 = make_snap(atb_remainder=42.5)
    eng1 = BattleEngine(p1, e)
    check("atb_remainder=42.5 → ATBSystem.player_pt 시작값 42.5", eng1.atb.player_pt == 42.5)

    print("\n[2] ATBSystem 100 초과분 이월 + player_start 동시 적용")
    atb = ATBSystem(player_start=95.0)
    actors = atb.tick(player_spd=20, enemy_spd=5)
    check("player_start=95 + spd20 → 즉시 행동권 획득", "player" in actors, str(actors))
    check("100 초과분만 차감(95+20-100=15)", abs(atb.player_pt - 15.0) < 1e-6, str(atb.player_pt))

    print("\n[3] BattleResult.final_player_atb 노출")
    p2 = make_snap(atb_remainder=0.0, hp=500, maxhp=500)
    weak_enemy = make_snap(name="약체", hp=1, maxhp=1, stg=1, arm=0, sparm=0)
    result = BattleEngine(p2, weak_enemy).run(PlayerAI("balanced"), EnemyAI())
    check("final_player_atb 필드 존재", hasattr(result, "final_player_atb"))
    check("final_player_atb는 0 이상의 float", isinstance(result.final_player_atb, float)
          and result.final_player_atb >= 0.0, str(result.final_player_atb))


def test_independent_trials_not_chained():
    print("\n[4] BattleSimulator — 독립 시행 보장 (템플릿 atb_remainder 불변)")
    p = make_snap(atb_remainder=50.0)
    e = make_snap(name="적")
    sim = BattleSimulator(p, e, n=30)
    sim.run()
    check("n회 시행 후에도 템플릿 원본 atb_remainder 그대로(50.0)",
          sim.player_template.atb_remainder == 50.0, str(sim.player_template.atb_remainder))

    print("\n[5] montecarlo류 시뮬 입력이 atb_remainder를 안 세팅하면 기존 결과 불변")
    p_default = make_snap()  # atb_remainder 미지정 → 기본 0.0
    check("기본 EntitySnapshot은 atb_remainder=0 (기존 스윕 영향 없음)",
          p_default.atb_remainder == 0.0)


def test_multibattle_enemy_count_fix():
    print("\n[6] MultiBattleSimulator — enemy_count가 실제로 decide()에 전달되는지")
    captured = []
    orig_decide = PlayerAI.decide

    def spy_decide(self, attacker, defender, enemy_count=1):
        captured.append(enemy_count)
        return orig_decide(self, attacker, defender, enemy_count=enemy_count)

    PlayerAI.decide = spy_decide
    try:
        player = make_snap(hp=2000, maxhp=2000, stg=30)
        enemies = [make_snap(name=f"적{i}", hp=200, maxhp=200, stg=5, arm=0) for i in range(3)]
        sim = MultiBattleSimulator(player, enemies, n=2, max_turns=30)
        sim.run()
    finally:
        PlayerAI.decide = orig_decide

    check("decide() 호출 기록 있음", len(captured) > 0)
    check("enemy_count>1로 호출된 적 있음(1v3이므로)", any(c > 1 for c in captured), str(captured[:10]))


def test_scale_entity_snapshot_matches_documented_formula():
    print("\n[7] scale_entity_snapshot() — 문서화된 공식과 일치 (리팩터 회귀 방지)")
    base = make_snap(hp=100, maxhp=100, stg=10, arm=10, luc=10, sparm=10, sp=10, spd=10)

    goblin = scale_entity_snapshot(base, 2.0, "고블린")
    exp_hp = 100 * (0.60 + 0.30 * 2.0)
    exp_stg = 10 * math.sqrt(2.0)
    check("고블린(표준) hp 공식 일치", abs(goblin.hp - exp_hp) < 1e-6, f"{goblin.hp} vs {exp_hp}")
    check("고블린(표준) stg 공식 일치", abs(goblin.stg - exp_stg) < 1e-6)
    check("고블린(표준) arm은 공통 축만(min(scale,2.5)=2.0)",
          abs(goblin.arm - 10 * min(2.0, 2.5)) < 1e-6)

    golem = scale_entity_snapshot(base, 2.0, "골렘")
    exp_arm = 10 * min(2.0, 2.5) * min(2.0 * 0.15 + 1.0, 1.5)
    check("골렘(탱커형) arm에 역할 추가축이 곱해짐", abs(golem.arm - exp_arm) < 1e-6,
          f"{golem.arm} vs {exp_arm}")

    print("\n[8] StatTuner._scale_enemy가 여전히 scale_entity_snapshot을 통해 동작")
    player_snap = make_snap()
    tuner = StatTuner(player_snap, base, chapter=1)
    scaled = tuner._scale_enemy(2.0)
    check("StatTuner._scale_enemy 결과가 직접 호출과 동일",
          abs(scaled.hp - exp_hp) < 1e-6 and abs(scaled.stg - exp_stg) < 1e-6)


def _make_hook(job="전사", lv=10):
    import io, contextlib
    from game.Player_Class import create_player_by_job
    from game.Lv import LV_
    with contextlib.redirect_stdout(io.StringIO()):
        p = create_player_by_job("밸런스3테스터", job)
        lvup = LV_(p)
        guard = 0
        while p.lv < lv and guard < 300:
            lvup.Get_exp(p, reward_exp=p.maxexp)
            guard += 1
    hook = BalanceHook(p, [], show_graph=False, verbose=False, auto_prewarm=False)
    return hook


def test_get_encounter_cache_key_normalization():
    print("\n[9] get_encounter() — 캐시 키가 '몬스터 종류'가 아니라 '난이도 구성'으로 정규화")
    hook = _make_hook()

    hook.get_encounter([("고블린", "normal"), ("박쥐", "normal")], chapter=1)
    n_after_first = len(hook._group_ready)
    check("첫 호출 → 그룹 튜닝 작업 1건 등록", n_after_first == 1, str(hook._group_ready.keys()))

    # 몬스터 종류는 완전히 다르지만 난이도 구성(normal,normal)이 같음 → 같은 키 재사용,
    # 새 백그라운드 작업이 추가로 생기면 안 됨.
    hook.get_encounter([("슬라임", "normal"), ("골렘", "normal")], chapter=1)
    check("난이도 구성이 같으면 종류가 달라도 캐시 항목이 늘지 않음",
          len(hook._group_ready) == n_after_first, str(hook._group_ready.keys()))

    # 난이도 구성이 다르면(hard 포함) 새 키가 생겨야 함.
    hook.get_encounter([("고블린", "hard"), ("박쥐", "normal")], chapter=1)
    check("난이도 구성이 다르면 새 캐시 키 생성",
          len(hook._group_ready) == n_after_first + 1, str(hook._group_ready.keys()))


def test_get_encounter_queue_full_fallback():
    print("\n[10] get_encounter() — 큐 포화 시 applied=False 폴백 + 흔적 정리")
    hook = _make_hook()

    orig_submit = BH._SIM_EXECUTOR.submit
    BH._SIM_EXECUTOR.submit = lambda fn: False
    try:
        snaps, applied = hook.get_encounter([("고블린", "easy"), ("박쥐", "easy")], chapter=1)
    finally:
        BH._SIM_EXECUTOR.submit = orig_submit

    check("큐 포화 시 applied=False", applied is False)
    check("큐 포화 시에도 개별 튜닝(폴백) 스냅샷은 정상 반환", len(snaps) == 2)
    key = (1, ("easy", "easy"))
    check("제출 실패한 키는 _group_ready에 흔적을 안 남김(다음 호출이 재시도 가능)",
          key not in hook._group_ready)


def main():
    print("=" * 56)
    print(" 밸런스 3차 회귀 테스트 — ATB 이월 + 그룹 튜닝")
    print("=" * 56)
    test_atb_field_and_engine_wiring()
    test_independent_trials_not_chained()
    test_multibattle_enemy_count_fix()
    test_scale_entity_snapshot_matches_documented_formula()
    test_get_encounter_cache_key_normalization()
    test_get_encounter_queue_full_fallback()

    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
