"""
verify_multi_v2.py
─────────────────────────────────────────────
패치 v2 검증 — 전사 패시브 약화 + 다대일 시뮬레이션

실행:
  cd /Users/kimyongkeun/Documents/AI_RPG_Engine
  python3 verify_multi_v2.py

검증 항목:
  [Test A] 전사 패시브 약화 효과
    - 4직업 × 박쥐 1대1 (Lv10) 승률 측정
    - 전사가 다른 직업과 비슷한 수준이어야 함 (이전엔 +76.5%p 과강)

  [Test B] 사제 단독 1대1
    - 4직업 × 사제 1대1 — 사제는 약하게 잡혀야 함

  [Test C] 다대일 vs 사제 포함
    - 고블린×2 (사제 없음) vs 고블린+사제 (사제 포함)
    - 사제 포함 시 승률이 명확히 떨어져야 함 → 전략적 압박 검증
"""
from __future__ import annotations
import sys
import os
import contextlib
import io

# 경로 설정
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ["game", "ai", "core"]:
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, ROOT)

from game.Player_Class import create_player_by_job
from game.Skill        import Ply_Skill
from game.Lv           import LV_
from game.Enemy_Class  import (
    Make_Goblin, Make_Bat, Make_Slime, Make_Golem,
    Make_Ghost, Make_Assassin, Make_Priest,
)
from ai.Battle_Engine  import EntitySnapshot
from ai.Simulator      import BattleSimulator, MultiBattleSimulator


# ─────────────────────────────────────────────
# 헬퍼: 직업별 Lv10 플레이어 스냅샷 생성
# ─────────────────────────────────────────────

def _make_player_snap(job: str, target_lv: int = 10) -> EntitySnapshot:
    """직업별 Lv10 플레이어 — 스킬 누적 학습 + 풀 HP/MP"""
    p = create_player_by_job(f"{job}A", job)
    p.skill = Ply_Skill(job)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        p.skill.update_skills(1)
        while p.lv < target_lv:
            LV_(p).Get_exp(p, reward_exp=p.maxexp)
            p.skill.update_skills(p.lv)

    snap = EntitySnapshot.from_player(p)
    # 풀 HP/MP + 기본 포션 셋
    snap.hp = snap.maxhp
    snap.mp = snap.maxmp
    snap.items = ["HP_M_potion", "HP_M_potion", "MP_M_potion", "MP_M_potion"]
    return snap


def _enemy_snap(maker, lv=10, grade="중") -> EntitySnapshot:
    return EntitySnapshot.from_enemy(maker(lv, grade))


def _print_row(label: str, win_rate: float, avg_turns: float, avg_hp: float):
    print(f"  {label:<28} {win_rate*100:>6.1f}%   {avg_turns:>5.1f}턴   HP {avg_hp:>5.0f}")


# ─────────────────────────────────────────────
# Test A: 전사 패시브 약화 효과
# ─────────────────────────────────────────────

print("\n" + "=" * 70)
print(" Test A: 전사 패시브 약화 효과 (vs 박쥐 1대1, Lv10)")
print("=" * 70)
print("  목표: 전사가 다른 직업과 비슷한 수준 (이전 과강 +76.5%p 해소 확인)")
print()
print(f"  {'직업':<28} {'승률':>8} {'평균턴':>8} {'잔여HP':>8}")
print("  " + "─" * 60)

for job in ["전사", "마법사", "탱커", "도적"]:
    p_snap = _make_player_snap(job, 10)
    e_snap = _enemy_snap(Make_Bat, 10, "중")
    sim = BattleSimulator(p_snap, e_snap, n=300)
    r = sim.run()
    _print_row(f"{job} vs 박쥐 (1대1)", r.win_rate, r.avg_turns, r.avg_final_hp)


# ─────────────────────────────────────────────
# Test B: 사제 단독 1대1
# ─────────────────────────────────────────────

print("\n" + "=" * 70)
print(" Test B: 사제 단독 1대1 (Lv10)")
print("=" * 70)
print("  목표: 사제는 단독 등장 시 약해야 함 (전사/도적 90%+, 마법사 80%+)")
print()
print(f"  {'직업':<28} {'승률':>8} {'평균턴':>8} {'잔여HP':>8}")
print("  " + "─" * 60)

for job in ["전사", "마법사", "탱커", "도적"]:
    p_snap = _make_player_snap(job, 10)
    e_snap = _enemy_snap(Make_Priest, 10, "중")
    sim = BattleSimulator(p_snap, e_snap, n=300)
    r = sim.run()
    _print_row(f"{job} vs 사제 (1대1)", r.win_rate, r.avg_turns, r.avg_final_hp)


# ─────────────────────────────────────────────
# Test C: 다대일 — 사제 포함 vs 미포함
# ─────────────────────────────────────────────

print("\n" + "=" * 70)
print(" Test C: 다대일 — 사제 포함 vs 미포함 (Lv10)")
print("=" * 70)
print("  목표: 사제 포함 그룹이 미포함 그룹보다 명확히 어려워야 함")
print("        (사제힐로 다른 적이 안 죽는 효과)")
print()
print(f"  {'직업 / 적 조합':<28} {'승률':>8} {'평균턴':>8} {'잔여HP':>8}")
print("  " + "─" * 60)

for job in ["전사", "마법사", "탱커", "도적"]:
    p_snap = _make_player_snap(job, 10)

    # 미포함: 고블린 × 2
    enemies_no_priest = [
        _enemy_snap(Make_Goblin, 10, "중"),
        _enemy_snap(Make_Goblin, 10, "중"),
    ]
    sim1 = MultiBattleSimulator(p_snap, enemies_no_priest, n=200)
    r1 = sim1.run()
    _print_row(f"{job}: 고블린×2", r1.win_rate, r1.avg_turns, r1.avg_final_hp)

    # 포함: 고블린 + 사제
    enemies_with_priest = [
        _enemy_snap(Make_Priest, 10, "중"),
        _enemy_snap(Make_Goblin, 10, "중"),
    ]
    sim2 = MultiBattleSimulator(p_snap, enemies_with_priest, n=200)
    r2 = sim2.run()
    _print_row(f"{job}: 사제+고블린", r2.win_rate, r2.avg_turns, r2.avg_final_hp)

    # 차이
    delta = (r1.win_rate - r2.win_rate) * 100
    print(f"    └ 사제 영향: 승률 {delta:+.1f}%p, 턴 +{r2.avg_turns - r1.avg_turns:.1f}")
    print()

print("=" * 70)
print(" 모든 검증 완료")
print("=" * 70)
print()
print("해석 가이드:")
print("  [Test A] 전사 승률이 마법사/탱커/도적과 ±10%p 이내면 패시브 적정.")
print("           전사가 여전히 +20%p 이상 높으면 maxhp 10% → 8% 추가 하향 검토.")
print("  [Test B] 사제 단독 승률이 모두 80% 이상이면 OK. 70% 미만이면 사제 hp/sparm 하향.")
print("  [Test C] 사제 포함 그룹의 승률이 미포함보다 10%p 이상 낮아야 함 (사제 가치).")
print("           차이가 5%p 미만이면 사제힐 파라미터 (cap 0.40 → 0.50) 검토.")
