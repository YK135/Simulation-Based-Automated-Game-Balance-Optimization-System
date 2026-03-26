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

예시 (플레이어 spd=30 / 적 spd=10):
  틱4  플레이어 120pt → 행동! (초기화)
  틱8  플레이어 120pt → 행동! (초기화)
  틱10 적 100pt       → 행동!
  → 플레이어 2번 행동 : 적 1번 행동 비율로 자연스럽게 동작
"""

import copy
from dataclasses import dataclass, field
from random import randint, random


# ────────────────────────────────────────────
# Debuff
# ────────────────────────────────────────────

@dataclass
class Debuff:
    """
    stat   : "arm" | "sparm" | "stg" | "spd"
    amount : 감소 비율 (0.0~1.0)
    turns  : 남은 지속 행동 수
    name   : 디버프 스킬명
    """
    stat:   str
    amount: float
    turns:  int
    name:   str


# ────────────────────────────────────────────
# EntitySnapshot
# ────────────────────────────────────────────

@dataclass
class EntitySnapshot:
    name:   str
    hp:     float
    maxhp:  float
    mp:     float
    maxmp:  float
    stg:    float
    arm:    float
    sparm:  float
    sp:     float
    luc:    float
    lv:     int
    spd:    float = 10.0
    learned_skills: list = field(default_factory=list)
    items:          list = field(default_factory=list)
    debuffs:        list = field(default_factory=list)

    def effective_stg(self) -> float:
        r = sum(d.amount for d in self.debuffs if d.stat == "stg")
        return max(1.0, self.stg * (1 - r))

    def effective_arm(self) -> float:
        r = sum(d.amount for d in self.debuffs if d.stat == "arm")
        return max(0.0, self.arm * (1 - r))

    def effective_sparm(self) -> float:
        r = sum(d.amount for d in self.debuffs if d.stat == "sparm")
        return max(0.0, self.sparm * (1 - r))

    def effective_spd(self) -> float:
        r = sum(d.amount for d in self.debuffs if d.stat == "spd")
        return max(1.0, self.spd * (1 - r))

    def apply_debuff(self, debuff: Debuff):
        for existing in self.debuffs:
            if existing.name == debuff.name:
                existing.turns = debuff.turns
                return
        self.debuffs.append(copy.copy(debuff))

    def tick_debuffs(self):
        """행동 1회 후 호출"""
        alive = []
        for d in self.debuffs:
            if d.turns > 1:
                d.turns -= 1
                alive.append(d)
        self.debuffs = alive

    @classmethod
    def from_player(cls, player) -> "EntitySnapshot":
        skills = []
        if hasattr(player, 'skill') and player.skill:
            skills = list(player.skill.learned_skills)
        return cls(
            name=player.name,
            hp=player.hp,       maxhp=player.maxhp,
            mp=player.mp,       maxmp=player.maxmp,
            stg=player.stg,     arm=player.arm,
            sparm=player.sparm, sp=player.sp,
            luc=player.luc,     lv=player.lv,
            spd=getattr(player, 'spd', 10.0),
            learned_skills=skills,
        )

    @classmethod
    def from_enemy(cls, enemy) -> "EntitySnapshot":
        return cls(
            name=enemy.name,
            hp=enemy.hp,        maxhp=enemy.hp,
            mp=getattr(enemy, 'mp', 0),
            maxmp=getattr(enemy, 'mp', 0),
            stg=enemy.stg,      arm=enemy.arm,
            sparm=getattr(enemy, 'sparm', 0),
            sp=getattr(enemy, 'sp', 0),
            luc=enemy.luc,      lv=enemy.lv,
            spd=getattr(enemy, 'spd', 10.0),
        )


# ────────────────────────────────────────────
# TurnLog / BattleResult
# ────────────────────────────────────────────

@dataclass
class TurnLog:
    turn:           int
    actor:          str
    action:         str
    action_detail:  str
    damage_dealt:   int   = 0
    hp_after:       float = 0.0
    mp_after:       float = 0.0
    is_dodge:       bool  = False
    is_crit:        bool  = False
    debuff_applied: str   = ""
    debuff_missed:  bool  = False  # 디버프 빗나감 여부
    escaped:        bool  = False
    player_pt:      float = 0.0   # 디버그용 ATB 포인트 스냅샷
    enemy_pt:       float = 0.0


@dataclass
class BattleResult:
    winner:          str
    total_turns:     int
    logs:            list
    final_player_hp: float
    final_enemy_hp:  float
    player_name:     str
    enemy_name:      str


# ────────────────────────────────────────────
# ATB 시스템
# ────────────────────────────────────────────

class ATBSystem:
    """
    Active Time Battle 포인트 시스템.

    tick() 호출마다 양쪽 포인트를 spd 만큼 누적.
    100 이상이 되면 행동권 발생 → 해당 객체 포인트 0 초기화.
    동시에 100 이상이면 포인트 높은 쪽이 먼저 행동.
    """

    THRESHOLD = 100

    # x: 스피드에 곱하는 배율 (기본 1.0 → spd 수치 그대로 포인트 누적)
    # 예) x=2.0이면 spd=10인 객체가 매 틱 20pt 누적
    SPD_MULTIPLIER: float = 1.0

    def __init__(self, spd_multiplier: float = 1.0):
        self.player_pt: float = 0.0
        self.enemy_pt:  float = 0.0
        self.x = spd_multiplier   # 스피드 × x = 틱당 누적 포인트

    def tick(self, player_spd: float, enemy_spd: float) -> list[str]:
        """
        한 틱 진행.
        포인트 누적: (spd × x) 만큼 매 틱 가산
        반환: 이 틱에 행동할 객체 목록 (행동 순서 순)
              [] | ["player"] | ["enemy"] | ["player","enemy"] | ["enemy","player"]
        """
        self.player_pt += max(1.0, player_spd * self.x)
        self.enemy_pt  += max(1.0, enemy_spd  * self.x)

        candidates = []
        if self.player_pt >= self.THRESHOLD:
            candidates.append(("player", self.player_pt))
        if self.enemy_pt >= self.THRESHOLD:
            candidates.append(("enemy", self.enemy_pt))

        # 포인트 높은 순, 동점은 player 우선
        candidates.sort(key=lambda x: (x[1], 1 if x[0] == "player" else 0), reverse=True)
        actors = [c[0] for c in candidates]

        if "player" in actors:
            self.player_pt = 0.0
        if "enemy" in actors:
            self.enemy_pt  = 0.0

        return actors

    def reset(self):
        self.player_pt = 0.0
        self.enemy_pt  = 0.0


# ────────────────────────────────────────────
# 데미지 계산
# ────────────────────────────────────────────

class DamageCalc:

    @staticmethod
    def physical(atk_stg, atk_luc, def_arm, def_luc) -> tuple[int, bool, bool]:
        if randint(1, 100) <= def_luc:
            return 0, True, False
        rd   = randint(1, max(1, randint(1, 10)))
        base = (atk_stg * 100 / (100 + def_arm) * 10) + rd
        is_crit = randint(1, 100) <= atk_luc
        if is_crit:
            base *= 1.5
        return int(base), False, is_crit

    @staticmethod
    def magical(atk_sp, atk_luc, def_sparm, def_luc) -> tuple[int, bool, bool]:
        if randint(1, 100) <= def_luc:
            return 0, True, False
        rd   = randint(1, max(1, randint(1, 10)))
        base = (atk_sp * 100 / (100 + def_sparm) * 10) + rd
        is_crit = randint(1, 100) <= atk_luc
        if is_crit:
            base *= 1.5
        return int(base), False, is_crit


# ────────────────────────────────────────────
# 스킬 메타데이터
# ────────────────────────────────────────────

SKILL_META = {
    "셰이드 1":      {"mp": 0,  "mult": 0.7, "type": "physical", "hits": 2},
    "셰이드 2":      {"mp": 0,  "mult": 0.7, "type": "physical", "hits": 3},
    "파이어볼 1":    {"mp": 10, "mult": 1.4, "type": "magical",  "hits": 1},
    "파이어볼 2":    {"mp": 13, "mult": 1.6, "type": "magical",  "hits": 1},
    "파이어볼 3":    {"mp": 15, "mult": 1.8, "type": "magical",  "hits": 1},
    "아이스 볼릿 1": {"mp": 7,  "mult": 1.5, "type": "magical",  "hits": 1},
    "아이스 볼릿 2": {"mp": 15, "mult": 1.7, "type": "magical",  "hits": 1},
    "아이스 볼릿 3": {"mp": 25, "mult": 2.0, "type": "magical",  "hits": 1},
    # hit_rate: 디버프 적중 확률 — 방어력/공격력/마방 계열 70%, 스피드 80%
    "약화 1":   {"mp": 8,  "type": "debuff", "debuff_stat": "arm",
                 "debuff_amount": (0.10, 0.15), "debuff_turns": (3, 4), "hit_rate": 0.70},
    "약화 2":   {"mp": 14, "type": "debuff", "debuff_stat": "arm",
                 "debuff_amount": (0.15, 0.25), "debuff_turns": (4, 5), "hit_rate": 0.70},
    "마약화 1": {"mp": 8,  "type": "debuff", "debuff_stat": "sparm",
                 "debuff_amount": (0.10, 0.15), "debuff_turns": (3, 4), "hit_rate": 0.70},
    "마약화 2": {"mp": 14, "type": "debuff", "debuff_stat": "sparm",
                 "debuff_amount": (0.15, 0.25), "debuff_turns": (4, 5), "hit_rate": 0.70},
    "저주 1":   {"mp": 10, "type": "debuff", "debuff_stat": "stg",
                 "debuff_amount": (0.10, 0.20), "debuff_turns": (3, 5), "hit_rate": 0.70},
    "저주 2":   {"mp": 18, "type": "debuff", "debuff_stat": "stg",
                 "debuff_amount": (0.20, 0.30), "debuff_turns": (4, 6), "hit_rate": 0.70},
    # 둔화: spd 감소 → ATB 포인트 누적 속도 직접 감소 / 적중률 80%
    "둔화 1":   {"mp": 7,  "type": "debuff", "debuff_stat": "spd",
                 "debuff_amount": (0.15, 0.25), "debuff_turns": (3, 4), "hit_rate": 0.80},
}


def execute_skill(
    skill_name: str,
    attacker:   EntitySnapshot,
    defender:   EntitySnapshot,
) -> tuple[int, bool, str]:
    """반환: (총_데미지, mp_부족, 적용된_디버프명)"""
    meta = SKILL_META.get(skill_name)
    if not meta:
        return 0, False, ""
    if attacker.mp < meta.get("mp", 0):
        return 0, True, ""

    attacker.mp -= meta["mp"]

    if meta["type"] == "debuff":
        # ── 적중 판정 (hit_rate: 방어력/공격력 70%, 스피드 80%) ──
        hit_rate = meta.get("hit_rate", 0.70)
        if random() > hit_rate:
            # 빗나감 — MP는 소모되었으나 디버프 미적용
            return 0, False, "miss"

        amt   = round(
            meta["debuff_amount"][0]
            + random() * (meta["debuff_amount"][1] - meta["debuff_amount"][0]), 2
        )
        turns = randint(meta["debuff_turns"][0], meta["debuff_turns"][1])
        defender.apply_debuff(Debuff(
            stat=meta["debuff_stat"], amount=amt, turns=turns, name=skill_name
        ))
        return 0, False, skill_name

    total = 0
    for _ in range(meta["hits"]):
        if meta["type"] == "physical":
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(), attacker.luc,
                defender.effective_arm(), defender.luc,
            )
        else:
            raw, _, _ = DamageCalc.magical(
                attacker.sp, attacker.luc,
                defender.effective_sparm(), defender.luc,
            )
        total += int(raw * meta["mult"])
    return total, False, ""


# ────────────────────────────────────────────
# 아이템
# ────────────────────────────────────────────

ITEM_META = {
    "HP_S_potion": {"stat": "hp", "amount": 50},
    "HP_M_potion": {"stat": "hp", "amount": 100},
    "HP_L_potion": {"stat": "hp", "amount": 150},
    "MP_S_potion": {"stat": "mp", "amount": 20},
    "MP_M_potion": {"stat": "mp", "amount": 40},
    "MP_L_potion": {"stat": "mp", "amount": 60},
}

def use_item(item_name: str, user: EntitySnapshot) -> bool:
    meta = ITEM_META.get(item_name)
    if not meta or item_name not in user.items:
        return False
    if meta["stat"] == "hp":
        user.hp = min(user.maxhp, user.hp + meta["amount"])
    elif meta["stat"] == "mp":
        user.mp = min(user.maxmp, user.mp + meta["amount"])
    user.items.remove(item_name)
    return True


# ────────────────────────────────────────────
# 도망 확률
# ────────────────────────────────────────────

def _escape_chance(player_spd: float, enemy_spd: float) -> float:
    ratio = player_spd / max(enemy_spd, 1.0)
    if ratio >= 2.0:   return 0.95
    elif ratio >= 1.5: return 0.80
    elif ratio >= 1.0: return 0.60
    elif ratio >= 0.7: return 0.35
    else:              return 0.15


# ────────────────────────────────────────────
# 전투 엔진
# ────────────────────────────────────────────

class BattleEngine:
    """ATB 포인트 기반 전투 엔진."""

    MAX_TICKS = 500

    def __init__(self, player: EntitySnapshot, enemy: EntitySnapshot,
                 spd_multiplier: float = 1.0):
        self.player       = copy.deepcopy(player)
        self.enemy        = copy.deepcopy(enemy)
        self.logs:        list[TurnLog] = []
        self.atb          = ATBSystem(spd_multiplier)
        self.tick_count   = 0
        self.action_count = 0

    def run(self, player_ai, enemy_ai) -> BattleResult:
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
                    action = player_ai(self.player, self.enemy)
                    res    = self._execute_action(action, self.player, self.enemy, "player")
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
            if "enemy" in actors:
                self.enemy.tick_debuffs()

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
            )
            defender.hp     -= dmg
            log.damage_dealt = dmg
            log.hp_after     = defender.hp
            log.is_dodge     = is_dodge
            log.is_crit      = is_crit

        elif action.action_type == "skill":
            dmg, mp_lack, debuff_name = execute_skill(action.detail, attacker, defender)
            if not mp_lack:
                defender.hp       -= dmg
                log.damage_dealt   = dmg
                log.hp_after       = defender.hp
                log.mp_after       = attacker.mp
                log.debuff_applied = debuff_name
            else:
                dmg, is_dodge, is_crit = DamageCalc.physical(
                    attacker.effective_stg(), attacker.luc,
                    defender.effective_arm(), defender.luc,
                )
                defender.hp      -= dmg
                log.action        = "attack"
                log.action_detail = "attack(mp_fallback)"
                log.damage_dealt  = dmg
                log.hp_after      = defender.hp
                log.is_dodge      = is_dodge
                log.is_crit       = is_crit

        elif action.action_type == "item":
            success           = use_item(action.detail, attacker)
            log.action_detail = action.detail if success else "item_failed"
            log.hp_after      = attacker.hp
            log.mp_after      = attacker.mp

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
    detail:      str = ""