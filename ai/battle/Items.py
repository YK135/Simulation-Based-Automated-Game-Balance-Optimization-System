"""Battle/Items.py — ITEM_META, use_item"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from random import randint, random, uniform

from .Entity import EntitySnapshot, Debuff
from .Elements import apply_element_and_react

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
        "amount": lambda u: max(30,  int(u.maxmp * 0.15))
    },
    "MP_M_potion": {
        "slot": "potion", 
        "stat": "mp", 
        "amount": lambda u: max(50,  int(u.maxmp * 0.25))
    },
    "MP_L_potion": {
        "slot": "potion", 
        "stat": "mp", 
        "amount": lambda u: max(70,  int(u.maxmp * 0.35))
    },

    # ── 특수 아이템 (special 슬롯, 최대 3개) ──
    # 데미지는 적 maxhp 비례 % 피해. category로 처리 분기.
    "bomb": {
        "slot": "special", "category": "aoe_damage", "target": "all",
        "damage_ratio": 0.25, "desc": "적 전체 25% 피해",
    },
    "web_bomb": {
        "slot": "special", "category": "aoe_damage", "target": "all",
        "damage_ratio": 0.18, "debuff_stat": "spd",
        "debuff_amount": 0.30, "debuff_turns": 2,
        "desc": "적 전체 18% 피해 + 2턴 속도↓",
    },
    "fire_vial": {
        "slot": "special", "category": "element", "target": "single",
        "element": "fire", "damage_ratio": 0.10, "desc": "단일 적 화염 부착",
    },
    "ice_vial": {
        "slot": "special", "category": "element", "target": "single",
        "element": "ice", "damage_ratio": 0.10, "desc": "단일 적 빙결 부착",
    },
    "lightning_crystal": {
        "slot": "special", "category": "element", "target": "single",
        "element": "lightning", "damage_ratio": 0.10, "desc": "단일 적 번개 부착",
    },
    "focus_drug": {
        "slot": "special", "category": "buff", "target": "self",
        "buff_type": "next_skill_bonus", "bonus_mult": 1.5,
        "desc": "다음 스킬 추가 피해",
    },
    "haste_drug": {
        "slot": "special", "category": "buff", "target": "self",
        "buff_type": "atb_gain", "atb_bonus": 50,
        "desc": "다음 행동 후 ATB 추가 획득",
    },
}


def use_item(item_name: str, user: EntitySnapshot, enemies: list = None) -> bool:
    """
    공통 아이템 사용 (BattleEngine/시뮬/콘솔 공유 — Digital Twin).
    포션: amount 기반 HP/MP 회복.
    특수: category로 aoe_damage / element / buff 처리.
    enemies: 특수 아이템 대상 (단일 전투는 [enemy]).
    """
    meta = ITEM_META.get(item_name)
    if not meta or item_name not in user.items:
        return False

    category = meta.get("category", "")
    enemies = enemies or []
    alive = [e for e in enemies if getattr(e, "hp", 0) > 0]

    # ── 포션 (amount 기반) ──
    if "amount" in meta:
        amount = meta["amount"](user)
        if meta.get("stat") == "hp":
            user.hp = min(user.maxhp, user.hp + amount)
        elif meta.get("stat") == "mp":
            user.mp = min(user.maxmp, user.mp + amount)

    # ── AoE 데미지 ──
    elif category == "aoe_damage":
        ratio = meta.get("damage_ratio", 0.2)
        for tgt in alive:
            dmg = max(1, int(tgt.maxhp * ratio))
            tgt.hp = max(0, tgt.hp - dmg)
            if meta.get("debuff_stat") and hasattr(tgt, "apply_debuff"):
                tgt.apply_debuff(Debuff(
                    stat=meta["debuff_stat"], amount=meta["debuff_amount"],
                    turns=meta["debuff_turns"], name=item_name,
                ))

    # ── 원소 부착 ──
    elif category == "element":
        if alive:
            tgt = alive[0]
            elem = meta.get("element", "")
            dmg = max(1, int(tgt.maxhp * meta.get("damage_ratio", 0.1)))
            _msgs = []
            dmg = apply_element_and_react(user, tgt, elem, dmg, _msgs)
            tgt.hp = max(0, tgt.hp - dmg)

    # ── 버프 ──
    elif category == "buff":
        btype = meta.get("buff_type", "")
        if btype == "next_skill_bonus":
            user._next_skill_bonus = meta.get("bonus_mult", 1.5)
        elif btype == "atb_gain":
            user._pending_atb_bonus = meta.get("atb_bonus", 50)

    user.items.remove(item_name)
    return True


# ────────────────────────────────────────────
# 도망 확률
# ────────────────────────────────────────────