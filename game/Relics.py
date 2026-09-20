"""
game/Relics.py — 유물 목록·설명·가격·제시 규칙 (Combat Content Brief 7장 · 11-1 2차 7번)
─────────────────────────────────────────────
전투 효과 자체는 ai/battle/Relics.py(수치 상수 포함) — 여기는 "무엇을 어떻게 주는가".

규칙 (7장 「죽은 보상 방지」 + 사용자 결정 2026-09-17):
  · 공용 8종 — 모든 직업에게 제시되고 상점에도 진열된다(직업 전용은 meta의 job 필드로 거른다).
  · 3종 중 택 1: 엘리트 노드·보스 승리 시 아직 없는 유물 중 최대 3개를 보여주고 하나를 고르게 한다.
    다 마음에 안 들면 골드로 환전(RELIC_GOLD_CONVERT). 선택 없이 주어지는 유물은 없다.
  · 상점에서도 판다(RELIC_SHOP_PRICE) — 아직 없는 유물만 진열.
"""
from __future__ import annotations

from random import sample

from ai.battle.Relics import (
    RELIC_IDS, RELIC_HOURGLASS, RELIC_GREED_SEAL, RELIC_FROST_MARK, RELIC_PRIEST_REMAINS,
    RELIC_MIRROR_SHARD, RELIC_PROPHECY_BOOK, RELIC_LOOT_SACK, RELIC_TRAVELERS_MAP,
    HOURGLASS_ATB_MULT, GREED_GOLD_BONUS, GREED_POTION_SLOT_PENALTY,
    FROST_MARK_PHYS_BONUS, FROST_MARK_SHATTER_ATB, REMAINS_REVIVE_HP_RATIO,
    MIRROR_SHARD_TURN_CUT, LOOT_SACK_POTION_SLOT_BONUS, TRAVELERS_MAP_DISCOUNT,
    PROPHECY_TELEGRAPH_LEAD,
)

RELIC_OFFER_COUNT = 3        # 한 번에 보여주는 수
RELIC_GOLD_CONVERT = 60      # 전부 거절하고 골드로 환전할 때 (중형 포션 값 남짓)
RELIC_SHOP_PRICE = 200       # 상점 판매가 (영구 효과 — 특수 아이템 120~150보다 위)

