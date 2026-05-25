"""
Verify_ATB.py
─────────────────────────────────────────────
새 ATB 시스템 (큐 기반 턴제 + 추가 행동권 + ATB 이월) 종합 검증.

검증 항목:
  Test A — 4직업 × 5몬스터 × 3난이도 1대1 승률
  Test B — 다대일 (3마리 그룹) 승률
  Test C — 빠른 직업(도적)의 추가 행동권(BONUS) 발동 빈도
  Test D — ATB 이월 효과 (player_atb 초기값 검증)

실행:
  python Verify_ATB.py
"""
import sys
import os
import copy
import statistics
from typing import Dict, List, Tuple
from collections import defaultdict

# 프로젝트 루트 + 서브 디렉토리를 path에 추가 (App.py 방식)
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ["game", "ai", "core", "interface"]:
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, ROOT)

# import 폴백 (ai/ 디렉토리 + 평탄 구조 둘 다 지원)
try:
    from ai.Battle_Engine import EntitySnapshot
    from ai.Simulator import MultiBattleSimulator, BattleSimulator
except ModuleNotFoundError:
    from ai.Battle_Engine import EntitySnapshot
    from ai.Simulator import MultiBattleSimulator, BattleSimulator
from game.Enemy_Class import (
    Make_Goblin, Make_Bat, Make_Slime,
    Make_Golem, Make_Ghost, Make_Assassin, Make_Priest,
)
from game.Player_Class import create_player_by_job
from game.Skill import Ply_Skill


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def _make_player_snap(job: str, lv: int = 10) -> EntitySnapshot:
    """직업별 Lv 플레이어 스냅 생성 (스킬 학습 완료)"""
    p = create_player_by_job("TEST", job)
    # 레벨업 시뮬
    for _ in range(lv - 1):
        p.lv += 1
        p.maxhp = int(p.maxhp * 1.15)
        p.hp = p.maxhp
        p.maxmp = int(p.maxmp * 1.1)
        p.mp = p.maxmp
        p.stg *= 1.08
        p.arm *= 1.08
        p.sparm *= 1.08
        p.sp *= 1.08
        p.spd *= 1.05
        p.luc *= 1.05

    # 스킬 학습
    p.skill = Ply_Skill(job)
    p.skill.update_skills(lv)

    snap = EntitySnapshot.from_player(p)
    return snap


def _enemy_snap(factory, lv: int, difficulty: str = "중") -> EntitySnapshot:
    """몬스터 EntitySnapshot 생성"""
    e = factory(lv, difficulty)
    return EntitySnapshot.from_enemy(e)


def _print_header(text: str):
    print("\n" + "=" * 70)
    print(f" {text}")
    print("=" * 70)


def _print_row(label: str, wr: float, turns: float, hp: float):
    bar_len = int(wr * 30)
    bar = "█" * bar_len + "░" * (30 - bar_len)
    print(f"  {label:<30} {wr*100:>5.1f}%  {bar}  턴{turns:>4.1f}  HP{hp:>5.1f}")


# ─────────────────────────────────────────────
# Test A — 4직업 × 5몬스터 × 3난이도 (1대1)
# ─────────────────────────────────────────────

def test_A_balance_matrix():
    _print_header("Test A: 4직업 × 5몬스터 × 3난이도 (1대1, Lv10, n=150)")

    jobs = ["전사", "마법사", "탱커", "도적"]
    monsters = [
        ("고블린", Make_Goblin),
        ("박쥐", Make_Bat),
        ("슬라임", Make_Slime),
        ("골렘", Make_Golem),
        ("유령", Make_Ghost),
    ]
    difficulties = [("쉬움", "하"), ("중간", "중"), ("어려움", "상")]

    # 결과 저장: results[(job, monster_name, diff_label)] = (wr, turns, hp)
    results: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}

    for job in jobs:
        print(f"\n  ── {job} ──")
        p_snap = _make_player_snap(job, 10)

        for mon_name, factory in monsters:
            for diff_label, diff_code in difficulties:
                e_snap = _enemy_snap(factory, 10, diff_code)
                sim = BattleSimulator(p_snap, e_snap, n=150)
                r = sim.run()
                results[(job, mon_name, diff_label)] = (
                    r.win_rate, r.avg_turns, r.avg_final_hp
                )
                _print_row(
                    f"{mon_name}({diff_label})",
                    r.win_rate, r.avg_turns, r.avg_final_hp
                )

    return results


def _summary_by_job(results) -> Dict[str, Dict]:
    """직업별 평균 승률/턴 요약"""
    by_job = defaultdict(lambda: {"wins": [], "turns": [], "hps": []})

    for (job, mon, diff), (wr, t, hp) in results.items():
        by_job[job]["wins"].append(wr)
        by_job[job]["turns"].append(t)
        by_job[job]["hps"].append(hp)

    summary = {}
    for job, data in by_job.items():
        summary[job] = {
            "avg_wr": statistics.mean(data["wins"]),
            "avg_turns": statistics.mean(data["turns"]),
            "avg_hp": statistics.mean(data["hps"]),
            "wr_std": statistics.stdev(data["wins"]) if len(data["wins"]) > 1 else 0,
        }
    return summary


