"""Battle/Skills.py — SKILL_META, execute_skill"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform

from .Entity import EntitySnapshot, Debuff, Buff
from .Damage import DamageCalc
from .Elements import apply_element_and_react

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