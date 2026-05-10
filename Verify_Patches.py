"""
verify_patches.py
─────────────────────────────────────────────
패치 검증용 시뮬레이션 — 모든 코드 반영 후 프로젝트 루트에서 실행:
  cd /Users/kimyongkeun/Documents/AI_RPG_Engine
  python3 verify_patches.py

검증 항목:
  1. 슬라임/골렘 상성이 물리/마법 데미지에 정상 적용
  2. 사제 단독 전투 — 홀리볼트 사용 + 기본 동작
  3. 사제+고블린 다대일 — 사제힐로 고블린 회복 발동
  4. 슬래시1 (AoE) — 다대일에서 모든 적에게 데미지 (MP는 한 번만 차감)
"""
from __future__ import annotations
import sys
import os
import statistics

# 경로 설정 (프로젝트 루트에서 실행 가정)
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ["game", "ai", "core"]:
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, ROOT)

from ai.Battle_Engine import EntitySnapshot, DamageCalc, SKILL_META
from game.Enemy_Class import Make_Goblin, Make_Slime, Make_Golem, Make_Priest
from ai.Battlesession import BattleSession


def _player_snap(job="전사", lv=10):
    """검증용 전사 Lv10 스냅샷"""
    return EntitySnapshot(
        name="테스트전사",
        hp=300, maxhp=300,
        mp=80, maxmp=80,
        stg=20, arm=14, sparm=8, sp=6,
        luc=10, lv=lv, spd=10,
        learned_skills=["강타1", "슬래시1", "강화1"],
        job=job,
    )


def _enemy_snap(maker, lv=10, grade="중"):
    """Make_X 결과를 EntitySnapshot으로 변환"""
    unit = maker(lv, grade)
    return EntitySnapshot(
        name=unit.name,
        hp=unit.hp, maxhp=unit.hp,
        mp=getattr(unit, "mp", 0), maxmp=getattr(unit, "mp", 0),
        stg=unit.stg, arm=unit.arm, sparm=unit.sparm,
        sp=getattr(unit, "sp", 0),
        luc=unit.luc, lv=unit.lv,
        spd=getattr(unit, "spd", 10),
        physical_resist=getattr(unit, "physical_resist", 1.0),
        magical_resist=getattr(unit, "magical_resist", 1.0),
        enemy_type=getattr(unit, "enemy_type", unit.name),
    )


# ─────────────────────────────────────────────
# 검증 1: 상성 (슬라임 vs 골렘)
# ─────────────────────────────────────────────
print("=" * 60)
print("검증 1: 물리/마법 상성")
print("=" * 60)

slime = _enemy_snap(Make_Slime, lv=5)
golem = _enemy_snap(Make_Golem, lv=5)

print(f"슬라임 — physical_resist: {slime.physical_resist}, magical_resist: {slime.magical_resist}")
print(f"골렘   — physical_resist: {golem.physical_resist}, magical_resist: {golem.magical_resist}")
print()

# 동일 STG=30, SP=30 가상 어태커로 1000회 평균 비교
class _Fake:
    def __init__(self):
        self.stg = 30; self.sp = 30; self.luc = 10
        self.has_attacked = True; self.first_attack_bonus = 1.0
        self.job = ""
    def effective_stg(self): return self.stg
fake = _Fake()


def _avg(target, dmg_type, n=1000):
    samples = []
    for _ in range(n):
        if dmg_type == "physical":
            d, _, _ = DamageCalc.physical(
                fake.stg, fake.luc, target.arm, target.luc,
                skill_mult=1.0, attacker=fake, defender=target,
            )
        else:
            d, _, _ = DamageCalc.magical(
                fake.sp, fake.luc, target.sparm, target.luc,
                skill_mult=1.0, attacker=fake, defender=target,
            )
        samples.append(d)
    return statistics.mean(samples)


phys_slime = _avg(slime, "physical")
mag_slime  = _avg(slime, "magical")
phys_golem = _avg(golem, "physical")
mag_golem  = _avg(golem, "magical")