# ─────────────────────────────────────────────
# Test B — 다대일 (3마리 그룹)
# ─────────────────────────────────────────────

def test_B_multi_target():
    _print_header("Test B: 다대일 (3마리 혼합 그룹, Lv10, n=100)")

    jobs = ["전사", "마법사", "탱커", "도적"]
    groups = [
        ("고블린×3",       [Make_Goblin, Make_Goblin, Make_Goblin]),
        ("박쥐×3",        [Make_Bat, Make_Bat, Make_Bat]),
        ("혼합 (G+B+S)",   [Make_Goblin, Make_Bat, Make_Slime]),
        ("사제+고블린×2",   [Make_Priest, Make_Goblin, Make_Goblin]),
        ("골렘+슬라임+유령", [Make_Golem, Make_Slime, Make_Ghost]),
    ]

    results = {}
    for job in jobs:
        print(f"\n  ── {job} ──")
        p_snap = _make_player_snap(job, 10)

        for group_name, factories in groups:
            e_snaps = [_enemy_snap(f, 10, "중") for f in factories]
            sim = MultiBattleSimulator(p_snap, e_snaps, n=100)
            r = sim.run()
            results[(job, group_name)] = (
                r.win_rate, r.avg_turns, r.avg_final_hp
            )
            _print_row(group_name, r.win_rate, r.avg_turns, r.avg_final_hp)

    return results


# ─────────────────────────────────────────────
# Test C — 추가 행동권(BONUS) 효과 분석
# ─────────────────────────────────────────────

def test_C_bonus_action():
    """
    빠른 직업이 추가 행동권을 얼마나 자주 발동하는지 측정.
    도적 (SPD 14+) vs 전사 (SPD 10) 비교.

    측정 방법:
      - 100번 시뮬 중 BONUS 메시지가 나온 횟수 측정
      - 평균 BONUS 발동률 (per battle)
    """
    _print_header("Test C: 추가 행동권(BONUS) 발동 빈도")

    # BattleSession을 직접 호출해서 메시지 분석
    try:
        from ai.Battlesession import BattleSession
    except ModuleNotFoundError:
        from ai.Battlesession import BattleSession

    from ai.Auto_AI import PlayerAI
    from ai.Simulator import MultiBattleSimulator

    jobs = ["도적", "전사"]   # 도적이 SPD 빠름 (14+) vs 전사 (10)

    for job in jobs:
        print(f"\n  ── {job} ──")
        p_snap = _make_player_snap(job, 10)
        print(f"  SPD = {p_snap.spd:.1f}")

        bonus_counts = []
        for _ in range(50):
            session = BattleSession(
                copy.deepcopy(p_snap),
                enemies=[_enemy_snap(Make_Goblin, 10, "중")],
                items=[],
                is_boss=False,
            )
            player_ai = PlayerAI("balanced")

            state = session.step("status")
            next_actor = state.get("next_actor", "player")
            bonus_count = 0

            for _ in range(200):
                if session.done or next_actor == "done":
                    break

                # BONUS 메시지 카운트
                msgs = state.get("messages", [])
                bonus_count += sum(1 for m in msgs if "BONUS" in m or "추가 행동" in m)

                if next_actor == "enemy":
                    state = session.step("auto")
                else:
                    target = session._current_target()
                    if target is None:
                        break
                    action_obj = player_ai(session.player, target)
                    if action_obj.action_type == "attack":
                        action = "attack"
                    elif action_obj.action_type == "skill":
                        action = f"skill:{action_obj.detail}"
                    elif action_obj.action_type == "item":
                        action = f"item:{action_obj.detail}"
                    else:
                        action = "attack"
                    state = session.step(action)

                next_actor = state.get("next_actor", "player")

            bonus_counts.append(bonus_count)

        avg_bonus = statistics.mean(bonus_counts) if bonus_counts else 0
        max_bonus = max(bonus_counts) if bonus_counts else 0
        print(f"  평균 BONUS 발동: {avg_bonus:.2f}회/전투")
        print(f"  최대 BONUS 발동: {max_bonus}회/전투")
        print(f"  발동률 (BONUS > 0): {sum(1 for b in bonus_counts if b > 0) / len(bonus_counts) * 100:.0f}%")


# ─────────────────────────────────────────────
# Test D — ATB 이월 검증
# ─────────────────────────────────────────────

