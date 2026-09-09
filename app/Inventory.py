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
from game.Inventory import get_slot

from .Shared import _get_session, _player_dict, _pop_pending_swap, _restore_pending_swap

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
    포션/특수 슬롯 가득 시: 기존 아이템(들)을 버리고 대기 중이던 새 아이템을 추가.
    요청: { "ticket_id": "...", "drops": {"HP_S_potion": 2} }
    (하위 호환: {"drop": "HP_S_potion"} 형태도 {"HP_S_potion": 1}로 흡수)

    ★ 얻는 아이템은 클라이언트가 지정하지 않는다 — ticket_id가 가리키는 서버
      발급 티켓의 item을 그대로 쓴다. 예전엔 클라이언트가 보낸 new를 그대로
      믿고 인벤토리에 넣어서, 상점/이벤트/전투보상 경로를 거치지 않은 임의의
      아이템을 이 API 직접 호출만으로 얻을 수 있었다(상점 구매 건은 결제도
      없이 얻는 것까지 가능했음). ticket_id로 식별하는 이유(이름 매칭이 아닌
      이유)는 app/Shared.py의 _register_pending_swap() 주석 참고 — 같은
      아이템에 대해 유료/무료 티켓이 동시에 떠 있어도 정확한 티켓만 소모된다.
      상점 구매(source="shop")였던 티켓은 슬롯이 가득 찼던 시점엔 아직 결제
      전이었으므로 여기서 실제로 결제한다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data      = request.get_json() or {}
    ticket_id = data.get("ticket_id", "")
    drops     = data.get("drops")
    if drops is None:
        single = data.get("drop", "")
        drops = {single: 1} if single else {}

    if not ticket_id or not drops:
        return jsonify({"ok": False, "error": "ticket_id와 drops를 모두 지정해야 합니다."}), 400

    # 수량은 정수만 신뢰 — 나머지 검증(실제 보유량 등)은 discard_multi()가 다시 한다.
    clean_drops = {}
    for name, count in drops.items():
        try:
            clean_drops[str(name)] = int(count)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"잘못된 수량: {name}={count}"}), 400

    ticket = _pop_pending_swap(gs, ticket_id)
    if ticket is None:
        return jsonify({"ok": False, "error": "이미 처리됐거나 존재하지 않는 교체 티켓입니다.",
                        "reason": "no_pending_swap"}), 400

    new_item = ticket["item"]
    target_slot = get_slot(new_item)
    mismatched = [n for n in clean_drops if get_slot(n) != target_slot]
    if mismatched:
        _restore_pending_swap(gs, ticket)
        return jsonify({"ok": False,
                        "error": f"{', '.join(mismatched)}은(는) {new_item}과(와) 종류가 달라 "
                                 f"교체할 수 없습니다.",
                        "reason": "slot_mismatch"}), 400

    price = ticket.get("price", 0)
    if ticket.get("source") == "shop" and price:
        gold = gs.get("gold", 0)
        if gold < price:
            # 티켓은 아직 유효하니 되돌려 놓는다 — 골드가 부족해졌다고
            # 대기 중이던 구매 자체를 잃을 이유는 없음.
            _restore_pending_swap(gs, ticket)
            return jsonify({"ok": False, "error": f"골드가 부족합니다. (보유: {gold}G)"}), 400
        gs["gold"] = gold - price

    inv = gs["inventory"]
    discard_res = inv.discard_multi(clean_drops)
    if not discard_res["ok"]:
        # 버리기 자체가 실패(보유량 부족 등)했으면 결제/티켓을 원상복구.
        if ticket.get("source") == "shop" and price:
            gs["gold"] = gs.get("gold", 0) + price
        _restore_pending_swap(gs, ticket)
        return jsonify({"ok": False, "error": discard_res.get("message", "교체 실패")}), 400

    inv.add(new_item)
    gs["items"] = inv.to_flat_list()

    dropped_desc = ", ".join(f"{name}×{count}" for name, count in clean_drops.items())
    resp = {
        "ok":      True,
        "dropped": clean_drops,
        "added":   new_item,
        "message": f"{dropped_desc}을(를) 버리고 {new_item}을(를) 획득!",
        "player":  _player_dict(gs["player"], inv),
    }
    if ticket.get("source") == "shop":
        resp["gold"] = gs.get("gold", 0)
    return jsonify(resp)


@inventory_bp.route("/api/inventory/swap/cancel", methods=["POST"])
def inventory_swap_cancel():
    """
    대기 중인 교체 티켓을 취소(그 아이템은 포기 — 더 이상 얻지 않는다).
    요청: { "ticket_id": "..." }

    ★ 예전엔 프런트가 모달만 닫고 서버엔 아무것도 알리지 않아서, 취소한
      티켓이 gs["pending_swaps"]에 영구히 남아있었다.
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data = request.get_json() or {}
    ticket_id = data.get("ticket_id", "")
    _pop_pending_swap(gs, ticket_id)   # 없으면(이미 처리/소멸) 조용히 무시 — 취소는 항상 성공
    return jsonify({"ok": True})