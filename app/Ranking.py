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
    _all_active_user_scores,
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
            # ★ 전체 유저 점수 계산을 이 요청 안에서 한 번만 수행 — 예전엔
            #   get_score_ranking()과 get_user_rank_position()이 각자 따로
            #   전체 유저를 순회하며 매번 Battle을 다시 조회해서, 요청 1건이
            #   사실상 이 계산을 두 번 반복했다.
            all_scores = _all_active_user_scores(db)
            rankings = get_score_ranking(db, limit=limit, _all_scores=all_scores)
            my_rank  = None
            db_user_id = _get_db_user_id()
            if db_user_id:
                my_rank = get_user_rank_position(db, db_user_id, _all_scores=all_scores)

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