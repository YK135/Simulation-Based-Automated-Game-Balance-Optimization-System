"""
Simulator.py
─────────────────────────────────────────────
N회 반복 배틀 시뮬레이션 + 승률 기반 몬스터 스탯 역산.

밸런싱 고도화:
  - 플레이어 현재 HP/MP 비율 반영
  - 스킬 기대 데미지 반영
  - 보유 아이템 수량 반영
  → 플레이어 상태가 좋을수록 몬스터를 강하게, 나쁠수록 약하게
"""

from typing import Optional, List, Tuple
import copy
import statistics
from dataclasses import dataclass

from ai.Battle_Engine import BattleEngine, EntitySnapshot, SKILL_META
from ai.Auto_AI import PlayerAI, EnemyAI


# ────────────────────────────────────────────
# 시뮬레이션 결과
# ────────────────────────────────────────────

@dataclass
class SimulationResult:
    win_rate:       float
    total_runs:     int
    player_wins:    int
    avg_turns:      float
    avg_final_hp:   float
    win_rate_label: str


# ────────────────────────────────────────────
# 플레이어 전투력 지수 계산
# ────────────────────────────────────────────

class PlayerPowerIndex:
    """
    플레이어 현재 상태를 0.0~2.0 지수로 환산.
    1.0 = 완전 회복 + 스킬 없음 기준선
    1.0 초과 = 강한 상태 → 몬스터 더 강하게
    1.0 미만 = 약한 상태 → 몬스터 더 약하게
    """

    @staticmethod
    def calc(player: EntitySnapshot) -> float:
        index = 1.0

        # ── 1. HP 비율 반영 ──
        # HP가 낮을수록 불리 → index 감소
        hp_ratio = player.hp / player.maxhp if player.maxhp > 0 else 1.0
        if hp_ratio >= 0.8:
            index += 0.15       # 체력 충분 → 강한 몬스터
        elif hp_ratio >= 0.5:
            index += 0.0        # 보통
        elif hp_ratio >= 0.3:
            index -= 0.15       # 체력 위험
        else:
            index -= 0.30       # 체력 매우 위험

        # ── 2. MP 비율 + 스킬 기대 데미지 반영 ──
        mp_ratio = player.mp / player.maxmp if player.maxmp > 0 else 0.0
        skill_power = PlayerPowerIndex._skill_expected_dmg(player)

        if player.learned_skills:
            if mp_ratio >= 0.7 and skill_power > 0:
                index += 0.20   # MP 충분 + 강한 스킬
            elif mp_ratio >= 0.4:
                index += 0.10   # MP 보통
            elif mp_ratio < 0.2:
                index -= 0.10   # MP 고갈 → 스킬 못 씀
        else:
            index -= 0.10       # 스킬 없음 → 불리

        # ── 3. 아이템 수량 반영 ──
        hp_potions = sum(1 for i in player.items if "HP" in i)
        mp_potions = sum(1 for i in player.items if "MP" in i)

        if hp_potions >= 3:
            index += 0.15
        elif hp_potions >= 1:
            index += 0.07
        else:
            index -= 0.10       # 포션 없음 → 불리

        if mp_potions >= 2 and player.learned_skills:
            index += 0.08

        # ── 4. 스탯 자체 수준 반영 ──
        # stg/sp 기반 원킬 가능성
        avg_stat = max(player.stg, player.sp)
        if avg_stat >= 15:
            index += 0.10
        elif avg_stat <= 5:
            index -= 0.10

        # 범위 제한
        return max(0.4, min(2.0, index))

    @staticmethod
    def _skill_expected_dmg(player: EntitySnapshot) -> float:
        """보유 스킬 중 최고 기대 데미지 반환"""
        best = 0.0
        for skill in player.learned_skills:
            meta = SKILL_META.get(skill)
            if not meta:
                continue
            if player.mp < meta["mp"]:
                continue
            base_stat = player.stg if meta["type"] == "physical" else player.sp
            dmg = base_stat * meta["mult"] * meta["hits"]
            if dmg > best:
                best = dmg
        return best


# ────────────────────────────────────────────
# 배틀 시뮬레이터
# ────────────────────────────────────────────

class BattleSimulator:
    """N회 반복 시뮬레이션 → 승률 반환"""

    def __init__(
        self,
        player: EntitySnapshot,
        enemy:  EntitySnapshot,
        n:      int = 500,
        player_ai_mode: str = "balanced",
    ):
        self.player_template = player
        self.enemy_template  = enemy
        self.n               = n
        self.player_ai       = PlayerAI(player_ai_mode)
        self.enemy_ai        = EnemyAI()

    def run(self) -> SimulationResult:
        wins      = 0
        turn_list = []
        hp_list   = []

        for _ in range(self.n):
            p_snap = copy.deepcopy(self.player_template)
            e_snap = copy.deepcopy(self.enemy_template)
            engine = BattleEngine(p_snap, e_snap)
            result = engine.run(self.player_ai, self.enemy_ai)

            if result.winner == "player":
                wins += 1
            turn_list.append(result.total_turns)
            hp_list.append(result.final_player_hp)

        win_rate = wins / self.n
        return SimulationResult(
            win_rate=round(win_rate, 4),
            total_runs=self.n,
            player_wins=wins,
            avg_turns=round(statistics.mean(turn_list), 1),
            avg_final_hp=round(statistics.mean(hp_list), 1),
            win_rate_label=self._label(win_rate),
        )

    @staticmethod
    def _label(wr: float) -> str:
        if wr <= 0.45:   return f"강함 ({wr*100:.1f}%)"
        elif wr <= 0.65: return f"중간 ({wr*100:.1f}%)"
        else:            return f"약함 ({wr*100:.1f}%)"


