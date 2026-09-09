"""
app/inventory.py — 인벤토리 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/use_item        — 필드에서 아이템 사용
  POST /api/inventory/swap  — 슬롯 교체 (포션/특수 공용, 가득 찼을 때)
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ai.battle.Battle_Engine  import ITEM_META

from .Shared import _get_session, _player_dict, _pop_pending_swap, _register_pending_swap

inventory_bp = Blueprint("inventory", __name__)

@inventory_bp.route("/api/use_item", methods=["POST"])
def use_item():
    """
    필드 아이템 사용 (전투 외).
    요청: { "item": "HP_M_potion" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if gs["battle"] is not None:
        return jsonify({"ok": False, "error": "전투 중에는 전투 아이템 API를 사용하세요."})

    data      = request.get_json() or {}
    item_name = data.get("item", "")
    player    = gs["player"]

    # ── 사망 상태 차단 (치명 버그 수정: 사망 후 포션 부활 방지) ──
    #    프론트 차단만으로는 부족 — API 직접 호출도 막아야 함.
    if getattr(player, "hp", 0) <= 0:
        return jsonify({
            "ok": False,
            "error": "플레이어가 사망한 상태에서는 아이템을 사용할 수 없습니다.",
            "reason": "player_dead",
        }), 400

    if item_name not in gs["items"]:
        return jsonify({"ok": False, "error": "해당 아이템이 없습니다."})

    meta = ITEM_META.get(item_name)
    if not meta:
        return jsonify({"ok": False, "error": "알 수 없는 아이템입니다."})

    # ── 특수 아이템 방어: 필드에서 사용 불가 (UI는 막지만 API 직접 호출 방어) ──
    #    특수 아이템은 amount/stat가 없어 아래 코드에서 500이 나므로 먼저 차단.
    if meta.get("slot") == "special" or meta.get("category"):
        return jsonify({
            "ok": False,
            "error": "특수 아이템은 전투 중에만 사용할 수 있습니다.",
            "reason": "battle_only",
        }), 400

    if "amount" not in meta or "stat" not in meta:
        return jsonify({
            "ok": False,
            "error": "필드에서 사용할 수 없는 아이템입니다.",
            "reason": "not_field_item",
        }), 400

    amount = meta["amount"](player) if callable(meta["amount"]) else meta["amount"]

    if meta["stat"] == "hp":
        before    = int(player.hp)
        player.hp = min(player.maxhp, player.hp + amount)
        gs["inventory"].remove(item_name)
        gs["items"] = gs["inventory"].to_flat_list()
        return jsonify({
            "ok":      True,
            "message": f"{item_name} 사용 → HP {before} → {int(player.hp)}",
            "player":  _player_dict(player, gs["inventory"]),
        })

    elif meta["stat"] == "mp":
        before    = int(player.mp)
        player.mp = min(player.maxmp, player.mp + amount)
        gs["inventory"].remove(item_name)
        gs["items"] = gs["inventory"].to_flat_list()
        return jsonify({
            "ok":      True,
            "message": f"{item_name} 사용 → MP {before} → {int(player.mp)}",
            "player":  _player_dict(player, gs["inventory"]),
        })

    return jsonify({"ok": False, "error": "사용할 수 없는 아이템입니다."})


@inventory_bp.route("/api/inventory/swap", methods=["POST"])
def inventory_swap():
    """
    포션/특수 슬롯 가득 시: 기존 아이템 1개 버리고 새 아이템 추가.
    요청: { "drop": "bomb", "new": "fire_bottle" }

    ★ new는 "서버가 실제로 발급 대기 중인 아이템"이어야 한다 — 예전엔 클라이
      언트가 보낸 new를 그대로 믿고 인벤토리에 넣어서, 상점/이벤트/전투보상
      경로를 거치지 않은 임의의 아이템을 이 API 직접 호출만으로 얻을 수
      있었다(상점 구매 건은 결제도 없이 얻는 것까지 가능했음). gs["pending_
      swaps"]에 등록된 티켓과 정확히 일치하는 항목만 소모한다 — 상점 구매
      (source="shop")였던 티켓은 슬롯이 가득 찼던 시점엔 아직 결제 전이었으
      므로 여기서 실제로 결제한다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data     = request.get_json() or {}
    drop_item = data.get("drop", "")
    new_item  = data.get("new",  "")

    if not drop_item or not new_item:
        return jsonify({"ok": False, "error": "drop과 new를 모두 지정해야 합니다."}), 400

    ticket = _pop_pending_swap(gs, new_item)
    if ticket is None:
        return jsonify({"ok": False, "error": "교체로 받을 수 있는 아이템이 아닙니다.",
                        "reason": "no_pending_swap"}), 400

    price = ticket.get("price", 0)
    if ticket.get("source") == "shop" and price:
        gold = gs.get("gold", 0)
        if gold < price:
            # 티켓은 아직 유효하니 되돌려 놓는다 — 골드가 부족해졌다고
            # 대기 중이던 구매 자체를 잃을 이유는 없음.
            _register_pending_swap(gs, new_item, source="shop", price=price)
            return jsonify({"ok": False, "error": f"골드가 부족합니다. (보유: {gold}G)"}), 400
        gs["gold"] = gold - price

    inv    = gs["inventory"]
    result = inv.swap_item(drop_item, new_item)

    if not result["ok"]:
        # 스왑 자체가 실패(drop_item 없음 등)했으면 결제/티켓을 원상복구.
        if ticket.get("source") == "shop" and price:
            gs["gold"] = gs.get("gold", 0) + price
        _register_pending_swap(gs, new_item, source=ticket.get("source", "reward"), price=price)
        return jsonify({"ok": False, "error": result.get("message", "교체 실패")}), 400

    gs["items"] = inv.to_flat_list()

    resp = {
        "ok":      True,
        "dropped": result["dropped"],
        "added":   result["added"],
        "message": f"{result['dropped']}을(를) 버리고 {result['added']}을(를) 획득!",
        "player":  _player_dict(gs["player"], inv),
    }
    if ticket.get("source") == "shop":
        resp["gold"] = gs.get("gold", 0)
    return jsonify(resp)