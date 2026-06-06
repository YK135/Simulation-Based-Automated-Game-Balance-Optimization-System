"""
app/game.py — 게임 시작 / 상태 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/new_game      — 새 게임 시작
  POST /api/newgame       — 별칭
  GET  /api/status        — 현재 플레이어 상태
  GET  /api/skills        — 스킬 목록
  GET  /api/items         — 아이템 목록
  POST /api/allocate_stat — 스탯 포인트 배분
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request, session

from game.Player_Class import create_player_by_job
from game.Inventory    import Inventory
from game.Lv           import Allocate_Stat_Points
from ai.battle  import SKILL_META
from core.Balance_Hook import BalanceHook

from .Shared import GAME_SESSIONS, _get_session, _player_dict

game_bp = Blueprint("game", __name__)


@game_bp.route("/api/new_game", methods=["POST"])
@game_bp.route("/api/newgame",  methods=["POST"])
def new_game():
    """
    요청: { "name": "용사", "job": "전사" }
    응답: { "ok": true, "player": {...} }
    """
    from DB import get_session as db_session
    from DB.Models import User

    data = request.get_json() or {}
    name = data.get("name", "용사").strip() or "용사"
    job  = data.get("job",  "전사")

    if job not in ("전사", "마법사", "탱커", "도적"):
        return jsonify({"ok": False, "error": "잘못된 직업입니다."}), 400

    # Flask session user_id
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    uid = session["user_id"]

    # DB User 생성 — auth_type='guest', nickname 사용 (name/job 필드 없음)
    db_user_id = None
    try:
        with db_session() as db:
            user = User(auth_type="guest", nickname=name, email=None, is_active=True)
            db.add(user)
            db.flush()
            db_user_id = user.id
            print(f"[DB] User created: id={db_user_id}, nickname={name}, job={job}")
    except Exception as e:
        print(f"[DB] User creation failed: {e}")

    player = create_player_by_job(name, job)

    # 레벨 1 스킬 초기화
    from game.Skill import Ply_Skill
    skill_sys = Ply_Skill(job)
    skill_sys.update_skills(1)
    player.skill = skill_sys
    # learned_skills를 player에도 직접 반영 (BattleSession/Snapshot 호환)
    if not hasattr(player, "learned_skills"):
        player.learned_skills = []
    player.learned_skills = list(skill_sys.learned_skills)

    inv   = Inventory.new()   # 시작 포션 3개 (상점 구매 여지 확보)
    for item in ["HP_S_potion", "HP_S_potion", "MP_S_potion"]:
        inv.add(item)
    items = inv.to_flat_list()

    hook = BalanceHook(player, items, show_graph=False, verbose=False)

    GAME_SESSIONS[uid] = {
        "player":           player,
        "inventory":        inv,
        "items":            items,        # 호환용 평탄 list
        "battle":           None,
        "turn":             0,
        "mid_boss_cleared": False,
        "last_event":       None,
        "hook":             hook,
        "db_user_id":       db_user_id,
        "nickname":         name,
        # 노드맵 관련
        "map":              None,   # FloorMap.to_dict() 저장
        "chapter":          None,
        "map_turn":         0,
        "pending_node_id":  None,
        "run_id":           None,
        "gold":             100,    # 시작 골드
    }

    return jsonify({
        "ok":         True,
        "player":     _player_dict(player, inv),
        "db_user_id": db_user_id,
        "gold":       100,
        "message":    f"안녕하세요, {name}님! ({job}) 모험을 시작합니다.",
    })


@game_bp.route("/api/status", methods=["GET"])
def status():
    """현재 플레이어 상태 + 전투 중 여부."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    player    = gs["player"]
    in_battle = gs["battle"] is not None
    resp = {
        "ok":        True,
        "player":    _player_dict(player, gs["inventory"]),
        "turn":      gs["turn"],
        "in_battle": in_battle,
        "gold":      gs.get("gold", 0),
        "user": {
            "db_user_id": gs.get("db_user_id"),
            "nickname":   gs.get("nickname"),
        },
    }
    # 전투 중이면 battle state도 함께 포함 (프론트 복구용)
    if in_battle:
        resp["battle"] = gs["battle"]._state()
    return jsonify(resp)


@game_bp.route("/api/skills", methods=["GET"])
def skills():
    """플레이어 학습 스킬 목록."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    player = gs["player"]
    result = []
    for sk in (player.skill.learned_skills if player.skill else []):
        meta = SKILL_META.get(sk, {})
        result.append({
            "name":   sk,
            "mp":     meta.get("mp", 0),
            "type":   meta.get("type", ""),
            "usable": player.mp >= meta.get("mp", 0),
        })
    return jsonify({"ok": True, "skills": result})


@game_bp.route("/api/items", methods=["GET"])
def items():
    """보유 아이템 목록."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    from collections import Counter
    cnt = Counter(gs["inventory"].to_flat_list())
    return jsonify({"ok": True, "items": [{"name": k, "count": v} for k, v in cnt.items()]})


@game_bp.route("/api/allocate_stat", methods=["POST"])
@game_bp.route("/api/levelup/allocate", methods=["POST"])
def allocate_stat():
    """
    스탯 포인트 배분.
    요청: { "allocation": { "stg": 2, "spd": 1 } }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data       = request.get_json() or {}
    allocation = data.get("allocation", {})

    if not isinstance(allocation, dict):
        return jsonify({"ok": False, "error": "allocation은 dict여야 합니다."}), 400

    clean_alloc = {}
    for stat, pts in allocation.items():
        try:
            clean_alloc[stat] = int(pts)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": f"잘못된 포인트 값: {stat}={pts}"}), 400

    player = gs["player"]
    result = Allocate_Stat_Points(player, clean_alloc)

    if not result["ok"]:
        return jsonify({"ok": False, "error": result["msg"],
                        "remaining": result["remaining"]}), 400

    return jsonify({
        "ok":        True,
        "player":    _player_dict(player, gs["inventory"]),
        "remaining": result["remaining"],
        "message":   result["msg"],
    })