print(f"슬라임에 물리 평균: {phys_slime:.1f}  (저항 0.65)")
print(f"슬라임에 마법 평균: {mag_slime:.1f}  (약점 1.10)")
print(f"  → 마법/물리 비율: {mag_slime/phys_slime:.2f}배  (1.69배 근접 기대)")
print()
print(f"골렘에 물리 평균: {phys_golem:.1f}  (약점 1.10)")
print(f"골렘에 마법 평균: {mag_golem:.1f}  (저항 0.65)")
print(f"  → 물리/마법 비율: {phys_golem/mag_golem:.2f}배  (1.69배 근접 기대)")
print()


# ─────────────────────────────────────────────
# 검증 2: 사제 단독 — 홀리볼트 동작
# ─────────────────────────────────────────────
print("=" * 60)
print("검증 2: 사제 1대1 (사제힐 발동 안 함, 홀리볼트만)")
print("=" * 60)

p = _player_snap()
priest = _enemy_snap(Make_Priest, lv=10)
print(f"사제 스펙 — HP {priest.hp}, MP {priest.mp}, SP {priest.sp}, SPD {priest.spd}")

session = BattleSession(p, enemy=priest, items=["HP_M_potion"] * 3)
state = session.step("attack")
print("플레이어 공격 후:")
for m in state["messages"][-6:]:
    print(f"  {m}")
print()


# ─────────────────────────────────────────────
# 검증 3: 사제 + 고블린 다대일 — 힐 발동
# ─────────────────────────────────────────────
print("=" * 60)
print("검증 3: 사제+고블린 다대일 (사제힐 발동 확인)")
print("=" * 60)

p = _player_snap()
priest = _enemy_snap(Make_Priest, lv=10)
goblin = _enemy_snap(Make_Goblin, lv=10)
# 고블린을 의도적으로 HP 낮게 — 사제힐 트리거
goblin.hp = goblin.maxhp * 0.4

session = BattleSession(p, enemies=[priest, goblin], items=["HP_M_potion"] * 3)
print(f"초기 — 사제 HP {int(session.enemies[0].hp)}, "
      f"고블린 HP {int(session.enemies[1].hp)}/{int(session.enemies[1].maxhp)}")

# 플레이어가 슬래시1 (AoE) 사용
state = session.step("skill:슬래시1")
print()
print("플레이어 슬래시1 (AoE) 사용 후:")
for m in state["messages"]:
    print(f"  {m}")
print()
print(f"결과 — 사제 HP {int(session.enemies[0].hp)}, "
      f"고블린 HP {int(session.enemies[1].hp)}")
print()


# ─────────────────────────────────────────────
# 검증 4: AoE 데미지 정확성
# ─────────────────────────────────────────────
print("=" * 60)
print("검증 4: AoE (슬래시1) 다중 적 데미지")
print("=" * 60)

p = _player_snap()
g1 = _enemy_snap(Make_Goblin, lv=5)
g2 = _enemy_snap(Make_Goblin, lv=5)
g3 = _enemy_snap(Make_Goblin, lv=5)

session = BattleSession(p, enemies=[g1, g2, g3], items=[])
print(f"초기 HP — 고블린1: {int(session.enemies[0].hp)}, "
      f"고블린2: {int(session.enemies[1].hp)}, 고블린3: {int(session.enemies[2].hp)}")
print(f"초기 MP: {int(session.player.mp)}")

state = session.step("skill:슬래시1")
print()
print("슬래시1 사용 후:")
for m in state["messages"]:
    print(f"  {m}")
print()
print(f"결과 HP — 고블린1: {int(session.enemies[0].hp)}, "
      f"고블린2: {int(session.enemies[1].hp)}, 고블린3: {int(session.enemies[2].hp)}")
print(f"플레이어 MP: {int(session.player.mp)}  (슬래시1 = MP 12, 한 번만 차감되어야 함)")
print()
print("=" * 60)
print("모든 검증 완료")
print("=" * 60)
