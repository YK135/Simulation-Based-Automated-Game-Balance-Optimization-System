"""
app/Master.py — 마스터 모드(로컬 전용 디버그) Blueprint
─────────────────────────────────────────────
플레이테스트/밸런스 확인용 단축 기능. app/__init__.py가
MASTER_MODE 설정일 때만 이 블루프린트를 등록한다 — RENDER 환경변수가
있으면(배포 환경) 어떤 설정을 하더라도 등록되지 않는다.

엔드포인트:
  GET  /api/master/status         — 활성화 여부 + 선택 가능한 몬스터 목록
  POST /api/master/level_up       — { "levels": 3 } 강제 레벨업 N회 (기본 1)
  POST /api/master/full_heal      — HP/MP 100% 회복
  POST /api/master/battle/boss    — { "boss": "mid" | "final" } 보스 즉시 전투
  POST /api/master/battle/monster — { "monster_type": "고블린", "grade": "상" }
                                     지정 몬스터 즉시 전투
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from game.Lv import LV_
from game.Enemy_Class import Make_MidBoss, Make_FinalBoss

from .Shared import _get_session, _player_dict
from .Battle import _start_battle

master_bp = Blueprint("master", __name__)

# app/Map.py의 CHAPTER_TIER_POOL에 등장하는 전체 몬스터 종류
_MONSTER_TYPES = [
    "고블린", "박쥐", "슬라임", "화염 슬라임", "빙결 슬라임",
    "번개 슬라임", "골렘", "유령", "암살자", "사제",
]

# app/Map.py의 _GRADE_TO_KEY와 동일한 매핑
_GRADE_TO_KEY = {"하": "easy", "중": "normal", "상": "hard"}

# 한 번 호출로 올릴 수 있는 레벨 수 상한 (실수로 큰 값을 보내는 것 방지)
_MAX_LEVELS_PER_CALL = 50


@master_bp.route("/api/master/status", methods=["GET"])
def master_status():
    return jsonify({"ok": True, "enabled": True, "monsters": _MONSTER_TYPES})


@master_bp.route("/api/master/level_up", methods=["POST"])
def master_level_up():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 사용할 수 없습니다."}), 400

    data   = request.get_json() or {}
    levels = data.get("levels", 1)
    try:
        levels = int(levels)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "levels는 숫자여야 합니다."}), 400
    if not (1 <= levels <= _MAX_LEVELS_PER_CALL):
        return jsonify({"ok": False, "error": f"levels는 1~{_MAX_LEVELS_PER_CALL} 사이여야 합니다."}), 400

    player = gs["player"]
    for _ in range(levels):
        LV_.Lv_up(player)
    gs["hook"].check_level_up()
    return jsonify({"ok": True, "player": _player_dict(player, gs["inventory"])})


@master_bp.route("/api/master/full_heal", methods=["POST"])
def master_full_heal():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 사용할 수 없습니다."}), 400

    player = gs["player"]
    player.hp = player.maxhp
    player.mp = player.maxmp
    return jsonify({"ok": True, "player": _player_dict(player, gs["inventory"])})


@master_bp.route("/api/master/battle/boss", methods=["POST"])
def master_battle_boss():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 사용할 수 없습니다."}), 400

    data  = request.get_json() or {}
    which = data.get("boss")
    if which not in ("mid", "final"):
        return jsonify({"ok": False, "error": "boss는 'mid' 또는 'final'이어야 합니다."}), 400

    player = gs["player"]
    boss = Make_MidBoss(player.lv) if which == "mid" else Make_FinalBoss(player.lv)

    gs["battle_node_type"] = "boss"
    gs["pending_node_id"]  = None   # 노드맵과 무관한 즉석 전투 — 노드 진행에 영향 없음

    state = _start_battle(gs, boss, is_boss=True)
    return jsonify({
        "ok": True,
        "enemy": {"name": boss.name, "hp": boss.hp},
        "battle_state": state,
    })


@master_bp.route("/api/master/battle/monster", methods=["POST"])
def master_battle_monster():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 사용할 수 없습니다."}), 400

    data         = request.get_json() or {}
    monster_type = data.get("monster_type")
    grade        = data.get("grade", "중")
    if monster_type not in _MONSTER_TYPES:
        return jsonify({"ok": False, "error": "알 수 없는 몬스터 종류입니다."}), 400
    if grade not in _GRADE_TO_KEY:
        return jsonify({"ok": False, "error": "grade는 하/중/상 중 하나여야 합니다."}), 400

    hook  = gs["hook"]
    snap  = hook.get_enemy(monster_type, difficulty=_GRADE_TO_KEY[grade])
    enemy = hook.make_battle_unit(snap)

    gs["battle_node_type"] = "battle"
    gs["pending_node_id"]  = None

    state = _start_battle(gs, enemy, is_boss=False)
    return jsonify({
        "ok": True,
        "enemy": {"name": enemy.name, "hp": enemy.hp},
        "battle_state": state,
    })
