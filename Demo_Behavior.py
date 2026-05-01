"""
BehaviorAnalyzer 시연 스크립트
─────────────────────────────────────────────
발표에서 보여줄 사용자 행동 패턴 분석 데모.

흐름:
  1. 가짜 플레이어 4명 시뮬 (각 직업별 다른 플레이 스타일)
  2. 각각 30번 전투 데이터 수집
  3. BehaviorAnalyzer가 자동으로 플레이 스타일 분류
  4. 결과 비교 출력

실행:
  python3 demo_behavior.py
"""
import sys, os, copy, io, contextlib
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game.Player_Class import create_player_by_job
from game.Enemy_Class import (
    Make_Goblin, Make_Bat, Make_Slime, Make_Golem, Make_Ghost, Make_Assassin,
)
from game.Lv import LV_
from game.Skill import Ply_Skill
from ai.Battle_Engine import BattleEngine, EntitySnapshot
from ai.Auto_AI import PlayerAI, EnemyAI
from ai.BehaviorAnalyzer import BehaviorAnalyzer


def setup_player(job: str, target_lv: int):
    """플레이어 생성 + 누적 스킬 학습 (게임 흐름과 동일)"""
    p = create_player_by_job(f"{job}A", job)
    skill_sys = Ply_Skill(job)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        skill_sys.update_skills(1)
        while p.lv < target_lv:
            LV_(p).Get_exp(p, reward_exp=p.maxexp)
            skill_sys.update_skills(p.lv)
    return p, list(skill_sys.learned_skills)


def simulate_battles(job: str, lv: int, style: str, n: int = 30):
    """주어진 직업/레벨/스타일로 n번 전투 시뮬"""
    results = []
    p, learned = setup_player(job, lv)

    avail = [Make_Goblin, Make_Bat]
    if lv >= 3:  avail.append(Make_Slime)
    if lv >= 6:  avail.append(Make_Golem)
    if lv >= 7:  avail.append(Make_Ghost)
    if lv >= 10: avail.append(Make_Assassin)

    for i in range(n):
        p_snap = EntitySnapshot(
            name=p.name, hp=p.maxhp, maxhp=p.maxhp, mp=p.maxmp, maxmp=p.maxmp,
            stg=p.stg, arm=p.arm, sparm=p.sparm, sp=p.sp, luc=p.luc,
            lv=p.lv, spd=p.spd, learned_skills=learned,
        )
        enemy = avail[i % len(avail)](lv, "상")
        e_snap = EntitySnapshot.from_enemy(enemy)
        e_snap.has_attacked = False

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = BattleEngine(p_snap, e_snap).run(PlayerAI(style), EnemyAI())
        results.append(result)
    return p, learned, results


def main():
    print("\n" + "=" * 70)
    print("   BehaviorAnalyzer 시연 — 사용자 행동 패턴 자동 분류")
    print("=" * 70 + "\n")

    print("개요:")
    print("  • 4명의 가상 플레이어가 각각 30번 전투")
    print("  • 시뮬은 모두 동일한 환경, 차이는 직업과 플레이 스타일뿐")
    print("  • BehaviorAnalyzer가 행동 비율을 분석해 자동 분류\n")

    analyzer = BehaviorAnalyzer()

    scenarios = [
        ("플레이어 A", "전사",   10, "aggressive",  "공격적 전사"),
        ("플레이어 B", "마법사", 10, "balanced",    "균형 잡힌 마법사"),
        ("플레이어 C", "탱커",   10, "defensive",   "방어적 탱커"),
        ("플레이어 D", "도적",   10, "aggressive",  "공격적 도적"),
    ]

    print("─" * 70)
    print(f"{'플레이어':<10} {'직업':<6} {'스타일':<12} {'분류 결과':<18} "
          f"{'공격%':>7} {'스킬%':>7} {'승률':>6}")
    print("─" * 70)

    summaries = []
    for name, job, lv, style, label in scenarios:
        p, learned, results = simulate_battles(job, lv, style, n=30)
        s = analyzer.analyze(results)
        summaries.append((name, label, s))
        print(f"{name:<10} {job:<6} {style:<12} {s.play_style:<18} "
              f"{s.attack_rate*100:>6.1f}% {s.skill_rate*100:>6.1f}% "
              f"{s.win_rate*100:>5.0f}%")

    print("─" * 70)

    # 요약
    print("\n해석:")
    distinct_labels = set(s[2].play_style for s in summaries)
    print(f"  • 4명 중 {len(distinct_labels)}가지 다른 라벨 자동 생성")
    print(f"  • 같은 직업이라도 스타일에 따라 다르게 분류 가능")
    print(f"  • 행동 비율(공격/스킬/아이템/도망) 기반 규칙 분류")

    print("\n다음 단계 (2학기):")
    print("  • LLM API 연동 → 자연어로 분석 결과 설명")
    print("  • 예: \"플레이어 A는 강타와 연속공격을 선호하는 적극적인 전사형\"")
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()