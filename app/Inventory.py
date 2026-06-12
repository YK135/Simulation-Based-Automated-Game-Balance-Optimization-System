"""
app/inventory.py — 인벤토리 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/use_item                — 필드에서 아이템 사용
  POST /api/inventory/swap_special  — 특수 슬롯 교체
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from game.Inventory    import Inventory
from ai.battle.Battle_Engine  import ITEM_META

from .Shared import _get_session, _player_dict

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


@inventory_bp.route("/api/inventory/swap_special", methods=["POST"])
def inventory_swap_special():
    """
    특수 슬롯 가득 시: 기존 아이템 1개 버리고 새 아이템 추가.
    요청: { "drop": "bomb", "new": "fire_bottle" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data     = request.get_json() or {}
    drop_item = data.get("drop", "")
    new_item  = data.get("new",  "")

    if not drop_item or not new_item:
        return jsonify({"ok": False, "error": "drop과 new를 모두 지정해야 합니다."}), 400

    inv    = gs["inventory"]
    result = inv.swap_special(drop_item, new_item)

    if not result["ok"]:
        return jsonify({"ok": False, "error": result.get("message", "교체 실패")}), 400

    gs["items"] = inv.to_flat_list()

    return jsonify({
        "ok":      True,
        "dropped": result["dropped"],
        "added":   result["added"],
        "message": f"{result['dropped']}을(를) 버리고 {result['added']}을(를) 획득!",
        "player":  _player_dict(gs["player"], inv),
    })