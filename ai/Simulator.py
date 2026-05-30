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

try:
    from ai.Battle_Engine  import BattleEngine, EntitySnapshot, SKILL_META
    from ai.Auto_AI        import PlayerAI, EnemyAI
    from game.Enemy_Class  import (
        Make_Goblin, Make_Bat,
        Make_Slime, Make_Golem, Make_Ghost, Make_Assassin, Make_Priest,
    )
except ModuleNotFoundError:
    from Battle_Engine import BattleEngine, EntitySnapshot, SKILL_META
    from Auto_AI       import PlayerAI, EnemyAI
    from game.Enemy_Class   import (
        Make_Goblin, Make_Bat,
        Make_Slime, Make_Golem, Make_Ghost, Make_Assassin, Make_Priest,
    )


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

        # ── 5. SPD 유리함 반영 ──
        # 적 기준 SPD(고블린=8, 박쥐=12)와 비교해 빠를수록 ATB 유리 → index 상향
        # 기준선: 10 (전사/마법사 평균)
        spd = getattr(player, "spd", 10.0)
        if spd >= 14:
            index += 0.15   # 도적 등 고SPD → 몬스터 더 강하게
        elif spd >= 12:
            index += 0.08
        elif spd <= 7:
            index -= 0.08   # 느린 직업 → 약간 유리하게

        # 범위 제한
        return max(0.4, min(2.0, index))

    @staticmethod
    def _skill_expected_dmg(player: EntitySnapshot) -> float:
        """
        보유 스킬 중 최고 기대 기여값 반환.
        공격형: 데미지 기대값
        생존형(heal/buff/shield): 생존력 보정치로 환산
        """
        best = 0.0
        for skill in player.learned_skills:
            meta = SKILL_META.get(skill)
            if not meta:
                continue
            if player.mp < meta.get("mp", 0):
                continue

            stype = meta.get("type", "")

            if stype == "physical":
                dmg = player.stg * meta.get("mult", 1.0) * meta.get("hits", 1)

            elif stype == "magical":
                dmg = player.sp * meta.get("mult", 1.0) * meta.get("hits", 1)

            elif stype == "multi_hit":
                # 기대타수: base_prob + luc_mult * LUC 기반 추정 (평균 2.5타)
                expected_hits = min(2.0 + player.luc * 0.05, meta.get("max_hits", 4))
                dmg = player.stg * expected_hits * meta.get("dmg_decay", 0.75)

            elif stype == "tank_attack":
                dmg = (player.arm * meta.get("arm_mult", 1.0)
                       + player.maxhp * meta.get("hp_mult", 0.0))

            elif stype == "counter":
                # 피해를 받기 전이면 낮게 평가
                recent = getattr(player, "last_damage_taken", 0)
                dmg = (recent * meta.get("counter_mult", 0.5)
                       + player.arm * meta.get("arm_mult", 1.0))
                dmg = min(dmg, player.maxhp * meta.get("cap", 1.0))
                dmg *= 0.5  # 조건부 스킬이라 가중치 절반

            elif stype == "heal":
                # 회복량을 생존력 보정치로 환산 (데미지 단위로 표현)
                heal = meta.get("base_heal", 0) + player.sp * meta.get("sp_mult", 0.0)
                dmg  = heal * 0.6  # 회복은 딜 기여보다 약하게 평가

            elif stype == "buff":
                # 스탯 증가 비율 → 기대 딜 증가분으로 환산
                amount = meta.get("buff_amount", 0.0)
                turns  = meta.get("buff_turns", 1)
                stat   = meta.get("buff_stat", "")
                base   = player.stg if stat == "stg" else player.sp if stat == "sp" else 0
                dmg    = base * amount * turns * 0.5

            elif stype == "shield":
                shield_val = player.maxhp * meta.get("shield_mult", 0.0)
                dmg        = shield_val * 0.5  # 방어 기여 절반 환산

            else:
                dmg = 0.0

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

