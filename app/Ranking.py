"""
app/ranking.py — 랭킹 Blueprint
─────────────────────────────────────────────
엔드포인트:
  GET /api/ranking           — 점수 기반 랭킹 TOP N
  GET /api/ranking/pioneers  — 선구자 랭킹 TOP N
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from DB import get_session as db_session
from DB.Queries import (
    get_score_ranking,
    get_pioneer_ranking,
    get_user_rank_position,
)

from .Shared import _get_db_user_id

ranking_bp = Blueprint("ranking", __name__)


@ranking_bp.route("/api/ranking", methods=["GET"])
def ranking():
    """점수 기반 랭킹 TOP 20 (쿼리 파라미터 ?limit=N 으로 조절)."""
    try:
        limit = int(request.args.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20
    limit = max(1, min(100, limit))

    try:
        with db_session() as db:
            rankings = get_score_ranking(db, limit=limit)
            my_rank  = None
            db_user_id = _get_db_user_id()
            if db_user_id:
                my_rank = get_user_rank_position(db, db_user_id)

        return jsonify({
            "ok":       True,
            "rankings": rankings,
            "my_rank":  my_rank,
            "limit":    limit,
        })
    except Exception as e:
        print(f"[DB] Ranking query failed: {e}")
        return jsonify({"ok": False, "error": "랭킹 조회 실패"}), 500


@ranking_bp.route("/api/ranking/pioneers", methods=["GET"])
def ranking_pioneers():
    """선구자 랭킹 TOP 10."""
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(50, limit))

    try:
        with db_session() as db:
            pioneers = get_pioneer_ranking(db, limit=limit)

        return jsonify({
            "ok":       True,
            "pioneers": pioneers,
            "limit":    limit,
        })
    except Exception as e:
        print(f"[DB] Pioneer ranking failed: {e}")
        return jsonify({"ok": False, "error": "선구자 랭킹 조회 실패"}), 500