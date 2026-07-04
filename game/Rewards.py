# -*- coding: utf-8 -*-
"""
game/Rewards.py — 전투 보상 (골드 + 아이템 드랍)
─────────────────────────────────────────────
전투 승리 시 골드/아이템 보상을 계산한다. (1차 적용)

담당:
  - 골드 계산 (등급 기반 + 다중 전투 보정)
  - 드랍 점수 계산 → 포션/특수 드랍 확률
  - 일반 전투 보상 / 엘리트 보상 (node_type == "elite"일 때만)
  - relics 필드는 구조만 열어둠 (유물 시스템은 추후 구현)

사용:
  from game.Rewards import calc_battle_rewards
  rewards = calc_battle_rewards(defeated_list, node_type)
  # → {"gold": 48, "items": ["HP_S_potion"], "relics": [], "messages": [...]}

규칙 (설계 문서 기준):
  · 확률은 1~100 정수 퍼센트로 통일 — roll은 randint(1, 100) <= percent
  · 등급 판정: difficulty(실측값) 우선 → grade → 기본 '중'
    (_SnapUnit의 grade는 getattr 기본값 '중'일 수 있어 difficulty가 신뢰도 높음)
"""
from __future__ import annotations
from random import randint, choices
from typing import List, Optional


# ─────────────────────────────────────────────
# 등급 판정 (경험치 시스템과 동일한 우선순위)
# ─────────────────────────────────────────────

_TIER_BY_DIFF = {"easy": "하", "normal": "중", "hard": "상"}


def _enemy_tier(e) -> str:
    """몬스터 등급 문자열 ('하'/'중'/'상'). difficulty 우선 → grade → 기본 '중'."""
    diff = getattr(e, "difficulty", "") or ""
    if diff in _TIER_BY_DIFF:
        return _TIER_BY_DIFF[diff]
    grade = getattr(e, "grade", "") or ""
    if grade in ("하", "중", "상"):
        return grade
    return "중"


# ─────────────────────────────────────────────
# 골드
# ─────────────────────────────────────────────

# 몬스터 1마리 골드 범위 (등급별)
_GOLD_RANGE = {
    "하": (10, 15),
    "중": (16, 20),
    "상": (21, 30),
}

# 다중 전투 골드 보정 (마릿수 → 총합 배율)
_MULTI_GOLD_MULT = {1: 1.00, 2: 1.05, 3: 1.10}


def _roll_gold(defeated: list) -> int:
    """일반 전투 골드 = Σ(마리별 골드) × 마릿수 보정, int 처리."""
    total = 0
    for e in defeated:
        lo, hi = _GOLD_RANGE[_enemy_tier(e)]
        total += randint(lo, hi)
    mult = _MULTI_GOLD_MULT.get(len(defeated), _MULTI_GOLD_MULT[3])
    return int(total * mult)


# ─────────────────────────────────────────────
# 드랍 점수 → 드랍 확률 (퍼센트, 1~100 정수 기준)
# ─────────────────────────────────────────────

_DROP_SCORE = {"하": 1, "중": 2, "상": 3}


def _drop_score(defeated: list) -> int:
    return sum(_DROP_SCORE[_enemy_tier(e)] for e in defeated)


def _potion_drop_percent(score: int) -> int:
    """일반 포션 드랍률(%) = min(45, 5 + score×5)."""
    return min(45, 5 + score * 5)


def _special_drop_percent(score: int) -> int:
    """특수 아이템 드랍률(%) = min(20, 3 + score×3)."""
    return min(20, 3 + score * 3)


# ─────────────────────────────────────────────
# 드랍 풀 (가중치)
# ─────────────────────────────────────────────

_POTION_POOL = {
    "HP_S_potion": 25,
    "MP_S_potion": 25,
    "HP_M_potion": 15,
    "MP_M_potion": 15,
    "HP_L_potion": 10,
    "MP_L_potion": 10,
}

_SPECIAL_POOL = {
    "bomb":              25,
    "web_bomb":          15,
    "fire_vial":         14,
    "ice_vial":          14,
    "lightning_crystal": 14,
    "focus_drug":        10,
    "haste_drug":        8,
}

# 엘리트 확정 포션 풀 (중형 이상)
_ELITE_POTION_POOL = {
    "HP_M_potion": 30,
    "MP_M_potion": 30,
    "HP_L_potion": 20,
    "MP_L_potion": 20,
}


def _pick_weighted(pool: dict) -> str:
    names = list(pool.keys())
    weights = list(pool.values())
    return choices(names, weights=weights, k=1)[0]


# ─────────────────────────────────────────────
# 보상 계산 (공개 API)
# ─────────────────────────────────────────────

def calc_battle_rewards(defeated: list, node_type: Optional[str] = None) -> dict:
    """
    전투 승리 보상 계산.

    Args:
        defeated : 처치한 몬스터 목록 (Unit | _SnapUnit | EntitySnapshot)
        node_type: 현재 노드 타입 ("battle"/"elite"/"boss"/None)
                   ★ 엘리트 보상은 node_type == "elite"일 때만.
                     (grade/difficulty가 '상'/hard라도 elite가 아니면 일반 보상)

    Returns:
        {"gold": int, "items": [str], "relics": [], "messages": [str]}
        relics는 유물 시스템(추후)용 자리 — 현재 항상 [].
    """
    if not defeated:
        return {"gold": 0, "items": [], "relics": [], "messages": []}

    if node_type == "elite":
        return _elite_rewards(defeated)
    return _normal_rewards(defeated)


def _normal_rewards(defeated: list) -> dict:
    gold = _roll_gold(defeated)
    score = _drop_score(defeated)

    items: List[str] = []
    # 일반 포션 드랍 (독립 판정)
    if randint(1, 100) <= _potion_drop_percent(score):
        items.append(_pick_weighted(_POTION_POOL))
    # 특수 아이템 드랍 (독립 판정)
    if randint(1, 100) <= _special_drop_percent(score):
        items.append(_pick_weighted(_SPECIAL_POOL))

    messages = [f"골드 {gold}G 획득!"]
    for it in items:
        messages.append(f"아이템 획득: {it}")

    return {"gold": gold, "items": items, "relics": [], "messages": messages}


def _elite_rewards(defeated: list) -> dict:
    """엘리트 보상 — 1마리 45~60G / 2마리 70~90G, 포션 1개 확정 + 특수 25~35%."""
    n = len(defeated)
    if n >= 2:
        gold = randint(70, 90)
    else:
        gold = randint(45, 60)

    items: List[str] = [_pick_weighted(_ELITE_POTION_POOL)]   # 포션 확정 1개
    # 특수 아이템: 25~35% 확률 (판정 시마다 확률 자체를 랜덤으로)
    if randint(1, 100) <= randint(25, 35):
        items.append(_pick_weighted(_SPECIAL_POOL))

    messages = [f"[엘리트 보상] 골드 {gold}G 획득!"]
    for it in items:
        messages.append(f"아이템 획득: {it}")

    return {"gold": gold, "items": items, "relics": [], "messages": messages}