class MultiBattleSimulator:
    """
    1대N 다대일 전투 시뮬레이터.

    BattleSession을 직접 사용해 N회 반복 시뮬 — Digital Twin 원칙:
    실게임 다대일 = 시뮬 다대일 = BattleSession (동일 객체).

    사용 예시:
      from ai.Simulator import MultiBattleSimulator
      from ai.Battle_Engine import EntitySnapshot
      from game.Enemy_Class import Make_Goblin, Make_Priest

      player_snap = EntitySnapshot.from_player(player)
      enemies = [
          EntitySnapshot.from_enemy(Make_Priest(10, "중")),
          EntitySnapshot.from_enemy(Make_Goblin(10, "중")),
      ]
      sim = MultiBattleSimulator(player_snap, enemies, n=300)
      result = sim.run()
      print(f"승률 {result.win_rate*100:.1f}%, 평균 {result.avg_turns}턴")
    """

    def __init__(
        self,
        player: EntitySnapshot,
        enemies: list,            # EntitySnapshot 리스트 (1~3마리)
        n: int = 300,
        items: list = None,
        player_ai_mode: str = "balanced",
        max_turns: int = 100,     # 무한루프 방지 (사제힐로 전투 길어질 수 있음)
    ):
        if not enemies:
            raise ValueError("MultiBattleSimulator: enemies는 최소 1마리 이상이어야 함")
        self.player_template  = player
        self.enemy_templates  = enemies
        self.n                = n
        self.items_template   = list(items or [])
        self.player_ai_mode   = player_ai_mode
        self.max_turns        = max_turns

    def run(self) -> SimulationResult:
        """
        N회 반복 시뮬 → SimulationResult 반환 (★ 새 ATB 시스템 호환).

        새 ATB: step() 응답의 next_actor에 따라 분기.
          - "player": _decide_player_action() 결과로 step
          - "enemy":  step("auto")로 적 자동 행동
          - "done":   루프 종료
        """
        # 지연 import — 순환참조 방지
        try:
            from ai.Battlesession import BattleSession
        except ModuleNotFoundError:
            from Battlesession import BattleSession

        wins = 0
        turn_list = []
        hp_list = []

        # 시뮬용 PlayerAI
        player_ai = PlayerAI(self.player_ai_mode)

        for _ in range(self.n):
            p_snap = copy.deepcopy(self.player_template)
            e_snaps = [copy.deepcopy(e) for e in self.enemy_templates]
            items = list(self.items_template)

            session = BattleSession(
                p_snap,
                enemies=e_snaps,
                items=items,
                is_boss=False,
            )

            # ── 새 ATB: 첫 응답에서 next_actor 받기 ──
            # BattleSession은 __init__에서 큐를 자동 빌드, 첫 step("status")로 상태 조회.
            # 또는 첫 step()을 _decide_player_action으로 호출하기 전에
            # action_queue[0] 확인해서 누구 차례인지 알아낼 수도 있음.
            # 가장 간단한 방법: 매 step 응답의 next_actor 사용.
            # 첫 응답 받기 위해 "status" 호출.
            state = session.step("status")
            next_actor = state.get("next_actor", "player")

            # ── 시뮬 루프 ──
            step_count = 0
            max_steps = self.max_turns * 4   # ATB 추가 행동 고려해 여유 4배

            while not session.done and step_count < max_steps:
                step_count += 1

                if next_actor == "done":
                    break

                if next_actor == "enemy":
                    # 적 자동 행동
                    state = session.step("auto")
                elif next_actor == "player":
                    # 플레이어 AI 결정 후 행동
                    action = self._decide_player_action(session, player_ai)
                    state = session.step(action)
                else:
                    # 예외 (next_actor 미정) — auto로 처리
                    state = session.step("auto")

                next_actor = state.get("next_actor", "player")

            # max_steps 초과 = 미결 → 적 측 승리로 간주 (보수적)
            if not session.done:
                session.winner = "enemy"

            if session.winner == "player":
                wins += 1
            turn_list.append(session.turn)
            hp_list.append(max(0.0, session.player.hp))

        win_rate = wins / self.n
        return SimulationResult(
            win_rate=round(win_rate, 4),
            total_runs=self.n,
            player_wins=wins,
            avg_turns=round(statistics.mean(turn_list), 1),
            avg_final_hp=round(statistics.mean(hp_list), 1),
            win_rate_label=BattleSimulator._label(win_rate),
        )

    @staticmethod
    def _decide_player_action(session, player_ai) -> str:
        """
        PlayerAI는 1대1 기준이므로 살아있는 첫 번째 적을 defender로 사용.
        반환된 Action을 BattleSession이 받는 action 문자열로 변환.
        """
        target = session._current_target()
        if target is None:
            return "attack"  # 폴백 — 사실 호출 전에 done 체크되어 도달 안 함

        action_obj = player_ai(session.player, target)

        if action_obj.action_type == "attack":
            return "attack"
        elif action_obj.action_type == "skill":
            return f"skill:{action_obj.detail}"
        elif action_obj.action_type == "item":
            return f"item:{action_obj.detail}"
        else:
            return "attack"

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

    # ── 몬스터 종류별 기본 목표 승률 ──────────────────
    # 몬스터 컨셉에 맞게 난이도 목표를 차별화.
    # 박쥐는 "유리대포" 컨셉 — HP/STG 낮고 MP/SP 있음. 물리적으로
    # 플레이어가 거의 항상 이김. 목표 승률을 80/90/95%로 설정해서
    # "박쥐 = 청소용 쉬운 몬스터, 마법 크리로 변수" 포지션을 명확화.
    # 고블린은 "균형잡힌 탱커" — 표준 난이도 45/60/70%.
    # _TARGET_BY_NAME에 없는 몬스터는 DEFAULT_TARGET 사용.
    DEFAULT_TARGET = {
        "hard":   0.45,
        "normal": 0.60,
        "easy":   0.70,
    }
    _TARGET_BY_NAME = {
        "박쥐": {
            "hard":   0.80,   # 강한 박쥐도 플레이어가 80% 이김 (유리대포)
            "normal": 0.90,
            "easy":   0.95,
        },
        "고블린": {
            "hard":   0.45,
            "normal": 0.60,
            "easy":   0.70,
        },
        # ── Phase 1 신규 — 역할 기반 ──
        # 상성 몬스터(슬라임/골렘)는 직업에 따라 승률 편차가 큼.
        # → 표준 45/60/70 유지 (시뮬은 PowerIndex로 보정)
        "슬라임": {
            "hard":   0.45,
            "normal": 0.60,
            "easy":   0.70,
        },
        "골렘": {
            "hard":   0.45,
            "normal": 0.60,
            "easy":   0.70,
        },
        # 유령: 회피 변수가 커서 결과 분산 큼 → 표준
        "유령": {
            "hard":   0.45,
            "normal": 0.60,
            "easy":   0.70,
        },
        # 암살자: 위협적이라 강함을 살짝 어렵게(동일하게%) — 첫턴 폭딜 컨셉
        "암살자": {
            "hard":   0.45,
            "normal": 0.60,
            "easy":   0.70,
        },
    }

    # 기존 BASE_TARGET은 호환성 유지용 (외부 코드가 참조할 수 있음)
    BASE_TARGET = DEFAULT_TARGET
    TOLERANCE = 0.03
    MAX_ITER  = 20
    SIM_N     = 300

    def __init__(self, player: EntitySnapshot, base_enemy: EntitySnapshot):
        self.player     = player
        self.base_enemy = base_enemy

        # 몬스터 이름 기반 목표 승률 결정
        enemy_name = getattr(base_enemy, "name", "").strip()
        self.target_table = self._TARGET_BY_NAME.get(enemy_name, self.DEFAULT_TARGET)

        # 플레이어 전투력 지수 계산
        self.power_index = PlayerPowerIndex.calc(player)

    def _adjusted_target(self, difficulty: str) -> float:
        """
        플레이어 전투력 지수로 목표 승률 보정.

        PowerIndex > 1.0 (강한 상태) → 목표 승률 감소 (더 강한 몬스터)
        PowerIndex < 1.0 (약한 상태) → 목표 승률 증가 (더 약한 몬스터)

        보정 범위: ±0.08 (기존 ±0.15에서 축소)
        축소 이유: 이분탐색이 따라갈 수 없을 정도로 공격적인 목표 방지.

        target_table은 몬스터 종류에 따라 다르게 적용됨 (박쥐 = 유리대포).
        상한을 0.92로 확장 — 박쥐 easy 목표 95% 수렴 허용.
        """
        base   = self.target_table[difficulty]
        delta  = (1.0 - self.power_index) * 0.08
        target = base + delta
        return round(max(0.20, min(0.97, target)), 3)

    def tune(self, difficulty: str) -> Tuple:
        target = self._adjusted_target(difficulty)

        # ── scale 범위 확장 (방안 A 폐기) ──
        # 이전: lo=0.6, hi=5.0 → 박쥐/슬라임/유령 같은 약체 몬스터의
        #       강함 난이도가 100% 승률에서 수렴하는 한계 발견.
        # 변경: hi=5.0 → 8.0
        #       ARM/LUC 캡 min(scale, 1.8) → min(scale, 2.5)
        #       sqrt 적용한 stg 등은 자연스레 1.4배까지 추가 확장됨.
        #
        # HP 완화 공식 (0.60 + 0.30*scale) 덕에 hi=8.0 에서도 HP는
        # 0.60 + 2.40 = 3.0배까지만 늘어남 — 폭등 방지 유지.
        lo, hi     = 0.6, 8.0
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

        # 난이도 라벨을 몬스터 스냅샷에 기록 (UI 표시용)
        # hard/normal/easy → 약/중/강과 반대 매핑 주의:
        #   hard = 플레이어가 이기기 어려움 → 몬스터 입장에서 "강함"
        #   easy = 플레이어가 이기기 쉬움 → 몬스터 입장에서 "약함"
        best_enemy.difficulty = difficulty
        return best_enemy, final_sim

    def _scale_enemy(self, scale: float) -> EntitySnapshot:
        """
        몬스터 종족별로 스케일링 축을 다르게 적용.
        같은 hp/stg만 조정하면 슬라임/골렘/유령 등 특수 몬스터의 난이도가
        '같은 스탯으로 접히는' 현상이 발생 → 역할별 축 차별화.

        공통 (모든 몬스터):
          hp:  e.hp * (0.60 + 0.30 * scale)   — 초반 HP 폭등 방지
          stg: e.stg * sqrt(scale)            — sqrt(8.0)=2.83배까지
          arm: e.arm * min(scale, 2.5)        — 강한 ARM 차별화 (1.8→2.5)
          luc: e.luc * min(scale, 2.5)        — 회피·크리 변수 (1.8→2.5)
        scale 상한 5.0→8.0 확장에 맞춰 ARM/LUC 캡도 함께 완화.

        역할 추가 축:
          슬라임 (저항형): sparm/sp 도 조정 → 마법 약점 활용시 난이도 차이 보장
          골렘  (탱커형): arm 가중치 추가 + sparm 강화 → 마법 면역 강조
          유령  (회피형): spd/luc 강화 → 회피·선공 난이도 차이
          암살자 (속도형): stg/spd/luc 강화 (기존)
          박쥐  (유리대포): sp 강화 → 마법 데미지 변수
          고블린 (표준): 공통 축만
        """
        import math
        e = copy.deepcopy(self.base_enemy)
        et = getattr(e, "enemy_type", "") or e.name

        # ── 공통 스케일링 ──
        e.hp = max(1.0, e.hp * (0.60 + 0.30 * scale))
        e.maxhp = e.hp
        e.stg   = max(1.0, e.stg * math.sqrt(scale))
        e.arm   = max(0.0, e.arm * min(scale, 2.5))   # 1.8 → 2.5
        e.luc   = max(0.0, e.luc * min(scale, 2.5))   # 1.8 → 2.5

        # ── 역할별 추가 축 ──
        if et == "슬라임":
            # 저항형: 마법 약점 활용 시 난이도 분리
            e.sparm = max(0.0, e.sparm * min(math.sqrt(scale) * 1.1, 2.2))
            e.sp    = max(0.0, e.sp * math.sqrt(scale))
        elif et == "골렘":
            # 탱커형: arm 한 번 더 + sparm
            e.arm   = max(0.0, e.arm * min(scale * 0.15 + 1.0, 1.5))   # +up to 50%
            e.sparm = max(0.0, e.sparm * min(math.sqrt(scale) * 1.1, 2.2))
        elif et == "유령":
            # 회피형: spd/luc 강화 (회피 메커니즘과 시너지)
            e.spd = max(0.0, e.spd * min(math.sqrt(scale) * 1.05, 1.8))
            e.luc = max(0.0, e.luc * min(scale * 0.1 + 1.0, 1.5))
        elif et == "암살자":
            # 속도/선공형: spd 추가
            e.spd = max(0.0, e.spd * min(math.sqrt(scale) * 1.05, 1.8))
        elif et == "박쥐":
            # 유리대포: sp 강화
            e.sp = max(0.0, e.sp * math.sqrt(scale))
        # 고블린: 공통 축만 (표준형)

        return e