def test_D_atb_carryover():
    """
    전투 종료 후 atb_remainder가 player에 저장되는지 검증.
    실게임은 player_original로 작동하지만,
    시뮬에서는 player_original=None 폴백 동작 확인.
    """
    _print_header("Test D: ATB 이월 동작 검증")

    try:
        from ai.Battlesession import BattleSession
    except ModuleNotFoundError:
        from ai.Battlesession import BattleSession

    from ai.Auto_AI import PlayerAI

    p = create_player_by_job("이월테스트", "도적")
    p.skill = Ply_Skill("도적")
    p.skill.update_skills(5)
    # atb_remainder는 Player 클래스 필드여야 함
    p.atb_remainder = 0.0

    print(f"\n  도적 SPD: {p.spd}")
    print(f"  전투 1 시작 atb_remainder: {p.atb_remainder}")

    # ── 전투 1 ──
    p_snap = EntitySnapshot.from_player(p)
    e_snap = _enemy_snap(Make_Goblin, 5, "중")
    session = BattleSession(
        copy.deepcopy(p_snap),
        enemies=[copy.deepcopy(e_snap)],
        items=[],
        is_boss=False,
        player_original=p,   # ★ 이월용 원본 Player
    )
    print(f"  전투 1 시작 player_atb: {session.player_atb}")

    player_ai = PlayerAI("balanced")
    state = session.step("status")
    next_actor = state.get("next_actor", "player")

    for _ in range(200):
        if session.done or next_actor == "done":
            break
        if next_actor == "enemy":
            state = session.step("auto")
        else:
            target = session._current_target()
            if target is None:
                break
            action_obj = player_ai(session.player, target)
            if action_obj.action_type == "attack":
                action = "attack"
            elif action_obj.action_type == "skill":
                action = f"skill:{action_obj.detail}"
            else:
                action = "attack"
            state = session.step(action)
        next_actor = state.get("next_actor", "player")

    print(f"  전투 1 종료 winner: {session.winner}")
    print(f"  전투 1 종료 session.player_atb: {session.player_atb:.1f}")
    print(f"  전투 1 종료 player.atb_remainder: {p.atb_remainder:.1f}")

    if p.atb_remainder > 0:
        print("  ✅ ATB 이월 정상 작동")
    else:
        print("  ⚠ ATB가 0 — 패배 시나리오일 수 있음")

    # ── 전투 2 ──
    print(f"\n  전투 2 시작 player.atb_remainder: {p.atb_remainder:.1f}")

    session2 = BattleSession(
        EntitySnapshot.from_player(p),
        enemies=[_enemy_snap(Make_Goblin, 5, "중")],
        items=[],
        is_boss=False,
        player_original=p,
    )
    print(f"  전투 2 시작 session.player_atb: {session2.player_atb:.1f}")

    if abs(session2.player_atb - p.atb_remainder) < 0.1:
        print("  ✅ 이월값이 정확히 전달됨")
    else:
        print("  ⚠ 이월값 불일치")


# ─────────────────────────────────────────────
# 메인 — 모든 테스트 실행
# ─────────────────────────────────────────────

def main():
    print("\n" + "█" * 70)
    print(" 새 ATB 시스템 종합 검증")
    print(" 큐 기반 턴제 + 추가 행동권(BONUS) + ATB 이월")
    print("█" * 70)

    # Test A
    results_A = test_A_balance_matrix()
    summary_A = _summary_by_job(results_A)

    _print_header("Test A 요약 — 직업별 평균")
    print(f"  {'직업':<8} {'평균승률':>10} {'평균턴':>10} {'평균HP':>10} {'표준편차':>10}")
    print("  " + "─" * 60)
    for job in ["전사", "마법사", "탱커", "도적"]:
        s = summary_A.get(job, {})
        print(f"  {job:<8} "
              f"{s.get('avg_wr', 0)*100:>8.1f}% "
              f"{s.get('avg_turns', 0):>10.1f} "
              f"{s.get('avg_hp', 0):>10.1f} "
              f"{s.get('wr_std', 0)*100:>9.2f}%")

    # Test B
    results_B = test_B_multi_target()

    # Test C
    test_C_bonus_action()

    # Test D
    test_D_atb_carryover()

    print("\n" + "█" * 70)
    print(" 모든 검증 완료")
    print("█" * 70)
    print()
    print("해석 가이드:")
    print("  [Test A] 직업별 평균 승률이 ±15%p 이내면 밸런스 양호")
    print("           20%p 이상 차이 나면 해당 직업 패시브/스킬 조정 검토")
    print("  [Test B] 다대일에서 모든 직업이 50%+ 승률이면 다대일 시스템 작동")
    print("           특정 그룹에서 0~20% 승률이면 해당 그룹 난이도 검토")
    print("  [Test C] 도적이 전사보다 BONUS 발동 더 자주 나와야 정상 (SPD 차이)")
    print("           발동률이 60%+ 이면 새 ATB가 게임플레이에 영향 큼")
    print("  [Test D] 이월값이 정확히 전달되면 player_original 메커니즘 OK")


if __name__ == "__main__":
    main()