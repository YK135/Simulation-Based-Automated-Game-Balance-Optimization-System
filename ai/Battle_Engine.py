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
        return max(1.0, self.spd * (1 - debuff_r + buff_r))

    def mp_cost_multiplier(self) -> float:
        reduction = sum(b.amount for b in self.buffs if b.stat == "mp_efficiency")
        return max(0.3, 1.0 - reduction)

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
        )

    @classmethod
    def from_enemy(cls, enemy) -> "EntitySnapshot":
        return cls(
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
        )


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
    ROLE_MULT = {
        "player": 1.0,
        "monster": 1.0,  # 1.1 → 1.0: 몬스터 기본 10% 추가 피해 제거, 공정한 기준선으로 통일
    }

    @staticmethod
    def _calc(
        atk_stat: float,
        def_stat: float,
        atk_luc: float,
        def_luc: float,
        skill_mult: float,
        role_mult: float,
    ) -> tuple[int, bool, bool]:
        evade_chance = min(def_luc * 0.4, 25)
        if randint(1, 100) <= evade_chance:
            return 0, True, False

        base = atk_stat * 100 / (100 + def_stat)
        base = max(base, atk_stat * 0.2)
        base *= skill_mult
        base *= role_mult
        base *= uniform(0.9, 1.1)

        crit_chance = min(atk_luc * 0.5, 40)
        is_crit = randint(1, 100) <= crit_chance
        if is_crit:
            base *= 1.5

        return int(base), False, is_crit

    @staticmethod
    def physical(
        atk_stg: float,
        atk_luc: float,
        def_arm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_stg, def_arm, atk_luc, def_luc,
            skill_mult, role_mult
        )

    @staticmethod
    def magical(
        atk_sp: float,
        atk_luc: float,
        def_sparm: float,
        def_luc: float,
        skill_mult: float = 1.0,
        role: str = "player",
    ) -> tuple[int, bool, bool]:
        role_mult = DamageCalc.ROLE_MULT.get(role, 1.0)
        return DamageCalc._calc(
            atk_sp, def_sparm, atk_luc, def_luc,
            skill_mult, role_mult
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
        "mp": 13, "mult": 0.75, "type": "physical", "hits": 3  # 0.65 → 0.75
    },
    "강타1": {
        "mp": 10, "mult": 1.55, "type": "physical", "hits": 1  # 1.35 → 1.55
    },
    "강타2": {
        "mp": 16, "mult": 1.85, "type": "physical", "hits": 1  # 1.55 → 1.85
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
        "mp": 10, "mult": 1.50, "type": "magical", "hits": 1  # 1.35 → 1.50
    },
    "파이어볼2": {
        "mp": 16, "mult": 1.70, "type": "magical", "hits": 1  # 1.55 → 1.70
    },
    "아이스볼릿1": {
        "mp": 11, "mult": 1.25, "type": "magical", "hits": 1,
        "debuff_stat": "spd", "debuff_chance": 0.3,
        "debuff_amount": (0.10, 0.15), "debuff_turns": (2, 3)
    },
    "아이스볼릿2": {
        "mp": 17, "mult": 1.45, "type": "magical", "hits": 1,
        "debuff_stat": "spd", "debuff_chance": 0.5,
        "debuff_amount": (0.15, 0.20), "debuff_turns": (2, 3)
    },
    "라이트닝1": {
        "mp": 12, "mult": 1.55, "type": "magical", "hits": 1  # 1.40 → 1.55
    },
    "라이트닝2": {
        "mp": 19, "mult": 1.75, "type": "magical", "hits": 1  # 1.60 → 1.75
    },
    "힐1": {
        "mp": 12, "type": "heal",
        "base_heal": 80, "sp_mult": 1.2, "cap": 0.22
    },
    "힐2": {
        "mp": 20, "type": "heal",
        "base_heal": 150, "sp_mult": 1.35, "cap": 0.35
    },
    "효율성1": {
        "mp": 14, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.20, "buff_turns": 2
    },
    "효율성2": {
        "mp": 22, "type": "buff",
        "buff_stat": "mp_efficiency", "buff_amount": 0.35, "buff_turns": 2
    },

    "몸통박치기1": {
        "mp": 8, "type": "tank_attack",
        "arm_mult": 1.4, "hp_mult": 0.03
    },
    "몸통박치기2": {
        "mp": 13, "type": "tank_attack",
        "arm_mult": 1.6, "hp_mult": 0.04
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
        "mp": 15, "mult": 1.40, "type": "physical", "hits": 1,
        "luc_bonus": 1.2
    },
    "연속찌르기": {
        "mp": 14, "type": "multi_hit",
        "max_hits": 4, "base_prob": 5, "luc_mult": 5,
        "prob_decay": 15, "dmg_decay": 0.75
    },
    "난사1": {
        "mp": 12, "mult": 0.65, "type": "physical", "hits": 1, "aoe": True
    },
    "난사2": {
        "mp": 18, "mult": 0.85, "type": "physical", "hits": 1, "aoe": True
    },
    "추진력": {
        "mp": 13, "type": "buff",
        "buff_stat": "spd", "buff_amount": 0.15, "buff_turns": 2
    },
}


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
        return int(damage), False, ""

    if stype == "counter":
        damage = (attacker.last_damage_taken * meta["counter_mult"]) + (attacker.effective_arm() * meta["arm_mult"])
        damage = min(damage, attacker.maxhp * meta["cap"])
        damage *= uniform(0.9, 1.1)
        return int(damage), False, ""

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

        for i in range(hit_count):
            raw, _, _ = DamageCalc.physical(
                attacker.effective_stg(),
                attacker.luc,
                defender.effective_arm(),
                defender.luc,
                skill_mult=1.0,
            )
            total += int(raw * (dmg_decay ** i))

        return total, False, ""

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
        return total, False, skill_name

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
            )
            actual = 0 if is_dodge else _apply_damage_with_shield(defender, dmg)
            log.damage_dealt = actual
            log.hp_after = defender.hp
            log.is_dodge = is_dodge
            log.is_crit = is_crit

        elif action.action_type == "skill":
            dmg, mp_lack, info = execute_skill(action.detail, attacker, defender)
            log.mp_after = attacker.mp

            if not mp_lack:
                if dmg > 0:
                    actual = _apply_damage_with_shield(defender, dmg)
                    log.damage_dealt = actual
                    log.hp_after = defender.hp
                else:
                    log.hp_after = defender.hp

                if info:
                    log.debuff_applied = info
            else:
                dmg, is_dodge, is_crit = DamageCalc.physical(
                    attacker.effective_stg(), attacker.luc,
                    defender.effective_arm(), defender.luc,
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