# ────────────────────────────────────────────
# 몬스터 팩토리
# ────────────────────────────────────────────

def _unit_to_snap(unit) -> EntitySnapshot:
    """
    Enemy_Class.Unit → EntitySnapshot 변환 헬퍼.
    Simulator 전체에서 이 함수만 사용 — 수치 출처를 Enemy_Class 단일화.
    Phase 1: 역할 기반 메커니즘 필드도 함께 보존.
    """
    return EntitySnapshot(
        name=unit.name,
        hp=unit.hp,       maxhp=unit.hp,
        mp=getattr(unit, 'mp', 0),
        maxmp=getattr(unit, 'mp', 0),
        stg=unit.stg,     arm=unit.arm,
        sparm=unit.sparm, sp=getattr(unit, 'sp', 0),
        luc=unit.luc,     lv=unit.lv,
        spd=getattr(unit, 'spd', 10),
        # 역할 기반 메커니즘
        physical_resist=getattr(unit, 'physical_resist', 1.0),
        magical_resist=getattr(unit, 'magical_resist', 1.0),
        dodge_bonus=getattr(unit, 'dodge_bonus', 0.0),
        dodge_penalty_per_extra_hit=getattr(unit, 'dodge_penalty_per_extra_hit', 0.10),
        first_strike=getattr(unit, 'first_strike', False),
        first_attack_bonus=getattr(unit, 'first_attack_bonus', 1.0),
        enemy_type=getattr(unit, 'enemy_type', unit.name),
    )


