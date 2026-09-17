"""
app/Relic.py — 유물 선택 API (Combat Content Brief 7장 · 11-1 2차 7번)
─────────────────────────────────────────────
  POST /api/relic/choose  { "ticket_id": "...", "relic_id": "<id>" | "gold" }

엘리트·보스 승리 시 app/Battle.py의 _finish_battle()이 티켓(pending_relic_offer)을 등록하고
result["relic_offer"]로 선택지를 내려준다. 클라이언트가 보내는 것은 ticket_id와 고른 id뿐 —
어떤 유물이 제시됐는지는 서버의 티켓이 알고 있고, 티켓에 없는 id는 거절한다
(CLAUDE.md "클라이언트 입력을 믿지 않는다"). 골드 환전 금액도 서버 상수다.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from .Shared import (
    _get_session, _get_json_body, _player_dict, _pop_relic_offer, _restore_relic_offer,
    _grant_relic,
)
from game.Relics import RELIC_GOLD_CONVERT, relic_public

relic_bp = Blueprint("relic", __name__)


@relic_bp.route("/api/relic/choose", methods=["POST"])
def relic_choose():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data = _get_json_body()
    ticket_id = str(data.get("ticket_id") or "")
    choice = str(data.get("relic_id") or "")

    ticket = _pop_relic_offer(gs, ticket_id)
    if ticket is None:
        return jsonify({"ok": False, "error": "유효하지 않은 유물 선택 티켓입니다."}), 400

    if choice == "gold":
        gs["gold"] = gs.get("gold", 0) + RELIC_GOLD_CONVERT
        message = f"유물을 골드로 환전했다. (+{RELIC_GOLD_CONVERT}G)"
        chosen = None
    elif choice in ticket.get("choices", []):
        if not _grant_relic(gs, choice):
            _restore_relic_offer(gs, ticket)
            return jsonify({"ok": False, "error": "이미 가진 유물입니다."}), 400
        chosen = relic_public(choice)
        message = f"유물 획득: {chosen['name']}"
    else:
        _restore_relic_offer(gs, ticket)      # 잘못된 id — 티켓은 그대로 두어 다시 고를 수 있게
        return jsonify({"ok": False, "error": "제시된 유물이 아닙니다."}), 400

    return jsonify({
        "ok": True,
        "message": message,
        "chosen": chosen,
        "gold": gs.get("gold", 0),
        "player": _player_dict(gs["player"], gs["inventory"]),
    })
