"""
app/rest.py — 휴식 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/rest  — 휴식 (heal | train)
"""
from __future__ import annotations

from random import random

from flask import Blueprint, jsonify, request

from game.Lv import LV_

from .Shared import _get_session, _player_dict

rest_bp = Blueprint("rest", __name__)


@rest_bp.route("/api/rest", methods=["POST"])
def rest():
    """
    요청: { "choice": "heal" | "train" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data   = request.get_json() or {}
    choice = data.get("choice", "")
    player = gs["player"]

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

    elif choice == "train":
        ratio    = 0.60 + random() * 0.20
        exp_gain = int(player.maxexp * ratio)
        LV_(player).Get_exp(player, reward_exp=exp_gain)
        gs["hook"].check_level_up()
        return jsonify({
            "ok":     True,
            "message": f"수련으로 {exp_gain} 경험치 획득!",
            "player":  _player_dict(player, gs["inventory"]),
        })

    return jsonify({"ok": False, "error": "choice는 heal 또는 train이어야 합니다."})