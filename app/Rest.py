"""
app/rest.py — 휴식 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/rest  — 휴식 (heal | train)
"""
from __future__ import annotations

from random import random

from flask import Blueprint, jsonify

from game.Lv import LV_

from .Shared import _get_session, _player_dict, _get_json_body

rest_bp = Blueprint("rest", __name__)


def _current_pending_node_type(gs: dict) -> str | None:
    """gs["pending_node_id"]가 가리키는 노드의 node_type. 없으면 None.

    ★ /api/rest는 예전엔 이걸 전혀 확인하지 않아서, 휴식 노드에 있지 않은
      상태에서도(맵 시작 직후, 전투/상점 노드 등) 브라우저 콘솔이나 별도
      HTTP 요청으로 {"choice":"train"}을 계속 보내면 경험치를 무한정 얻을
      수 있었다."""
    node_id = gs.get("pending_node_id")
    map_data = gs.get("map")
    if not node_id or not map_data:
        return None
    node = (map_data.get("nodes") or {}).get(node_id)
    return node.get("node_type") if node else None


@rest_bp.route("/api/rest", methods=["POST"])
def rest():
    """
    요청: { "choice": "heal" | "train" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if _current_pending_node_type(gs) != "rest":
        return jsonify({"ok": False, "error": "휴식 노드에서만 사용할 수 있습니다.",
                        "reason": "not_rest_node"}), 400

    # ★ 노드 하나당 1회만 — pending_node_id는 /api/map/node/complete가 호출될
    #   때까지 유지되므로, 이 가드가 없으면 완료 호출 전까지 /api/rest를
    #   반복 호출해서(특히 "train") 경험치를 계속 얻을 수 있었다(실측 취약점).
    pending_id = gs.get("pending_node_id")
    if gs.get("rest_used_node_id") == pending_id:
        return jsonify({"ok": False, "error": "이미 이 휴식을 사용했습니다.",
                        "reason": "rest_already_used"}), 400

    data   = _get_json_body()
    choice = data.get("choice", "")
    player = gs["player"]

    if choice not in ("heal", "train"):
        return jsonify({"ok": False, "error": "choice는 heal 또는 train이어야 합니다."})

    # ★ heal/train 둘 다(체력이 이미 가득 차 회복량이 0인 경우 포함) 이 노드를
    #   "사용함"으로 표시 — 위 가드가 이 요청부터 적용되도록.
    gs["rest_used_node_id"] = pending_id

    if choice == "heal":
        if player.hp >= player.maxhp:
            return jsonify({"ok": True,
                            "message": "이미 체력이 가득 찼습니다.",
                            "player":  _player_dict(player, gs["inventory"])})
        heal      = min(int(player.maxhp / 3), int(player.maxhp - player.hp))
        player.hp = min(player.maxhp, player.hp + heal)
        return jsonify({
            "ok":     True,
            "message": f"체력 {heal} 회복! ({int(player.hp)}/{int(player.maxhp)})",
            "player":  _player_dict(player, gs["inventory"]),
        })

    ratio    = 0.60 + random() * 0.20
    exp_gain = int(player.maxexp * ratio)
    LV_(player).Get_exp(player, reward_exp=exp_gain)
    gs["hook"].check_level_up()
    return jsonify({
        "ok":     True,
        "message": f"수련으로 {exp_gain} 경험치 획득!",
        "player":  _player_dict(player, gs["inventory"]),
    })