# ────────────────────────────────────────────
# 스탯 역산기 — 플레이어 상태 반영 버전
# ────────────────────────────────────────────

class StatTuner:
    """
    목표 승률이 되도록 몬스터 스탯을 이진 탐색으로 조정.
    플레이어 전투력 지수(PowerIndex)로 목표 승률을 동적 보정.

    예시:
      플레이어 HP 20%, 포션 없음 → PowerIndex 낮음
      → 목표 승률을 올려서 더 약한 몬스터 생성 (플레이어 보호)

      플레이어 HP 100%, 포션 3개, 강한 스킬 → PowerIndex 높음
      → 목표 승률을 낮춰서 더 강한 몬스터 생성 (긴장감 유지)
    """

    # 기본 목표 승률
    BASE_TARGET = {
        "hard":   0.45,
        "normal": 0.60,
        "easy":   0.70,
    }
    TOLERANCE = 0.03
    MAX_ITER  = 20
    SIM_N     = 300

    def __init__(self, player: EntitySnapshot, base_enemy: EntitySnapshot):
        self.player     = player
        self.base_enemy = base_enemy

        # 플레이어 전투력 지수 계산
        self.power_index = PlayerPowerIndex.calc(player)

    def _adjusted_target(self, difficulty: str) -> float:
        """
        플레이어 전투력 지수로 목표 승률 보정.

        PowerIndex > 1.0 (강한 상태) → 목표 승률 감소 (더 강한 몬스터)
        PowerIndex < 1.0 (약한 상태) → 목표 승률 증가 (더 약한 몬스터)

        보정 범위: ±0.15
        """
        base   = self.BASE_TARGET[difficulty]
        delta  = (1.0 - self.power_index) * 0.15
        target = base + delta
        return round(max(0.20, min(0.85, target)), 3)

    def tune(self, difficulty: str) -> Tuple:
        target = self._adjusted_target(difficulty)

        lo, hi     = 0.1, 5.0
        best_enemy = copy.deepcopy(self.base_enemy)
        best_sim   = None

        for _ in range(self.MAX_ITER):
            mid   = (lo + hi) / 2
            enemy = self._scale_enemy(mid)
            sim   = BattleSimulator(self.player, enemy, n=self.SIM_N).run()

            if abs(sim.win_rate - target) <= self.TOLERANCE:
                best_enemy = enemy
                best_sim   = sim
                break

            if sim.win_rate > target:
                lo = mid   # 적이 너무 약함 → 강하게
            else:
                hi = mid   # 적이 너무 강함 → 약하게

            best_enemy = enemy
            best_sim   = sim

        # 최종 검증
        final_sim = BattleSimulator(self.player, best_enemy, n=500).run()
        return best_enemy, final_sim

    def _scale_enemy(self, scale: float) -> EntitySnapshot:
        e = copy.deepcopy(self.base_enemy)
        e.hp    = max(1.0, e.hp    * scale)
        e.maxhp = max(1.0, e.maxhp * scale)
        e.stg   = max(1.0, e.stg   * scale)
        e.arm   = max(0.0, e.arm   * scale)
        e.luc   = max(0.0, e.luc   * scale)
        return e


# ────────────────────────────────────────────
# 몬스터 팩토리
# ────────────────────────────────────────────

BASE_ENEMIES = {
    "고블린": EntitySnapshot(
        name="고블린", hp=75, maxhp=75, mp=0, maxmp=0,
        stg=2, arm=6, sparm=0, sp=0, luc=5, lv=1,
    ),
    "박쥐": EntitySnapshot(
        name="박쥐", hp=15, maxhp=15, mp=0, maxmp=0,
        stg=5, arm=5, sparm=0, sp=0, luc=0, lv=1,
    ),
}


class MonsterFactory:
    """플레이어 상태 기반으로 강/중/약 3종 몬스터를 자동 생성."""

    def __init__(self, player: EntitySnapshot, enemy_type: str = "고블린"):
        self.player     = player
        self.base_enemy = BASE_ENEMIES.get(enemy_type, BASE_ENEMIES["고블린"])
        self.tuner      = StatTuner(player, self.base_enemy)

    def generate_all(self, verbose: bool = True) -> dict:
        results = {}
        labels  = {"hard": "강함", "normal": "중간", "easy": "약함"}

        if verbose:
            pi = self.tuner.power_index
            status = "강함" if pi > 1.1 else ("약함" if pi < 0.9 else "보통")
            print(f"  [밸런싱] 플레이어 전투력 지수: {pi:.2f} ({status})")
            for diff in ["hard", "normal", "easy"]:
                adj = self.tuner._adjusted_target(diff)
                print(f"    {labels[diff]} 목표 승률: {adj*100:.0f}%")

        for diff in ["hard", "normal", "easy"]:
            if verbose:
                print(f"  [{labels[diff]}] 계산 중...", end=" ", flush=True)

            enemy_snap, sim = self.tuner.tune(diff)

            if verbose:
                print(f"완료 — 승률 {sim.win_rate*100:.1f}% | "
                      f"HP {enemy_snap.hp:.0f} | STG {enemy_snap.stg:.1f}")

            results[diff] = (enemy_snap, sim)

        return results