RELIC_META = {
    RELIC_HOURGLASS: {
        "id": RELIC_HOURGLASS, "name": "깨진 모래시계", "icon": "⏳", "job": "",
        "short": f"잔여 ATB 이월 ×{HOURGLASS_ATB_MULT:.0f}",
        "desc": f"전투 종료 시 잔여 ATB가 {HOURGLASS_ATB_MULT:.0f}배로 다음 전투에 이월된다",
    },
    RELIC_GREED_SEAL: {
        "id": RELIC_GREED_SEAL, "name": "탐욕의 인장", "icon": "💰", "job": "",
        "short": f"골드 +{int(GREED_GOLD_BONUS * 100)}% · 포션칸 −{GREED_POTION_SLOT_PENALTY}",
        "desc": f"골드 획득 +{int(GREED_GOLD_BONUS * 100)}%, 대신 포션 슬롯 −{GREED_POTION_SLOT_PENALTY}",
    },
    RELIC_FROST_MARK: {
        "id": RELIC_FROST_MARK, "name": "서리 사냥꾼의 각인", "icon": "❄", "job": "",
        "short": f"ice 적에 물리 +{int(FROST_MARK_PHYS_BONUS * 100)}%",
        "desc": f"ice가 부착된 적에게 주는 물리 피해 +{int(FROST_MARK_PHYS_BONUS * 100)}%, 파쇄를 터뜨리면 ATB +{int(FROST_MARK_SHATTER_ATB)}",
    },
    RELIC_PRIEST_REMAINS: {
        "id": RELIC_PRIEST_REMAINS, "name": "사제의 유해", "icon": "💀", "job": "",
        "short": f"전투당 1회 부활 {int(REMAINS_REVIVE_HP_RATIO * 100)}%",
        "desc": f"전투당 1회, HP가 0이 될 때 최대 HP {int(REMAINS_REVIVE_HP_RATIO * 100)}%로 되살아난다",
    },
    # ── 공용 추가 4종 (브리프 7장 「유물 확장」) ──
    RELIC_MIRROR_SHARD: {
        "id": RELIC_MIRROR_SHARD, "name": "거울 파편", "icon": "🪞", "job": "",
        "short": f"디버프 지속 −{MIRROR_SHARD_TURN_CUT}턴 (양쪽)",
        "desc": f"내가 받는 디버프도, 내가 거는 디버프도 지속이 {MIRROR_SHARD_TURN_CUT}턴 짧아진다 (최소 1턴)",
    },
    RELIC_PROPHECY_BOOK: {
        "id": RELIC_PROPHECY_BOOK, "name": "예언서", "icon": "📖", "job": "",
        "short": f"적 예고를 {PROPHECY_TELEGRAPH_LEAD}행동 먼저",
        "desc": f"적의 예고·스택 배지가 {PROPHECY_TELEGRAPH_LEAD}행동 먼저 경고 상태로 바뀐다",
    },
    RELIC_LOOT_SACK: {
        "id": RELIC_LOOT_SACK, "name": "전리품 자루", "icon": "🎒", "job": "",
        "short": f"포션칸 +{LOOT_SACK_POTION_SLOT_BONUS}",
        "desc": f"포션 슬롯 +{LOOT_SACK_POTION_SLOT_BONUS} (탐욕의 인장을 함께 가지면 정확히 상쇄된다)",
    },
    RELIC_TRAVELERS_MAP: {
        "id": RELIC_TRAVELERS_MAP, "name": "여행자의 지도", "icon": "🗺", "job": "",
        "short": f"상점 아이템 −{int(TRAVELERS_MAP_DISCOUNT * 100)}%",
        "desc": f"상점의 포션·특수 아이템 가격 {int(TRAVELERS_MAP_DISCOUNT * 100)}% 할인 (유물 가격은 제외)",
    },
}


def relic_public(relic_id: str) -> dict | None:
    """프론트에 내려주는 유물 정보 (id·name·icon·desc)."""
    meta = RELIC_META.get(relic_id)
    return dict(meta) if meta else None


def relic_list_public(relic_ids) -> list:
    return [m for m in (relic_public(r) for r in (relic_ids or [])) if m]


def available_relics(owned, job: str = "") -> list:
    """아직 없는 유물 id 목록 — 직업 전용 유물이 생기면 job으로 거른다 (지금은 전부 공용)."""
    owned = set(owned or [])
    out = []
    for rid in RELIC_IDS:
        meta = RELIC_META[rid]
        if rid in owned:
            continue
        if meta.get("job") and meta["job"] != job:
            continue
        out.append(rid)
    return out


def relic_choices(owned, job: str = "", k: int = RELIC_OFFER_COUNT, rng_sample=sample) -> list:
    """제시할 유물 id 최대 k개(무작위). 남은 것이 없으면 []."""
    pool = available_relics(owned, job)
    if not pool:
        return []
    return list(rng_sample(pool, min(k, len(pool))))


def shop_relic_items(owned, job: str = "") -> list:
    """상점 진열용 — 아직 없는 유물을 app/Map.py의 상품 dict 형식으로."""
    # effect는 카드에 들어가는 짧은 문구(다른 상품의 "HP +60%"와 같은 길이), desc는 툴팁용 전체 설명
    return [{
        "id": rid, "name": RELIC_META[rid]["name"], "type": "relic",
        "effect": RELIC_META[rid]["short"], "desc": RELIC_META[rid]["desc"],
        "price": RELIC_SHOP_PRICE, "icon": RELIC_META[rid]["icon"],
    } for rid in available_relics(owned, job)]
