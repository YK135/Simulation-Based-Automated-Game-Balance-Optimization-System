"""
Battle_Engine.py
─────────────────────────────────────────────
순수 전투 로직 계산 모듈.
input() / print() 없음.

ATB 포인트 시스템:
  - 매 틱마다 effective_spd() 만큼 포인트 누적
  - 포인트 >= 100 → 행동권 발생, 이후 0으로 초기화
  - 스피드 차이가 클수록 자연스럽게 연속 행동 발생
  - 둔화 디버프 → spd 감소 → ATB 누적 느려짐
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform


# ────────────────────────────────────────────
# Debuff / Buff
# ────────────────────────────────────────────

@dataclass
class Debuff:
    """
    stat   : "arm" | "sparm" | "stg" | "spd"
    amount : 감소 비율 (0.0~1.0)
    turns  : 남은 지속 행동 수
    name   : 디버프 스킬명
    """
    stat: str
    amount: float
    turns: int
    name: str


@dataclass
class Buff:
    """
    stat   : "stg" | "arm" | "spd" | "mp_efficiency"
    amount : 증가 비율 (0.0~1.0)
    turns  : 남은 지속 행동 수
    name   : 버프 스킬명
    """
    stat: str
    amount: float
    turns: int
    name: str


# ────────────────────────────────────────────
# StatusEffect (원소 기반 행동 제어형 상태이상)
# ────────────────────────────────────────────

@dataclass
class StatusEffect:
    """
    원소 기반 상태이상.
    effect_type: "ignite" | "frostbite" | "paralyze"
    turns   : 남은 지속 행동 수
    dot_rate: 점화 데미지 비율 (기본 maxhp 4%)
    fail_prob: 마비 행동 실패 확률 (기본 40%)
    """
    effect_type: str
    turns: int
    name: str
    dot_rate: float = 0.04
    fail_prob: int  = 40


# ────────────────────────────────────────────
# EntitySnapshot
# ────────────────────────────────────────────

@dataclass
class EntitySnapshot:
    name: str
    hp: float
    maxhp: float
    mp: float
    maxmp: float
    stg: float
    arm: float
    sparm: float
    sp: float
    luc: float
    lv: int
    spd: float = 10.0
    learned_skills: list = field(default_factory=list)
    items: list = field(default_factory=list)
    debuffs: list = field(default_factory=list)
    buffs: list = field(default_factory=list)
    shield: float = 0.0
    last_damage_taken: float = 0.0
    difficulty: str = ""  # Simulator가 튜닝 시 "hard"/"normal"/"easy" 기록

    # ── 역할 기반 전투 시스템 (1학기 Phase 1) ──
    # 상성: 받는 데미지에 곱연산. 1.0 = 보통, 0.65 = 반감, 1.10 = 약점.
    physical_resist: float = 1.0   # 물리 데미지 받을 때 곱 (슬라임 0.65)
    magical_resist:  float = 1.0   # 마법 데미지 받을 때 곱 (골렘 0.65)

    # 회피 보정 (유령 +0.20 → 회피율 + 20%p 추가)
    dodge_bonus: float = 0.0

    # 다단히트 회피 패널티 (유령): hit_count > 1 인 스킬에 대해
    # dodge_penalty_per_extra_hit 만큼 회피율 감소
    dodge_penalty_per_extra_hit: float = 0.10

    # 선공/첫공격 (암살자):
    #   first_strike: 전투 시작 시 무조건 선공 (SPD와 무관)
    #   first_attack_bonus: 첫 공격 데미지 배율 (1.15 = +15%)
    first_strike: bool = False
    first_attack_bonus: float = 1.0
    has_attacked: bool = False  # 이번 전투에서 첫 공격을 했는지

    # 종족 식별자 (UI 표시 등에 활용)
    enemy_type: str = ""

    # ── 직업 식별자 (플레이어 전용) ──
    # 직업별 패시브 발동에 사용:
    #   "전사":   공격 3회마다 maxhp 10% 회복 (Battlesession.step에서 처리)
    #   "마법사": 스킬 MP 비용 30% 감소 (execute_skill에서 처리)
    #   "탱커":   물공 받으면 maxmp 10%, 마공 받으면 maxhp 10% 회복
    #             (DamageCalc 또는 _execute_action 에서 처리)
    #   "도적":   크리 시 70% 확률로 방어력 50% 무시
    #             (DamageCalc.physical 에서 처리)
    job: str = ""

    # ── 원소 시스템 ──
    # element_queue: 원소 부착 큐 (최대 2개)
    # status_effects: 실제 상태이상 리스트 (StatusEffect)
    # attack_element: 몬스터 기본공격 원소
    element_queue: list = field(default_factory=list)
    status_effects: list = field(default_factory=list)
    attack_element: str = ""

    # 하위 호환 property
    @property
    def element_aura(self) -> str:
        return self.element_queue[-1] if self.element_queue else ""

    @element_aura.setter
    def element_aura(self, val: str):
        if val:
            self.element_queue = [val]
        else:
            self.element_queue.clear()

    def effective_stg(self) -> float:
        debuff_r = sum(d.amount for d in self.debuffs if d.stat == "stg")
        buff_r = sum(b.amount for b in self.buffs if b.stat == "stg")
        return max(1.0, self.stg * (1 - debuff_r + buff_r))

    def effective_arm(self) -> float:
        debuff_r = sum(d.amount for d in self.debuffs if d.stat == "arm")
        buff_r = sum(b.amount for b in self.buffs if b.stat == "arm")
        return max(0.0, self.arm * (1 - debuff_r + buff_r))

    def effective_sparm(self) -> float:
        debuff_r = sum(d.amount for d in self.debuffs if d.stat == "sparm")
        return max(0.0, self.sparm * (1 - debuff_r))

    def effective_spd(self) -> float:
        debuff_r = sum(d.amount for d in self.debuffs if d.stat == "spd")
        buff_r = sum(b.amount for b in self.buffs if b.stat == "spd")
        base = max(1.0, self.spd * (1 - debuff_r + buff_r))
        # 동상: ATB 50% 감소
        if any(e.effect_type == "frostbite" for e in self.status_effects):
            base *= 0.5
        return max(1.0, base)

    def mp_cost_multiplier(self) -> float:
        # 기존 buff 기반 효율 (한정 시간 효과)
        reduction = sum(b.amount for b in self.buffs if b.stat == "mp_efficiency")

        # ── 마법사 패시브: 영구 30% MP 비용 감소 ──
        # 직업 정체성 — 마나 효율형. 시뮬레이터에서도 자동 검증됨.
        if self.job == "마법사":
            reduction += 0.30

        return max(0.3, 1.0 - reduction)

    # ═══════════════════════════════════════════════════════════
    # 직업 패시브 헬퍼
    # ═══════════════════════════════════════════════════════════

    def passive_on_turn_start(self) -> str:
        """
        플레이어 행동 시점에 호출되는 패시브 처리.
          - 전사: 공격 3회마다 maxhp 10% 회복 (action_count 외부에서 관리)
        반환: 발동 메시지 (없으면 "")
 
        주의: 호출 측에서 발동 조건(3회마다)을 가지고 있어야 함.
        여기서는 단순히 "전사인지" + "회복" 만 처리.
 
        밸런싱 이력:
          - 초기: 2턴마다 → 시뮬 결과 +76.5%p 승률 향상 (과강)
          - 현재: 공격 3회마다 → 발동 빈도 ~33% 감소 → 적정 수준 기대
        """
        if self.job == "전사":
            heal = self.maxhp * 0.10
            before = self.hp
            self.hp = min(self.maxhp, self.hp + heal)
            healed = int(self.hp - before)
            if healed > 0:
                return f"[전사 패시브] 자동회복 +{healed} HP"
        return ""

    def passive_on_hit_received(self, damage_type: str) -> str:
        """
        데미지를 받은 직후 발동되는 패시브.
          - 탱커:
              물리(physical) 받음 → maxmp 10% 회복
              마법(magical)  받음 → maxhp 10% 회복
        damage_type: "physical" | "magical"
        반환: 발동 메시지 (없으면 "")

        호출 시점: _execute_action 또는 BattleSession이 데미지 적용 직후.
        회피했거나 데미지 0이면 호출 안 됨.
        """
        if self.job != "탱커":
            return ""
        if damage_type == "physical":
            heal = self.maxmp * 0.10
            before = self.mp
            self.mp = min(self.maxmp, self.mp + heal)
            gained = int(self.mp - before)
            if gained > 0:
                return f"[탱커 패시브] 물리피격 → MP +{gained}"
        elif damage_type == "magical":
            heal = self.maxhp * 0.10
            before = self.hp
            self.hp = min(self.maxhp, self.hp + heal)
            gained = int(self.hp - before)
            if gained > 0:
                return f"[탱커 패시브] 마법피격 → HP +{gained}"
        return ""

    def apply_debuff(self, debuff: Debuff):
        for existing in self.debuffs:
            if existing.stat == debuff.stat:
                existing.amount = debuff.amount
                existing.turns = debuff.turns
                existing.name = debuff.name
                return
        self.debuffs.append(copy.copy(debuff))

    def apply_buff(self, buff: Buff):
        for existing in self.buffs:
            if existing.stat == buff.stat:
                existing.amount = buff.amount
                existing.turns = buff.turns
                existing.name = buff.name
                return
        self.buffs.append(copy.copy(buff))

    def tick_debuffs(self):
        alive = []
        for d in self.debuffs:
            if d.turns > 1:
                d.turns -= 1
                alive.append(d)
        self.debuffs = alive

    def tick_buffs(self):
        alive = []
        for b in self.buffs:
            if b.turns > 1:
                b.turns -= 1
                alive.append(b)
        self.buffs = alive

    # ── 원소 상태이상 ──
    def apply_status_effect(self, effect: "StatusEffect") -> None:
        """상태이상 적용. 같은 타입은 남은 턴 갱신(중복 허용X)."""
        for existing in self.status_effects:
            if existing.effect_type == effect.effect_type:
                existing.turns = max(existing.turns, effect.turns)
                return
        import copy as _copy
        self.status_effects.append(_copy.copy(effect))

    def tick_status_effects(self) -> list:
        """
        행동자 턴 시작 시 호출.
        점화: 이 턴 데미지 적용.
        동상/마비: 메시지만 반환 (실제 효과는 effective_spd/is_paralyzed에서).
        반환: 메시지 리스트 (UI 표시용)
        """
        msgs = []
        alive = []
        for eff in self.status_effects:
            if eff.effect_type == "ignite":
                dmg = max(1, int(self.maxhp * eff.dot_rate))
                self.hp = max(0.0, self.hp - dmg)
                msgs.append(f"🔥 [{self.name}] 점화 -{dmg} HP")
            elif eff.effect_type == "frostbite":
                msgs.append(f"❄ [{self.name}] 동상 — SPD 50% ({eff.turns}T 남음)")
            elif eff.effect_type == "paralyze":
                msgs.append(f"⚡ [{self.name}] 마비 중 ({eff.turns}T 남음)")
            if eff.turns > 1:
                eff.turns -= 1
                alive.append(eff)
        self.status_effects = alive
        return msgs

    def is_paralyzed(self) -> bool:
        """마비 행동 실패 판정. 호출 시 확률 롤."""
        for eff in self.status_effects:
            if eff.effect_type == "paralyze":
                return randint(1, 100) <= eff.fail_prob
        return False

    @classmethod
    def from_player(cls, player) -> "EntitySnapshot":
        skills = []
        if hasattr(player, "skill") and player.skill and hasattr(player.skill, "learned_skills"):
            skills = list(player.skill.learned_skills)
        elif hasattr(player, "learned_skills"):
            skills = list(player.learned_skills)

        return cls(
            name=player.name,
            hp=player.hp,
            maxhp=player.maxhp,
            mp=player.mp,
            maxmp=player.maxmp,
            stg=player.stg,
            arm=player.arm,
            sparm=player.sparm,
            sp=player.sp,
            luc=player.luc,
            lv=player.lv,
            spd=getattr(player, "spd", 10.0),
            learned_skills=skills,
            job=getattr(player, "job", ""),  # 직업별 패시브 발동용
        )

    @classmethod
    def from_enemy(cls, enemy) -> "EntitySnapshot":
        snap = cls(
            name=enemy.name,
            hp=enemy.hp,
            maxhp=getattr(enemy, "maxhp", enemy.hp),
            mp=getattr(enemy, "mp", 0),
            maxmp=getattr(enemy, "maxmp", getattr(enemy, "mp", 0)),
            stg=enemy.stg,
            arm=enemy.arm,
            sparm=getattr(enemy, "sparm", 0),
            sp=getattr(enemy, "sp", 0),
            luc=enemy.luc,
            lv=enemy.lv,
            spd=getattr(enemy, "spd", 10.0),
            difficulty=getattr(enemy, "difficulty", ""),
            # 역할 기반 메커니즘 (Phase 1)
            physical_resist=getattr(enemy, "physical_resist", 1.0),
            magical_resist=getattr(enemy, "magical_resist", 1.0),
            dodge_bonus=getattr(enemy, "dodge_bonus", 0.0),
            dodge_penalty_per_extra_hit=getattr(enemy, "dodge_penalty_per_extra_hit", 0.10),
            first_strike=getattr(enemy, "first_strike", False),
            first_attack_bonus=getattr(enemy, "first_attack_bonus", 1.0),
            enemy_type=getattr(enemy, "enemy_type", ""),
            attack_element=getattr(enemy, "attack_element", ""),
        )
        # 원소 슬라임 등: 전투 시작 시 초기 원소 큐 설정
        init_q = getattr(enemy, "init_element_queue", [])
        if init_q:
            snap.element_queue = list(init_q)
        return snap


# ────────────────────────────────────────────
# TurnLog / BattleResult
# ────────────────────────────────────────────

@dataclass
class TurnLog:
    turn: int
    actor: str
    action: str
    action_detail: str
    damage_dealt: int = 0
    hp_after: float = 0.0
    mp_after: float = 0.0
    is_dodge: bool = False
    is_crit: bool = False
    debuff_applied: str = ""
    escaped: bool = False
    player_pt: float = 0.0
    enemy_pt: float = 0.0


@dataclass
class BattleResult:
    winner: str
    total_turns: int
    logs: list
    final_player_hp: float
    final_enemy_hp: float
    player_name: str
    enemy_name: str
    final_player_items: list = field(default_factory=list)


# ────────────────────────────────────────────
# ATB 시스템
# ────────────────────────────────────────────

class ATBSystem:
    THRESHOLD = 100
    SPD_MULTIPLIER: float = 1.0

    def __init__(self, spd_multiplier: float = 1.0):
        self.player_pt: float = 0.0
        self.enemy_pt: float = 0.0
        self.x = spd_multiplier

    def tick(self, player_spd: float, enemy_spd: float) -> list[str]:
        self.player_pt += max(1.0, player_spd * self.x)
        self.enemy_pt += max(1.0, enemy_spd * self.x)

        candidates = []
        if self.player_pt >= self.THRESHOLD:
            candidates.append(("player", self.player_pt))
        if self.enemy_pt >= self.THRESHOLD:
            candidates.append(("enemy", self.enemy_pt))

        candidates.sort(key=lambda x: (x[1], 1 if x[0] == "player" else 0), reverse=True)
        actors = [c[0] for c in candidates]

        if "player" in actors:
            self.player_pt = 0.0
        if "enemy" in actors:
            self.enemy_pt = 0.0

        return actors

    def reset(self):
        self.player_pt = 0.0
        self.enemy_pt = 0.0


# ────────────────────────────────────────────
# 데미지 계산
# ────────────────────────────────────────────

class DamageCalc:
    """
    데미지 계산 통합 클래스 (Phase 1 — 역할 기반 메커니즘 통합).

    기본 공식 (v2):
      base = atk_stat * 200 / (100 + def_stat)
      base = max(base, atk_stat * 0.4)         # 최소 데미지 보장
      base *= skill_mult * role_mult * uniform(0.9, 1.1)
      crit (luc * 0.5%, 상한 40%) → +50%

    역할 기반 추가 (Phase 1):
      - 회피: def_luc * 0.4 + dodge_bonus*100 - dodge_penalty_per_extra_hit
              (유령: dodge_bonus=0.20, 다단히트시 hit당 회피 감소)
      - 첫 공격 보너스: attacker.has_attacked == False 면 first_attack_bonus 적용
              (암살자: first_attack_bonus=1.15)
      - 상성: defender의 physical_resist / magical_resist
              (슬라임: 물리 0.65 / 마법 1.10, 골렘: 반대)
      - 최종 최소 데미지 보장: atk_stat * 0.20
              (상성으로 깎여도 공격력의 20% 이상은 보장)

    호출 흐름:
      physical(): 물리 데미지 → _calc(damage_type="physical")
      magical():  마법 데미지 → _calc(damage_type="magical")
      _calc():    회피 → 기본 → 첫공 → 상성 → 크리 → 최소 보장 → 정수화

    호출 시 attacker / defender 스냅샷을 넘겨야 역할 메커니즘 적용됨.
    옛 호출 (attacker/defender 인자 없음)도 후방 호환 — 기본값은 1.0/0.0.
    """

    ROLE_MULT = {
        "player": 1.0,
        "monster": 1.0,
    }

    @staticmethod
    def _calc(
        atk_stat: float,
        def_stat: float,
        atk_luc: float,
        def_luc: float,
        skill_mult: float,
        role_mult: float,
        # ── Phase 1 신규 인자 (모두 옵셔널, 후방 호환) ──
        damage_type: str = "physical",   # "physical" | "magical"
        defender = None,                 # EntitySnapshot — 상성/회피보너스 적용
        attacker = None,                 # EntitySnapshot — 첫공격 보너스 / has_attacked 갱신
        hit_count: int = 1,              # 다단히트 (회피 페널티 적용)
    ) -> tuple[int, bool, bool]:
        # ── 회피 판정 (다단히트 + dodge_bonus 반영) ──
        # 기본: def_luc × 0.4, 상한 25
        # +dodge_bonus(유령 +20), -다단히트 페널티(다단히트시 회피율 감소)
        base_evade = min(def_luc * 0.4, 25)
        if defender is not None:
            base_evade += defender.dodge_bonus * 100  # 0.20 → +20%p
            if hit_count > 1:
                penalty = defender.dodge_penalty_per_extra_hit * 100 * (hit_count - 1)
                base_evade -= penalty
        base_evade = max(0.0, min(base_evade, 60.0))  # 상하한 가드

        if randint(1, 100) <= base_evade:
            return 0, True, False

        # ── 기본 데미지 공식 (v2) ──
        base = atk_stat * 200 / (100 + def_stat)
        base = max(base, atk_stat * 0.4)
        base *= skill_mult
        base *= role_mult
        base *= uniform(0.9, 1.1)

        # ── 첫공격 보너스 (암살자) ──
        if attacker is not None and not attacker.has_attacked:
            base *= attacker.first_attack_bonus
            attacker.has_attacked = True

        # ── 상성 적용 (defender의 저항/약점) ──
        if defender is not None:
            if damage_type == "physical":
                base *= defender.physical_resist
            elif damage_type == "magical":
                base *= defender.magical_resist

        # ── 크리티컬 ──
        crit_chance = min(atk_luc * 0.5, 40)
        is_crit = randint(1, 100) <= crit_chance
        if is_crit:
            base *= 1.5

            # ── 도적 패시브: 크리 시 70% 확률로 방어력 50% 무시 ──
            # 효과 = 원래 base를 def_stat 절반으로 다시 계산한 값으로 보정.
            #   원래: atk * 200 / (100 + def)
            #   무시: atk * 200 / (100 + def * 0.5)
            #   비율: (100 + def) / (100 + def * 0.5)
            # def가 높을수록 효과가 큼 → 일격 특화 정체성과 일치.
            if attacker is not None and attacker.job == "도적":
                if randint(1, 100) <= 70:
                    pen_ratio = (100 + def_stat) / (100 + def_stat * 0.5)
                    base *= pen_ratio

        # ── 최소 데미지 보장 (atk_stat × 0.20) ──
        # 상성으로 깎여도 공격력의 20% 이상은 보장 (Phase 1 디자인 원칙)
        # 단 회피로 0이 된 경우는 위에서 이미 return 됨
        min_dmg = atk_stat * 0.20
        if base < min_dmg:
            base = min_dmg

        return int(base), False, is_crit

    @staticmethod
    def physical(
        atk_stg: float,
        atk_luc: float,
        def_arm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
        defender = None,
        attacker = None,
        hit_count: int = 1,
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_stg, def_arm, atk_luc, def_luc,
            skill_mult, role_mult,
            damage_type="physical",
            defender=defender,
            attacker=attacker,
            hit_count=hit_count,
        )

    @staticmethod
    def magical(
        atk_sp: float,
        atk_luc: float,
        def_sparm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
        defender = None,
        attacker = None,
        hit_count: int = 1,
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_sp, def_sparm, atk_luc, def_luc,
            skill_mult, role_mult,
            damage_type="magical",
            defender=defender,
            attacker=attacker,
            hit_count=hit_count,
        )


# ────────────────────────────────────────────
# 스킬 메타데이터
# ────────────────────────────────────────────

SKILL_META = {
    "약화1": {
        "mp": 8, "type": "debuff",
        "debuff_stat": "arm",
        "debuff_amount": (0.10, 0.15),
        "debuff_turns": (3, 4)
    },
    "약화2": {
        "mp": 14, "type": "debuff",
        "debuff_stat": "arm",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (4, 5)
    },
    "마약화1": {
        "mp": 8, "type": "debuff",
        "debuff_stat": "sparm",
        "debuff_amount": (0.10, 0.15),
        "debuff_turns": (3, 4)
    },
    "마약화2": {
        "mp": 14, "type": "debuff",
        "debuff_stat": "sparm",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (4, 5)
    },
    "저주1": {
        "mp": 10, "type": "debuff",
        "debuff_stat": "stg",
        "debuff_amount": (0.10, 0.20),
        "debuff_turns": (3, 5)
    },
    "저주2": {
        "mp": 18, "type": "debuff",
        "debuff_stat": "stg",
        "debuff_amount": (0.20, 0.30),
        "debuff_turns": (4, 6)
    },
    "둔화1": {
        "mp": 7, "type": "debuff",
        "debuff_stat": "spd",
        "debuff_amount": (0.15, 0.25),
        "debuff_turns": (3, 4)
    },
    "둔화2": {
        "mp": 15, "type": "debuff",
        "debuff_stat": "spd",
        "debuff_amount": (0.25, 0.35),
        "debuff_turns": (4, 5)
    },

    "연속공격1": {
        "mp": 8, "mult": 0.80, "type": "physical", "hits": 2  # 0.70 → 0.80: 초반 연타 체감 개선
    },
    "연속공격2": {
        # 스펙: mult 0.70, hits 3 (약간 하향)
        "mp": 13, "mult": 0.70, "type": "physical", "hits": 3
    },
    "강타1": {
        "mp": 10, "mult": 1.55, "type": "physical", "hits": 1
    },
    "강타2": {
        # 스펙: mult 1.80
        "mp": 16, "mult": 1.80, "type": "physical", "hits": 1
    },
    "슬래시1": {
        "mp": 12, "mult": 0.65, "type": "physical", "hits": 1, "aoe": True
    },
    "슬래시2": {
        "mp": 18, "mult": 0.80, "type": "physical", "hits": 1, "aoe": True
    },
    "강화1": {
        "mp": 14, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.15, "buff_turns": 2
    },
    "강화2": {
        "mp": 20, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.25, "buff_turns": 2
    },

    "파이어볼1": {
        "mp": 10, "mult": 1.50, "type": "magical", "hits": 1, "element": "fire"
    },
    "파이어볼2": {
        # 스펙: mult 1.55 (후반 화력 억제)
        "mp": 16, "mult": 1.55, "type": "magical", "hits": 1, "element": "fire"
    },
    "아이스볼릿1": {
        "mp": 11, "mult": 1.25, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 0.3,
        "debuff_amount": (0.10, 0.15), "debuff_turns": (2, 3)
    },
    "아이스볼릿2": {
        "mp": 17, "mult": 1.45, "type": "magical", "hits": 1,
        "element": "ice",
        "debuff_stat": "spd", "debuff_chance": 0.5,
        "debuff_amount": (0.15, 0.20), "debuff_turns": (2, 3)
    },
    "라이트닝1": {
        "mp": 12, "mult": 1.55, "type": "magical", "hits": 1, "element": "lightning"
    },
    "라이트닝2": {
        # 스펙: mult 1.60
        "mp": 19, "mult": 1.60, "type": "magical", "hits": 1, "element": "lightning"
    },
    "힐1": {
        "mp": 12, "type": "heal",
        "base_heal": 80, "sp_mult": 1.2, "cap": 0.22
    },
    "힐2": {
        # 스펙: base_heal 130, sp_mult 1.15, cap 0.30 (유지력 억제)
        "mp": 20, "type": "heal",
        "base_heal": 130, "sp_mult": 1.15, "cap": 0.30
    },
    "효율성1": {
        "mp": 14, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.20, "buff_turns": 2
    },
    "효율성2": {
        # 스펙: buff_amount 0.25 (0.35 → 0.25, 후반 무한화력 억제)
        "mp": 22, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.25, "buff_turns": 2
    },

    "몸통박치기1": {
        "mp": 8, "type": "tank_attack",
        "arm_mult": 1.4, "hp_mult": 0.03
    },
    "몸통박치기2": {
        # 스펙: arm_mult 1.5, hp_mult 0.035
        "mp": 13, "type": "tank_attack",
        "arm_mult": 1.5, "hp_mult": 0.035
    },
    "되갚기1": {
        "mp": 10, "type": "counter",
        "counter_mult": 0.5, "arm_mult": 1.0, "cap": 0.18
    },
    "되갚기2": {
        "mp": 16, "type": "counter",
        "counter_mult": 0.6, "arm_mult": 1.2, "cap": 0.25
    },
    "수비태세1": {
        "mp": 12, "type": "buff",
        "buff_stat": "arm", "buff_amount": 0.15, "buff_turns": 2
    },
    "수비태세2": {
        "mp": 18, "type": "buff",
        "buff_stat": "arm", "buff_amount": 0.25, "buff_turns": 2
    },
    "실드": {
        "mp": 16, "type": "shield",
        "shield_mult": 0.20
    },

    "급소찌르기1": {
        "mp": 7, "mult": 1.20, "type": "physical", "hits": 1,
        "luc_bonus": 0.8
    },
    "급소찌르기2": {
        # 스펙: mult 1.30, luc_bonus 0.8 (후반 폭주 억제)
        "mp": 15, "mult": 1.30, "type": "physical", "hits": 1,
        "luc_bonus": 0.8
    },
    "연속찌르기": {
        # 스펙: max_hits 4, base_prob 5, luc_mult 3, prob_decay 20, dmg_decay 0.68
        "mp": 14, "type": "multi_hit",
        "max_hits": 4, "base_prob": 5, "luc_mult": 3,
        "prob_decay": 20, "dmg_decay": 0.68
    },
    "난사1": {
        "mp": 12, "mult": 0.65, "type": "physical", "hits": 1, "aoe": True
    },
    "난사2": {
        "mp": 18, "mult": 0.85, "type": "physical", "hits": 1, "aoe": True
    },
    "추진력": {
        "mp": 13, "type": "buff",
        "buff_stat": "spd", "buff_amount": 0.10, "buff_turns": 2
    },
    # ─────────────────────────────────────────────
    # 사제(서포터형 몬스터) 전용 스킬 — 적이 사용
    # 플레이어 스킬 트리에는 등록되지 않음.
    # ─────────────────────────────────────────────
    "홀리볼트": {
        # 사제의 공격 스킬 — 마법 데미지 (약함)
        # 골렘(마법 저항 0.65)에는 잘 안 통하고, 슬라임(마법 +10%)에는 잘 통함
        "mp": 8, "mult": 1.10, "type": "magical", "hits": 1
    },
    "사제축복": {
        # 사제 본인이 사용 안 함. Battlesession._priest_action에서 다른 아군에게 적용.
        # SKILL_META에는 buff 형태로만 정의 (실제 발동은 별도 처리).
        "mp": 12, "type": "buff",
        "buff_stat": "stg", "buff_amount": 0.15, "buff_turns": 3
    },
    "사제힐": {
        # 사제의 핵심 — 다른 아군 회복.
        # SKILL_META에는 heal 형태로만 정의 (실제 발동은 Battlesession에서 별도 처리).
        # 자기 자신 X / 가장 HP 비율 낮은 아군 O.
        "mp": 14, "type": "heal",
        "base_heal": 60, "sp_mult": 1.4, "cap": 0.40
    },
}



# ────────────────────────────────────────────
# 원소 시스템 — element_queue 기반
# ────────────────────────────────────────────

# 반응 테이블: (큐[0], 큐[1]) → 반응명
REACTIONS = {
    ("ice",       "fire"):      "melt",
    ("fire",      "ice"):       "melt",
    ("fire",      "lightning"): "overload",
    ("lightning", "fire"):      "overload",
}

REACTION_EFFECTS = {
    "melt":     {"bonus_mult": 1.5, "label": "💧 융해"},
    "shatter":  {"bonus_mult": 1.2, "label": "💎 파쇄"},
    "overload": {"bonus_mult": 1.3, "label": "⚡ 과부하"},
}

# 원소 → 상태이상
ELEMENT_STATUS = {
    "fire":      ("ignite",    30),
    "ice":       ("frostbite", 35),
    "lightning": ("paralyze",  25),
}
ELEMENT_STATUS_TURNS = {"ignite": 3, "frostbite": 2, "paralyze": 3}
ELEMENT_STATUS_LABEL = {"ignite": "🔥 화상", "frostbite": "❄ 동상", "paralyze": "⚡ 마비"}
SAME_ELEMENT_STATUS_BONUS = {"fire": 15, "ice": 15, "lightning": 15}


def _current_element(entity) -> str:
    """큐의 최신 원소 반환."""
    q = getattr(entity, "element_queue", [])
    return q[-1] if q else ""


def apply_element_and_react(
    attacker,
    defender,
    attack_element: str,
    base_damage: int,
    messages: list,
) -> int:
    """
    원소 큐 업데이트 + 반응 판정 + 상태이상 처리.
    반환: 최종 데미지
    """
    q = getattr(defender, "element_queue", [])

    # physical: 파쇄 체크만 (큐에 추가 안 함)
    if attack_element == "physical" or not attack_element:
        if q and q[-1] == "ice":
            eff = REACTION_EFFECTS["shatter"]
            bonus = int(base_damage * (eff["bonus_mult"] - 1.0))
            defender.element_queue.clear()
            messages.append(f"{eff['label']} 발동! +{bonus} 추가 데미지")
            messages.append(f"{defender.name}의 원소 큐가 초기화되었다.")
            return base_damage + bonus
        return base_damage

    status_bonus = 0

    if len(q) == 0:
        defender.element_queue.append(attack_element)
        messages.append(f"{defender.name}에게 {attack_element} 원소가 부착되었다.")

    elif len(q) == 1:
        existing = q[0]
        if existing == attack_element:
            status_bonus = SAME_ELEMENT_STATUS_BONUS.get(attack_element, 0)
            messages.append(f"{defender.name}에게 {attack_element} 원소 중첩! 상태이상 확률 ↑")
            defender.element_queue = [attack_element]
        else:
            defender.element_queue.append(attack_element)
            key = (existing, attack_element)
            reaction_name = REACTIONS.get(key)
            if reaction_name:
                eff = REACTION_EFFECTS[reaction_name]
                bonus = int(base_damage * (eff["bonus_mult"] - 1.0))
                defender.element_queue.clear()
                messages.append(f"{eff['label']} 반응 발동!")
                messages.append(f"{defender.name}에게 추가 {bonus} 피해!")
                messages.append(f"{defender.name}의 원소 큐가 초기화되었다.")
                base_damage += bonus
            else:
                defender.element_queue = [attack_element]
                messages.append(f"{defender.name}에게 {attack_element} 원소가 부착되었다.")

    # 상태이상 부여
    entry = ELEMENT_STATUS.get(attack_element)
    if entry:
        effect_type, base_prob = entry
        prob = min(95, base_prob + status_bonus)
        if randint(1, 100) <= prob:
            turns = ELEMENT_STATUS_TURNS[effect_type]
            eff_obj = StatusEffect(effect_type=effect_type, turns=turns, name=attack_element)
            if hasattr(defender, "apply_status_effect"):
                defender.apply_status_effect(eff_obj)
            label = ELEMENT_STATUS_LABEL[effect_type]
            messages.append(f"{defender.name}에게 {label} 상태가 부여되었다. ({turns}T)")

    return base_damage


# 하위 호환 래퍼
def check_element_reaction(defender, attack_element: str, base_damage: int, messages: list) -> int:
    return apply_element_and_react(None, defender, attack_element, base_damage, messages)


def try_apply_element_aura_and_status(attacker, defender, element: str, messages: list) -> None:
    if element:
        apply_element_and_react(attacker, defender, element, 0, messages)


# 구버전 호환
REACTION_TABLE = {}


def execute_skill(
    skill_name: str,
    attacker: EntitySnapshot,
    defender: EntitySnapshot,
) -> tuple[int, bool, str]:
    meta = SKILL_META.get(skill_name)
    if not meta:
        return 0, False, ""

    base_mp_cost = meta.get("mp", 0)
    real_mp_cost = int(round(base_mp_cost * attacker.mp_cost_multiplier()))
    real_mp_cost = max(0, real_mp_cost)

    if attacker.mp < real_mp_cost:
        return 0, True, ""

    attacker.mp -= real_mp_cost
    stype = meta["type"]

    if stype == "debuff":
        amt = round(
            meta["debuff_amount"][0]
            + random() * (meta["debuff_amount"][1] - meta["debuff_amount"][0]),
            2
        )
        turns = randint(meta["debuff_turns"][0], meta["debuff_turns"][1])
        defender.apply_debuff(Debuff(
            stat=meta["debuff_stat"],
            amount=amt,
            turns=turns,
            name=skill_name,
        ))
        return 0, False, skill_name

    if stype == "buff":
        attacker.apply_buff(Buff(
            stat=meta["buff_stat"],
            amount=meta["buff_amount"],
            turns=meta["buff_turns"],
            name=skill_name,
        ))
        return 0, False, skill_name

    if stype == "heal":
        heal = meta["base_heal"] + attacker.sp * meta["sp_mult"]
        heal = min(heal, attacker.maxhp * meta["cap"])
        attacker.hp = min(attacker.maxhp, attacker.hp + int(heal))
        return 0, False, "heal"

    if stype == "shield":
        new_shield = attacker.maxhp * meta["shield_mult"]
        attacker.shield = max(attacker.shield, new_shield)
        return 0, False, "shield"

    if stype == "tank_attack":
        damage = (attacker.effective_arm() * meta["arm_mult"]) + (attacker.maxhp * meta["hp_mult"])
        damage *= uniform(0.9, 1.1)
        _d = int(damage); _em=[]
        _d = apply_element_and_react(attacker, defender, meta.get("element",""), _d, _em)
        return _d, False, ("|".join(_em)) if _em else ""

    if stype == "counter":
        damage = (attacker.last_damage_taken * meta["counter_mult"]) + (attacker.effective_arm() * meta["arm_mult"])
        damage = min(damage, attacker.maxhp * meta["cap"])
        damage *= uniform(0.9, 1.1)
        _d = int(damage); _em=[]
        _d = apply_element_and_react(attacker, defender, meta.get("element",""), _d, _em)
        return _d, False, ("|".join(_em)) if _em else ""


    if stype == "multi_hit":
        total = 0
        hit_count = 1
        base_prob = meta["base_prob"]
        luc_mult = meta["luc_mult"]
        prob_decay = meta["prob_decay"]
        dmg_decay = meta["dmg_decay"]
        max_hits = meta["max_hits"]

        for hit_index in range(1, max_hits):
            prob = max(base_prob, min(85, attacker.luc * luc_mult - hit_index * prob_decay))
            if randint(1, 100) <= prob:
                hit_count += 1
            else:
                break

        # multi_hit은 hit_count 개수만큼 다단히트 →
        # defender의 dodge_penalty_per_extra_hit이 적용되어 유령 회피율 감소.
        for i in range(hit_count):
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(),
                attacker.luc,
                defender.effective_arm(),
                defender.luc,
                skill_mult=1.0,
                attacker=attacker,
                defender=defender,
                hit_count=hit_count,  # 다단히트 정보 전달
            )
            total += int(raw * (dmg_decay ** i))

        # multi_hit 원소 반응
        _elem = meta.get("element", "")
        _msgs: list = []
        if total > 0 or _elem:
            total = apply_element_and_react(attacker, defender, _elem, total, _msgs)
        return total, False, ("|".join(_msgs)) if _msgs else ""

    total = 0
    hits = meta.get("hits", 1)

    for _ in range(hits):
        if stype == "physical":
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(),
                attacker.luc,
                defender.effective_arm(),
                defender.luc,
                skill_mult=meta.get("mult", 1.0),
                attacker=attacker,
                defender=defender,
                hit_count=hits,  # hits>1이면 다단히트로 회피 페널티 적용
            )
            bonus = meta.get("luc_bonus", 0.0)
            if bonus:
                raw += int(attacker.luc * bonus)

        elif stype == "magical":
            raw, _, _ = DamageCalc.magical(
                attacker.sp,
                attacker.luc,
                defender.effective_sparm(),
                defender.luc,
                skill_mult=meta.get("mult", 1.0),
                attacker=attacker,
                defender=defender,
                hit_count=hits,
            )
        else:
            return 0, False, ""

        total += int(raw)

    if stype == "magical" and "debuff_stat" in meta and random() <= meta.get("debuff_chance", 0.0):
        amt = round(
            meta["debuff_amount"][0]
            + random() * (meta["debuff_amount"][1] - meta["debuff_amount"][0]),
            2
        )
        turns = randint(meta["debuff_turns"][0], meta["debuff_turns"][1])
        defender.apply_debuff(Debuff(
            stat=meta["debuff_stat"],
            amount=amt,
            turns=turns,
            name=skill_name,
        ))

    # ── 원소 큐 + 반응 + 상태이상 ──
    element = meta.get("element", "")
    extra_msgs: list = []
    if total > 0 or element:
        total = apply_element_and_react(attacker, defender, element, total, extra_msgs)
    info = skill_name if extra_msgs else (skill_name if "debuff_stat" in meta else "")
    return total, False, (info + "|" + "|".join(extra_msgs)) if extra_msgs else info


# ────────────────────────────────────────────
# 아이템
# ────────────────────────────────────────────

ITEM_META = {
    # amount는 (user) -> int 함수.
    # Digital Twin 원칙: game/Item.py의 공식과 완전히 일치시킴.
    # max(고정 최소값, maxhp/maxmp 비율) 형태.
    # 호출 시 meta["amount"](user) 형태로 사용.
    "HP_S_potion": {
        "slot": "potion",        
        "stat": "hp", 
        "amount": lambda u: max(200, int(u.maxhp * 0.12))
    },
    "HP_M_potion": {
        "slot": "potion", 
        "stat": "hp",
        "amount": lambda u: max(300, int(u.maxhp * 0.20))
    },
    "HP_L_potion": {
        "slot": "potion", 
        "stat": "hp", 
        "amount": lambda u: max(500, int(u.maxhp * 0.30))
    },
    "MP_S_potion": {
        "slot": "potion", 
        "stat": "mp", 
        "amount": lambda u: max(25,  int(u.maxmp * 0.15))
    },
    "MP_M_potion": {
        "slot": "potion", 
        "stat": "mp", 
        "amount": lambda u: max(40,  int(u.maxmp * 0.25))
    },
    "MP_L_potion": {
        "slot": "potion", 
        "stat": "mp", 
        "amount": lambda u: max(50,  int(u.maxmp * 0.35))
    },
}


def use_item(item_name: str, user: EntitySnapshot) -> bool:
    meta = ITEM_META.get(item_name)
    if not meta or item_name not in user.items:
        return False
    amount = meta["amount"](user)
    if meta["stat"] == "hp":
        user.hp = min(user.maxhp, user.hp + amount)
    elif meta["stat"] == "mp":
        user.mp = min(user.maxmp, user.mp + amount)
    user.items.remove(item_name)
    return True


# ────────────────────────────────────────────
# 도망 확률
# ────────────────────────────────────────────

def _escape_chance(player_spd: float, enemy_spd: float) -> float:
    ratio = player_spd / max(enemy_spd, 1.0)
    if ratio >= 2.0:
        return 0.95
    elif ratio >= 1.5:
        return 0.80
    elif ratio >= 1.0:
        return 0.60
    elif ratio >= 0.7:
        return 0.35
    else:
        return 0.15


def _apply_damage_with_shield(defender: EntitySnapshot, dmg: int) -> int:
    actual = dmg
    if defender.shield > 0:
        absorbed = min(defender.shield, actual)
        defender.shield -= absorbed
        actual -= absorbed
    defender.hp -= actual
    defender.last_damage_taken = actual
    return actual


# ────────────────────────────────────────────
# 전투 엔진
# ────────────────────────────────────────────

class BattleEngine:
    MAX_TICKS = 500

    def __init__(self, player: EntitySnapshot, enemy: EntitySnapshot, spd_multiplier: float = 1.0):
        self.player = copy.deepcopy(player)
        self.enemy = copy.deepcopy(enemy)
        self.logs: list[TurnLog] = []
        self.atb = ATBSystem(spd_multiplier)
        self.tick_count = 0
        self.action_count = 0
        # 직업 패시브용 카운터
        self._player_action_count = 0   # 전사 패시브 (2번마다 회복)

    def run(self, player_ai, enemy_ai) -> BattleResult:
        # ── first_strike 처리 (암살자) ──
        if getattr(self.enemy, "first_strike", False):
            self.action_count += 1
            action = enemy_ai(self.enemy, self.player)
            self._execute_action(action, self.enemy, self.player, "enemy")
            if self.player.hp <= 0:
                return self._make_result("enemy")

        while self.tick_count < self.MAX_TICKS:
            self.tick_count += 1

            actors = self.atb.tick(
                self.player.effective_spd(),
                self.enemy.effective_spd(),
            )

            if not actors:
                continue

            for actor in actors:
                self.action_count += 1

                if actor == "player":
                    # ── 전사 패시브: 공격 3회마다 maxhp 10% 회복 ──
                    # 변경: 2회→3회로 발동 빈도 ~33% 감소 (과강 +76.5%p 시뮬결과 반영)
                    self._player_action_count += 1
                    if self.player.job == "전사" and self._player_action_count % 3 == 0:
                        self.player.passive_on_turn_start()  # 메시지는 시뮬에선 무시
 
                    action = player_ai(self.player, self.enemy)
                    res = self._execute_action(action, self.player, self.enemy, "player")
                    if res == "escaped":
                        return self._make_result("escaped")
                    if self.enemy.hp <= 0:
                        return self._make_result("player")
                else:
                    action = enemy_ai(self.enemy, self.player)
                    self._execute_action(action, self.enemy, self.player, "enemy")
                    if self.player.hp <= 0:
                        return self._make_result("enemy")

            if "player" in actors:
                self.player.tick_debuffs()
                self.player.tick_buffs()
            if "enemy" in actors:
                self.enemy.tick_debuffs()
                self.enemy.tick_buffs()

        winner = "player" if self.player.hp >= self.enemy.hp else "enemy"
        return self._make_result(winner)

    def _execute_action(self, action, attacker, defender, actor) -> str:
        log = TurnLog(
            turn=self.action_count,
            actor=actor,
            action=action.action_type,
            action_detail=action.detail,
            hp_after=defender.hp,
            mp_after=attacker.mp,
            player_pt=self.atb.player_pt,
            enemy_pt=self.atb.enemy_pt,
        )

        if action.action_type == "attack":
            dmg, is_dodge, is_crit = DamageCalc.physical(
                attacker.effective_stg(), attacker.luc,
                defender.effective_arm(), defender.luc,
                skill_mult=1.0,
                role="player" if actor == "player" else "monster",
                attacker=attacker,
                defender=defender,
            )
            actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
            log.damage_dealt = actual
            log.hp_after = defender.hp
            log.is_dodge = is_dodge
            log.is_crit = is_crit

            # ── 탱커 패시브: 물리 피격 후 MP 회복 ──
            # defender가 탱커이고 회피하지 않고 데미지를 입은 경우 발동
            if not is_dodge and actual > 0:
                defender.passive_on_hit_received("physical")

        elif action.action_type == "skill":
            dmg, mp_lack, info = execute_skill(action.detail, attacker, defender)
            log.mp_after = attacker.mp

            if not mp_lack:
                if dmg > 0:
                    actual = _apply_damage_with_shield(defender, dmg)
                    log.damage_dealt = actual
                    log.hp_after = defender.hp

                    # ── 탱커 패시브: 스킬 피격 후 회복 (스킬 타입 따라 HP/MP) ──
                    # SKILL_META에서 type 조회 ("physical" or "magical")
                    skill_meta = SKILL_META.get(action.detail, {})
                    skill_type = skill_meta.get("type", "physical")
                    defender.passive_on_hit_received(skill_type)
                else:
                    log.hp_after = defender.hp

                if info:
                    log.debuff_applied = info
            else:
                dmg, is_dodge, is_crit = DamageCalc.physical(
                    attacker.effective_stg(), attacker.luc,
                    defender.effective_arm(), defender.luc,
                    skill_mult=1.0,
                    role="player" if actor == "player" else "monster",
                    attacker=attacker,
                    defender=defender,
                )
                actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
                log.action = "attack"
                log.action_detail = "attack(mp_fallback)"
                log.damage_dealt = actual
                log.hp_after = defender.hp
                log.is_dodge = is_dodge
                log.is_crit = is_crit

        elif action.action_type == "item":
            success = use_item(action.detail, attacker)
            log.action_detail = action.detail if success else "item_failed"
            log.hp_after = attacker.hp
            log.mp_after = attacker.mp

        elif action.action_type == "escape":
            chance = _escape_chance(attacker.effective_spd(), defender.effective_spd())
            if random() <= chance:
                log.escaped = True
                self.logs.append(log)
                return "escaped"
            else:
                log.action_detail = "escape_failed"

        elif action.action_type == "watch":
            log.action_detail = "watching"

        elif action.action_type == "pass":
            pass

        self.logs.append(log)
        return "ok"

    def _make_result(self, winner: str) -> BattleResult:
        return BattleResult(
            winner=winner,
            total_turns=self.action_count,
            logs=self.logs,
            final_player_hp=self.player.hp,
            final_enemy_hp=self.enemy.hp,
            player_name=self.player.name,
            enemy_name=self.enemy.name,
            final_player_items=list(self.player.items),
        )


# ────────────────────────────────────────────
# Action
# ────────────────────────────────────────────

@dataclass
class Action:
    """
    action_type: "attack"|"skill"|"item"|"escape"|"watch"|"pass"
    detail:      스킬명 / 아이템명 / ""
    """
    action_type: str
    detail: str = ""