# 신규 5종 포함 — enemy_type 명칭으로 디스패치
_MAKER_DISPATCH = {
    "고블린":   Make_Goblin,
    "박쥐":     Make_Bat,
    "슬라임":   Make_Slime,
    "골렘":     Make_Golem,
    "유령":     Make_Ghost,
    "암살자":   Make_Assassin,
    "사제":     Make_Priest,
}


def _make_base_enemy(enemy_type: str, player_lv: int) -> EntitySnapshot:
    """
    enemy_type별 적절한 Make_X 함수를 호출하여 중급 몬스터 생성.
    Simulator가 독립적인 몬스터 수치를 갖지 않도록 단일 출처 보장.
    """
    lv = max(1, player_lv)
    maker = _MAKER_DISPATCH.get(enemy_type, Make_Goblin)
    return _unit_to_snap(maker(lv, "중"))


# 하위 호환용 스냅샷 (Enemy_Class Lv1 중급 기준으로 자동 생성)
def _make_base_enemies():
    return {name: _unit_to_snap(maker(1, "중"))
            for name, maker in _MAKER_DISPATCH.items()}


BASE_ENEMIES = _make_base_enemies()


class MonsterFactory:
    """플레이어 상태 기반으로 강/중/약 3종 몬스터를 자동 생성."""

    def __init__(self, player: EntitySnapshot, enemy_type: str = "고블린"):
        self.player     = player
        self.enemy_type = enemy_type                               # ← 추가
        self.base_enemy = _make_base_enemy(enemy_type, player.lv) # 레벨 기반 동적 생성
        self.tuner      = StatTuner(player, self.base_enemy)

    def generate_all(self, verbose: bool = True, monitor=None) -> dict:
        """
        verbose=True : 메인 콘솔에 출력
        monitor      : BalanceHook 인스턴스 또는 None
                       _monitor_write() 메서드로 파일 IPC 전송
        """
        results = {}
        labels  = {"hard": "강함", "normal": "중간", "easy": "약함"}

        def _out(msg: str):
            if verbose:
                print(msg, flush=True)
            if monitor is not None and hasattr(monitor, '_monitor_write'):
                monitor._monitor_write(msg)

        _out(f"  [AI] {self.enemy_type} 밸런스 분석 시작")
        _out(f"  플레이어 전투력 지수: {self.tuner.power_index:.2f}")
        _out("")

        for diff in ["hard", "normal", "easy"]:
            adj = self.tuner._adjusted_target(diff)
            _out(f"  [{labels[diff]}] 목표 승률 {adj*100:.0f}%  계산 중...")
            enemy_snap, sim = self.tuner.tune(diff)
            results[diff] = (enemy_snap, sim)
            _out(f"  [{labels[diff]}] 완료 — 승률 {sim.win_rate*100:.1f}%"
                 f"  HP {int(enemy_snap.hp)}  STG {round(enemy_snap.stg, 1)}")

        _out("")
        _out(f"  [AI] {self.enemy_type} 분석 완료!")

        # __DONE__ 신호는 Balance_Hook의 _monitor_done()에서 전송
        # (마지막 스레드 완료 시점에 한 번만)

        return results