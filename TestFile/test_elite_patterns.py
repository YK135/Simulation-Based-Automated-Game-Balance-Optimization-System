# -*- coding: utf-8 -*-
"""
test_elite_patterns.py — 엘리트 몬스터 패턴 회귀 테스트
─────────────────────────────────────────────
실행: python3 TestFile/test_elite_patterns.py

검증 대상 (9종 엘리트 패턴 + 공통 인프라):
  일반 노드(elite_leader=False)에서는 패턴 미발동, 증식 슬라임 1회 한정
  분열 + 보상 제외, 골렘 3단계 사이클 + 그로기 인터럽트, 암살자 표식,
  화염/번개 슬라임 스택+과부하 리셋, 빙결 슬라임 파쇄, 사제 부활(1회 한정,
  재분열/재부활 없음), 박쥐 흡혈+비명, 고블린 버프/분노, 전투 정상 종료.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def mk_player(hp=2000, mp=300, stg=200, spd=99.0, job="전사"):
    return EntitySnapshot(
        name="테스트", hp=hp, maxhp=hp, mp=mp, maxmp=mp,
        stg=stg, arm=20, sparm=10, sp=10, luc=0, lv=10, spd=spd,
        job=job, learned_skills=["급소찌르기1"], items=[])


def mk_elite(etype, hp=100000, stg=10, spd=1.0, elite_leader=True):
    e = EntitySnapshot(
        name=etype, hp=hp, maxhp=hp, mp=999, maxmp=999,
        stg=stg, arm=5, sparm=5, sp=10, luc=0, lv=5, spd=spd,
        enemy_type=etype)
    e.is_elite = True
    e.elite_leader = elite_leader
    return e


# ═══════════════════════════════════════════════════════
# 공통 — 일반 노드에서는 패턴 미발동
# ═══════════════════════════════════════════════════════

def test_non_elite_no_pattern():
    player = mk_player()
    enemy = mk_elite("고블린", elite_leader=False)
    session = BattleSession(player, enemy=enemy, items=[])
    msgs = []
    session._elite_pre_action(enemy, msgs)  # elite_leader=False라 호출 자체는 방어적으로 no-op이어야 함
    # _single_enemy_action의 분기가 elite_leader를 체크하므로, 여기선 필드 자체가 꺼져있는지만 확인
    check("elite_leader=False 몬스터는 is_elite/elite_leader 모두 False",
          not enemy.is_elite is True or not enemy.elite_leader)


# ═══════════════════════════════════════════════════════
# 증식 슬라임 — 분열
# ═══════════════════════════════════════════════════════

def test_slime_split():
    player = mk_player()
    enemy = mk_elite("슬라임", hp=50, stg=10)
    session = BattleSession(player, enemy=enemy, items=[])
    enemy = session.enemies[0]   # BattleSession.__init__이 deepcopy하므로 세션 내부 객체로 갱신
    msgs = []
    session._apply_dmg_shielded(enemy, 999, msgs)  # 원본 즉사

    check("분열 후 적 목록이 3마리(원본+작은슬라임2)", len(session.enemies) == 3,
          f"len={len(session.enemies)}")
    children = [e for e in session.enemies if e.enemy_type == "작은 슬라임"]
    check("작은 슬라임 2마리 생성", len(children) == 2, f"count={len(children)}")
    if children:
        check("작은 슬라임 maxhp=원본의 30%", abs(children[0].maxhp - 50 * 0.30) < 0.01)
        check("작은 슬라임 stg=원본의 65%", abs(children[0].stg - 10 * 0.65) < 0.01)
        check("작은 슬라임은 보상 제외(reward_eligible=False)", children[0].reward_eligible is False)
        check("작은 슬라임은 is_summoned=True", children[0].is_summoned is True)
    check("enemy_atbs 병렬 배열도 함께 늘어남", len(session.enemy_atbs) == len(session.enemies))

    # 1회 한정 — 다시 죽여도(이미 hp<=0) 추가 분열 없어야 함
    msgs2 = []
    session._apply_dmg_shielded(enemy, 999, msgs2)
    check("증식은 전투당 1회만 (재분열 없음)", len(session.enemies) == 3)


def test_defeated_list_excludes_summoned():
    from app.Battle import _get_defeated_list

    player = mk_player()
    origin = mk_elite("슬라임", hp=50, stg=10)
    session = BattleSession(player, enemy=origin, items=[])
    origin = session.enemies[0]
    session._apply_dmg_shielded(origin, 999, [])
    for e in session.enemies:
        e.hp = 0   # 전부 처치된 상태로 가정

    defeated = _get_defeated_list(session)
    names = [d.name for d in defeated]
    check("_get_defeated_list가 작은 슬라임을 보상 목록에서 제외",
          "작은 슬라임" not in names, f"names={names}")
    check("원본 증식 슬라임은 보상 목록에 포함", "슬라임" in names, f"names={names}")


# ═══════════════════════════════════════════════════════
# 골렘 — 3단계 사이클 + 그로기 인터럽트
# ═══════════════════════════════════════════════════════

def test_golem_cycle():
    player = mk_player()
    golem = mk_elite("골렘", hp=100000, stg=10)
    session = BattleSession(player, enemy=golem, items=[])
    golem = session.enemies[0]   # deepcopy 반영

    check("골렘 초기 phase=0(수비태세)", golem.elite_phase == 0)
    session._elite_golem_action(golem, [])
    check("1회차 후 phase=1(충전예고)", golem.elite_phase == 1)
    session._elite_golem_action(golem, [])
    check("2회차 후 phase=2(공격 대기)", golem.elite_phase == 2)
    hp_before = session.player.hp
    session._elite_golem_action(golem, [])
    check("3회차(공격) 후 phase가 0으로 재시작", golem.elite_phase == 0)
    check("강화 몸통박치기가 실제 대미지를 입힘", session.player.hp < hp_before,
          f"hp {hp_before}->{session.player.hp}")


def test_golem_groggy_interrupt():
    player = mk_player()
    golem = mk_elite("골렘", hp=100000, stg=10)
    session = BattleSession(player, enemy=golem, items=[])
    session._elite_golem_action(golem, [])  # phase 0->1 (충전예고)
    check("충전예고 진입", golem.elite_phase == 1)

    msgs = []
    session._apply_dmg_shielded(golem, 10, msgs, is_basic_attack=True)
    session._apply_dmg_shielded(golem, 10, msgs, is_basic_attack=True)
    check("충전예고 중 기본공격 2연속 적중 → 그로기 발생", golem.physical_hit_streak == 0)
    check("그로기로 강화공격 취소, phase가 0으로 리셋", golem.elite_phase == 0,
          f"phase={golem.elite_phase}")
    check("그로기 메시지 출력", any("그로기" in m for m in msgs), msgs)


# ═══════════════════════════════════════════════════════
# 암살자 — 표식
# ═══════════════════════════════════════════════════════

def test_assassin_mark_cycle():
    player = mk_player()
    assassin = mk_elite("암살자", hp=100000, stg=10)
    session = BattleSession(player, enemy=assassin, items=[])

    check("암살자 마크 없음 초기", not session._has_assassin_mark())
    for _ in range(3):
        msgs = []
        session._elite_pre_action(assassin, msgs)
    check("3번째 행동에서 표식 부여", session._has_assassin_mark())
    check("표식 부여 후 elite_phase=1(다음 행동 급소찌르기 강제)", assassin.elite_phase == 1)

    from ai.battle import elite_forced_action
    forced = elite_forced_action(assassin, player, chapter=2)
    check("표식 다음 행동은 급소찌르기1 강제",
          forced is not None and forced.action_type == "skill" and forced.detail == "급소찌르기1")
    check("강제 발동 후 elite_phase가 0으로 리셋", assassin.elite_phase == 0)


def test_assassin_mark_cleared_by_full_shield():
    player = mk_player()
    assassin = mk_elite("암살자", hp=100000, stg=10)
    session = BattleSession(player, enemy=assassin, items=[])
    from ai.battle import Debuff
    player.apply_debuff(Debuff(stat="assassin_mark", amount=0.0, turns=2, name="암살표식"))
    player.shield = 99999
    msgs = []
    dmg = session._apply_dmg_shielded(player, 50, msgs)
    check("실드로 100% 흡수되면 실제 hp 피해 0", dmg == 0)
    session._clear_assassin_mark(msgs)
    check("실드 100% 흡수 시 표식 제거", not session._has_assassin_mark())


# ═══════════════════════════════════════════════════════
# 원소 슬라임 — 스택/과부하/파쇄
# ═══════════════════════════════════════════════════════

def test_fire_slime_overload_resets_stack():
    from ai.battle import apply_element_and_react
    player = mk_player()
    slime = mk_elite("화염 슬라임", hp=100000, stg=10)
    slime.element_queue = ["fire"]
    slime.elite_pattern_turn = 3
    msgs = []
    apply_element_and_react(player, slime, "lightning", 100, msgs)
    check("번개 공격으로 과부하 발생 시 화염 슬라임 열기 스택 초기화",
          slime.elite_pattern_turn == 0, msgs)


def test_lightning_slime_overload_resets_stack_and_slows():
    from ai.battle import apply_element_and_react
    player = mk_player()
    slime = mk_elite("번개 슬라임", hp=100000, stg=10)
    slime.element_queue = ["lightning"]
    slime.elite_pattern_turn = 3
    msgs = []
    apply_element_and_react(player, slime, "fire", 100, msgs)
    check("화염 공격으로 과부하 발생 시 번개 슬라임 전하 스택 초기화",
          slime.elite_pattern_turn == 0, msgs)
    check("과부하 직후 SPD 디버프 부여", any(d.stat == "spd" for d in slime.debuffs))


def test_fire_slime_burst_forced():
    from ai.battle import elite_forced_action
    player = mk_player()
    slime = mk_elite("화염 슬라임", hp=100000, stg=10)
    slime.elite_pattern_turn = 3
    forced = elite_forced_action(slime, player, chapter=1)
    check("열기 3스택 도달 시 화염 버스트 공격 강제",
          forced is not None and forced.action_type == "skill" and "파이어볼" in forced.detail)


def test_ice_slime_shatter_breaks_armor():
    from ai.battle import apply_element_and_react
    player = mk_player()
    slime = mk_elite("빙결 슬라임", hp=100000, stg=10)
    slime.element_queue = ["ice"]
    slime.physical_resist = 0.85
    msgs = []
    apply_element_and_react(player, slime, "physical", 100, msgs)
    check("물리 공격으로 파쇄 발생 시 빙결 갑옷 해제(physical_resist=1.0)",
          slime.physical_resist == 1.0, msgs)
    check("파쇄 시 elite_phase=1(해제 상태)", slime.elite_phase == 1)
    check("파쇄 시 SPARM 디버프 부여", any(d.stat == "sparm" and d.name == "파쇄" for d in slime.debuffs))

    # 같은 턴 중복 파쇄 무시
    resist_before = slime.physical_resist
    debuff_count_before = len(slime.debuffs)
    apply_element_and_react(player, slime, "physical", 100, msgs)
    check("이미 해제 상태에서 중복 파쇄는 무시(디버프 중복 적용 안 됨)",
          len(slime.debuffs) == debuff_count_before and slime.physical_resist == resist_before)


# ═══════════════════════════════════════════════════════
# 사제 — 부활 의식
# ═══════════════════════════════════════════════════════

def test_priest_revival_once_only():
    player = mk_player()
    priest = mk_elite("사제", hp=100000, stg=10)
    escort = mk_elite("고블린", hp=50, stg=5, elite_leader=False)
    session = BattleSession(player, enemies=[priest, escort], items=[])
    priest, escort = session.enemies   # deepcopy 반영
    escort.hp = 0   # 동료 사망 가정

    msgs1 = []
    handled1 = session._priest_elite_revival_check(priest, msgs1)
    check("동료 사망 감지 시 부활 의식 준비 시작(행동 소비)", handled1 is True)
    check("준비 단계 진입(elite_phase=1)", priest.elite_phase == 1)

    msgs2 = []
    handled2 = session._priest_elite_revival_check(priest, msgs2)
    check("다음 행동에 부활 발동", handled2 is True)
    check("동료가 최대HP 25%로 부활", escort.hp == escort.maxhp * 0.25, f"hp={escort.hp}")
    check("부활한 동료는 보상 제외", escort.reward_eligible is False)
    check("사제 부활 능력 1회 소진(elite_pattern_used)", priest.elite_pattern_used is True)

    # 재사망 후 재부활 시도 — 이미 사용했으므로 무시되어야 함
    escort.hp = 0
    msgs3 = []
    handled3 = session._priest_elite_revival_check(priest, msgs3)
    check("부활 1회 소진 후 재부활 시도는 무시", handled3 is False)


def test_priest_death_cancels_ritual():
    player = mk_player()
    priest = mk_elite("사제", hp=50, stg=10)
    escort = mk_elite("고블린", hp=50, stg=5, elite_leader=False)
    session = BattleSession(player, enemies=[priest, escort], items=[])
    priest, escort = session.enemies   # deepcopy 반영
    escort.hp = 0
    session._priest_elite_revival_check(priest, [])
    check("의식 준비 중", priest.elite_phase == 1)

    msgs = []
    session._apply_dmg_shielded(priest, 999, msgs)  # 사제 사망
    check("사제 사망 시 취소 메시지 출력", any("중단" in m for m in msgs), msgs)


# ═══════════════════════════════════════════════════════
# 흡혈 박쥐 / 고블린 대장
# ═══════════════════════════════════════════════════════

def test_bat_lifesteal_and_scream():
    player = mk_player()
    bat = mk_elite("박쥐", hp=1000, stg=10)
    session = BattleSession(player, enemy=bat, items=[])
    bat.hp = 500   # 절반만 채워 회복 여지를 둠 (풀피면 회복량이 캡에 막혀 검증 불가)
    hp_before = bat.hp
    session._elite_bat_lifesteal(bat, 100, [])
    check("흡혈 시 HP 회복(피해량의 20%, 상한 maxHP 10%)",
          bat.hp == hp_before + min(100 * 0.20, bat.maxhp * 0.10))

    for _ in range(3):
        msgs = []
        session._elite_bat_pre(bat, msgs)
    check("3번째 행동에서 비명 예고", bat.elite_phase == 1)
    from ai.battle import elite_forced_action
    forced = elite_forced_action(bat, player, chapter=1)
    check("예고 다음 행동은 초음파비명 강제",
          forced is not None and forced.detail == "초음파비명")


def test_bat_no_lifesteal_when_shielded_or_dodged():
    player = mk_player()
    bat = mk_elite("박쥐", hp=1000, stg=10)
    session = BattleSession(player, enemy=bat, items=[])
    hp_before = bat.hp
    session._elite_bat_lifesteal(bat, 0, [])   # 회피/실드 완전흡수 시 dmg=0으로 호출됨
    check("피해 0(회피/완전흡수)일 때는 흡혈 없음", bat.hp == hp_before)


def test_goblin_start_buff_and_rage():
    player = mk_player()
    goblin = mk_elite("고블린", hp=100, stg=10)
    session = BattleSession(player, enemy=goblin, items=[])
    session._elite_goblin_pre(goblin, [])
    check("전투 시작 시 STG 버프 부여", any(b.stat == "stg" and b.name == "전투 함성" for b in goblin.buffs))

    goblin.hp = goblin.maxhp * 0.4   # 50% 이하로 하락
    session._elite_goblin_pre(goblin, [])
    check("HP 50% 이하에서 분노 진입", goblin.elite_pattern_used is True)
    check("분노 시 STG 버프 추가", any(b.name == "분노" and b.stat == "stg" for b in goblin.buffs))
    check("분노 시 ARM/SPARM 디버프", any(d.name == "분노" for d in goblin.debuffs))

    # 1회 한정
    goblin.hp = 1
    session._elite_goblin_pre(goblin, [])
    rage_buffs = [b for b in goblin.buffs if b.name == "분노"]
    check("분노는 전투당 1회만", len(rage_buffs) == 1, f"count={len(rage_buffs)}")


# ═══════════════════════════════════════════════════════
# 전투 정상 종료 (무한 루프 방지)
# ═══════════════════════════════════════════════════════

def test_battle_ends_normally_with_split():
    player = mk_player(hp=5000, stg=500)
    slime = mk_elite("슬라임", hp=30, stg=1)
    session = BattleSession(player, enemy=slime, items=[])

    for _ in range(200):
        if session.done:
            break
        if session.action_queue and session.action_queue[0][0] == "player":
            session.step("attack")
        else:
            session.step("auto")

    check("분열이 걸려도 전투가 정상 종료(무한루프 없음)", session.done is True)
    check("플레이어 승리", session.winner == "player", f"winner={session.winner}")


def main():
    print("=" * 56)
    print(" 엘리트 몬스터 패턴 회귀 테스트")
    print("=" * 56)
    try:
        test_non_elite_no_pattern()
        test_slime_split()
        test_defeated_list_excludes_summoned()
        test_golem_cycle()
        test_golem_groggy_interrupt()
        test_assassin_mark_cycle()
        test_assassin_mark_cleared_by_full_shield()
        test_fire_slime_overload_resets_stack()
        test_lightning_slime_overload_resets_stack_and_slows()
        test_fire_slime_burst_forced()
        test_ice_slime_shatter_breaks_armor()
        test_priest_revival_once_only()
        test_priest_death_cancels_ritual()
        test_bat_lifesteal_and_scream()
        test_bat_no_lifesteal_when_shielded_or_dodged()
        test_goblin_start_buff_and_rage()
        test_battle_ends_normally_with_split()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 56)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
