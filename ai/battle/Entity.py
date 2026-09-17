"""Battle/Entity.py — EntitySnapshot, Buff, Debuff, StatusEffect"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, uniform


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
    상태이상 (원소 + 도적 출혈 + 보스 균열).
    effect_type: "ignite" | "frostbite" | "paralyze" | "bleed" | "rift"
    turns   : 남은 지속 행동 수
    dot_rate: 점화/균열 데미지 비율 (기본 maxhp 4%)
              bleed는 dot_rate 대신 매턴 uniform(0.04, 0.07) 랜덤 적용
    rift    : 중간 보스 「대지 균열」의 지속 피해. 전용 타입인 이유 —
              apply_status_effect()가 effect_type으로 동일 효과를 판정하므로
              ignite를 재사용하면 기존 화상과 하나로 합쳐진다
              (TestFile/telegraph_envelope.py 부록 D-2/D-3)
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

    # 골렘 그로기: 기본 공격을 연속으로 몇 번 맞았는지(스킬/회피가 끼면 리셋).
    # 2 도달 시 arm/sparm 50% 감소 디버프 적용 (Enemy_Actions/Player_Actions에서 갱신).
    physical_hit_streak: int = 0

    # 종족 식별자 (UI 표시 등에 활용)
    enemy_type: str = ""

    # ── 엘리트 몬스터 패턴 (ai/battle/EliteKit.py 참고) ──
    # elite_phase / elite_pattern_turn은 몬스터마다 의미가 다르게 쓰인다
    # (예: 골렘 0/1/2=수비태세/충전예고/공격, 빙결슬라임 0/1=갑옷활성/해제중,
    #  박쥐·화염·번개슬라임의 elite_pattern_turn=행동 스택 카운터).
    is_elite: bool = False
    elite_leader: bool = False
    elite_phase: int = 0
    elite_pattern_turn: int = 0
    elite_pattern_used: bool = False   # 전투당 1회 한정 능력(분노/추진력/부활/분열, 일반 사제의 약식 소생) 사용 여부
    is_summoned: bool = False          # 분열로 생성된 개체
    reward_eligible: bool = True       # False면 처치해도 경험치/보상 제외

    # ── 일반 몬스터 정체성 (ai/battle/MonsterKit.py 「일반 몬스터 정체성 규칙」) ──
    pack_bonus: float = 0.0        # 고블린 무리 전술 — 살아있는 고블린 수에 따른 STG 가산(세션이 동기화)
    flee_attempted: bool = False   # 고블린 겁쟁이 — 도주 시도는 전투당 1회
    fled: bool = False             # 달아났다(hp 0 + reward_eligible False로 전투에서 빠진다 — 죽은 것과 구분해 표시)

    # ── 보스 패턴 (ai/battle/BossKit.py) — 엘리트 필드와 섞지 않는다 ──
    boss_phase: int = 0            # 0=아직 동기화 전, 1/2/3 (midboss_sync_phase가 HP로 올린다)
    boss_cycle: int = 0            # 「대지 균열」 주기 카운터 — 예고·발동 행동은 세지 않음
    boss_telegraph_at: int = -1    # 예고를 세운 시점의 플레이어 행동 횟수, -1이면 예약 없음.
                                   # 발동 조건: 플레이어 행동 횟수 > 이 값 (예고 보장 규칙)
    boss_frost_regrow: int = 0     # 서리 갑주(ice) 재부착 카운트다운

    # ── 직업 식별자 (플레이어 전용) ──
    # 직업별 패시브 발동에 사용:
    #   "전사":   적 공격(일반공격/공격형 스킬) 3회마다 maxhp 10% 회복
    #             (Player_Actions._count_warrior_attack에서 카운트)
    #   "마법사": 융해/과부하 반응 피해 +5%p + 원소 반응 시 MP 8% 회복
    #             (Elements.apply_element_and_react에서 처리, 파쇄 제외)
    #   "탱커":   물리 피격 시 maxmp 10% 회복, 마법 피격 시 maxhp 10% 회복
    #             (passive_on_hit_received — Enemy_Actions/Engine에서 호출)
    #   "도적":   공격 시 주사위(1~6 배율/출혈/6=크리확정+ATB20),
    #             회피 시 반격(일반 luc 크리 허용, 주사위 미적용)
    #             (Player_Actions/Enemy_Actions/Damage._suppress_crit)
    job: str = ""

    # ── 원소 시스템 ──
    # element_queue: 원소 부착 큐 (최대 2개)
    # status_effects: 실제 상태이상 리스트 (StatusEffect)
    # attack_element: 몬스터 기본공격 원소
    element_queue: list = field(default_factory=list)
    _next_skill_bonus: float = 1.0
    _pending_atb_bonus: int = 0
    status_effects: list = field(default_factory=list)
    attack_element: str = ""

    # ── 밸런스 3차: cross-battle ATB 이월 (시뮬레이터용) ──
    # 실전(ai/Battlesession.py)은 이미 Player.atb_remainder로 전투 간 ATB를
    # 이월한다 — 이 필드는 그 값을 ai/battle/Engine.py의 BattleEngine(1v1
    # 시뮬레이터)에도 전달하기 위한 것. 기본 0.0이라 기존 호출부는 영향 없음.
    atb_remainder: float = 0.0

    # ── UI 데미지 숫자 색 구분용 태그 (표시 전용 — 전투 로직은 절대 읽지 않는다) ──
    # "이 대상이 마지막으로 받은 피해가 무슨 속성/반응이었나"를 기록만 한다.
    #   last_hit_element : "fire"/"ice"/"lightning"/"physical"/"bleed"/""
    #                      ★ "bleed"는 엔진의 원소가 아니다(element_queue에 절대
    #                        안 들어감) — 출혈 DoT를 색으로 구분하기 위한 표시용 값.
    #   last_hit_reaction: "melt"/"shatter"/"overload"/""
    #   last_hit_via     : "dot"(상태이상 지속피해) — 나머지(공격/스킬/아이템)는
    #                      이 시점에 알 수 없어서 세션이 TurnLog로 유도한다.
    # 쓰는 곳: Elements.apply_element_and_react(), 아래 tick_status_effects().
    # 읽는 곳: ai/battle_session/State.py._hits_from_snapshot() 한 곳뿐.
    # step() 진입 시 _hp_snapshot()이 전부 ""로 지우므로 지난 턴 값이 안 묻는다.
    last_hit_element: str = ""
    last_hit_reaction: str = ""
    last_hit_via: str = ""
    # 표시 전용 피격 장부 — UI 숫자/이펙트를 "순변화량"이 아니라 실제로 일어난
    #   피해·흡수·회복·실드 획득 단위로 만들기 위한 기록. None이면 기록하지 않는다
    #   (시뮬 경로의 기본값 — 추가 비용 0). BattleSession이 step 진입 시 []로 켜고
    #   끝나면 다시 None으로 끈다. 전투 계산은 이 값을 절대 읽지 않는다.
    #   항목: {"kind": damage|absorb|heal|shield, "amount", "via", "element", "reaction"}
    hit_ledger: list | None = None

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
        # pack_bonus: 고블린 무리 전술 — 버프 목록이 아니라 전용 필드인 이유는 apply_buff()가
        # 같은 stat 항목을 덮어써서 전투 함성·사제축복과 서로 지워 버리기 때문 (기본 0.0)
        return max(1.0, self.stg * (1 - debuff_r + buff_r + self.pack_bonus))

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
        # buff 기반 효율 (효율성 스킬 등 한정 시간 효과)
        # ※ 구 마법사 패시브(영구 MP 30% 감소)는 제거됨 —
        #    새 마법사 패시브는 원소 반응 기반 (Elements.py 참고)
        reduction = sum(b.amount for b in self.buffs if b.stat == "mp_efficiency")
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
            self._record_hit("heal", self.hp - before, via="passive")
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
            self._record_hit("heal", self.hp - before, via="passive")
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

    def _record_hit(self, kind: str, amount: float, via: str = "",
                    element: str | None = None, reaction: str | None = None) -> None:
        """hit_ledger에 한 줄 남긴다 (표시 전용 — 계산에 영향 없음).
        amount는 실제로 변한 양(상한에 걸려 잘린 뒤의 값)을 넘겨야 한다.
        element/reaction을 생략하면 직전 _stamp_last_hit 값을 쓴다 — 피해 적용
        직전에 apply_element_and_react()가 도장을 찍는 순서를 그대로 이용한다."""
        if self.hit_ledger is None or amount <= 0:
            return
        self.hit_ledger.append({
            "kind":     kind,
            "amount":   float(amount),
            "via":      via,
            "element":  self.last_hit_element  if element  is None else element,
            "reaction": self.last_hit_reaction if reaction is None else reaction,
        })

    def _stamp_last_hit(self, element: str, reaction: str = "", via: str = "") -> None:
        """받은 피해의 출처를 표시용으로 기록 (UI 데미지 숫자 색 구분).
        ★ 전투 계산에는 전혀 쓰이지 않는다 — 쓰기 전용 필드다.
        한 step 안에서 같은 대상을 여러 번 때리면 마지막 출처가 남는다
        (숫자도 대상별 합계 1개라 색도 1개 — State._hits_from_snapshot 참고).
        via는 확실히 아는 곳(DoT)에서만 채우고, 나머지는 세션이 TurnLog로 유도."""
        self.last_hit_element  = element or ""
        self.last_hit_reaction = reaction or ""
        if via:
            self.last_hit_via = via

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
                before = self.hp
                self.hp = max(0.0, self.hp - dmg)
                self._stamp_last_hit("fire", via="dot")   # UI 숫자 색 (표시 전용)
                self._record_hit("damage", before - self.hp, via="dot")
                msgs.append(f"🔥 [{self.name}] 점화 -{dmg} HP")
            elif eff.effect_type == "bleed":
                # 도적 주사위 출혈: 매턴 maxhp의 4~7% 랜덤 데미지 (크리 미적용)
                rate = uniform(0.04, 0.07)
                dmg = max(1, int(self.maxhp * rate))
                before = self.hp
                self.hp = max(0.0, self.hp - dmg)
                self._stamp_last_hit("bleed", via="dot")  # UI 숫자 색 (표시 전용)
                self._record_hit("damage", before - self.hp, via="dot")
                msgs.append(f"🩸 [{self.name}] 출혈 -{dmg} HP")
            elif eff.effect_type == "rift":
                # 균열 — 점화와 같은 고정 비율 DoT. 물리 공격의 여파라 숫자 색은 physical.
                dmg = max(1, int(self.maxhp * eff.dot_rate))
                before = self.hp
                self.hp = max(0.0, self.hp - dmg)
                self._stamp_last_hit("physical", via="dot")  # UI 숫자 색 (표시 전용)
                self._record_hit("damage", before - self.hp, via="dot")
                msgs.append(f"🌑 [{self.name}] 균열 -{dmg} HP")
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
            atb_remainder=float(getattr(player, "atb_remainder", 0.0)),
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
            is_elite=getattr(enemy, "is_elite", False),
            elite_leader=getattr(enemy, "elite_leader", False),
        )
        # 원소 슬라임 등: 전투 시작 시 초기 원소 큐 설정
        init_q = getattr(enemy, "init_element_queue", [])
        if init_q:
            snap.element_queue = list(init_q)
        # 안전망: 변환 과정에서 큐가 유실됐어도 원소 슬라임은 이름으로 복구
        if not snap.element_queue:
            _elem_by_name = {
                "화염 슬라임": "fire",
                "빙결 슬라임": "ice",
                "번개 슬라임": "lightning",
            }
            _key = snap.enemy_type or snap.name
            _elem = _elem_by_name.get(_key) or _elem_by_name.get(snap.name)
            if _elem:
                snap.element_queue = [_elem]
                if not snap.attack_element:
                    snap.attack_element = _elem
        return snap


# ────────────────────────────────────────────
# TurnLog / BattleResult
# ────────────────────────────────────────────