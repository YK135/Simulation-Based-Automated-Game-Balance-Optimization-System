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
  POST /api/master/battle/elite   — { "chapter": 1|2 } (생략 시 현재 챕터) 엘리트
                                     풀에서 랜덤 리더(+동료) 즉시 전투
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from game.Lv import LV_
from game.Enemy_Class import Make_MidBoss, Make_FinalBoss

from .Shared import _get_session, _player_dict, _get_json_body
from .Battle import _start_battle, _start_battle_multi

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

    data   = _get_json_body()
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
    # ★ Lv_up()은 "경험치가 이미 찼다"는 전제로 exp -= maxexp를 하므로, 경험치 없이
    #   강제로 올리는 이 경로에서는 exp가 음수로 남는다(레벨 14회면 −2400 — 패널의
    #   EXP 바가 음수로 표시되고, 이후 실제 전투 경험치가 그 빚을 먼저 갚아야 한다).
    #   실전 경로(Get_exp)는 찬 만큼만 빼므로 음수가 되지 않는다 — 여기서만 0으로 맞춘다.
    player.exp = max(0, getattr(player, "exp", 0))
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

    data  = _get_json_body()
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

    data         = _get_json_body()
    monster_type = data.get("monster_type")
    grade        = data.get("grade", "중")
    if monster_type not in _MONSTER_TYPES:
        return jsonify({"ok": False, "error": "알 수 없는 몬스터 종류입니다."}), 400
    if grade not in _GRADE_TO_KEY:
        return jsonify({"ok": False, "error": "grade는 하/중/상 중 하나여야 합니다."}), 400

    hook  = gs["hook"]
    snap  = hook.get_enemy(monster_type, difficulty=_GRADE_TO_KEY[grade], chapter=gs.get("chapter", 1))
    enemy = hook.make_battle_unit(snap)

    gs["battle_node_type"] = "battle"
    gs["pending_node_id"]  = None

    state = _start_battle(gs, enemy, is_boss=False)
    return jsonify({
        "ok": True,
        "enemy": {"name": enemy.name, "hp": enemy.hp},
        "battle_state": state,
    })


@master_bp.route("/api/master/battle/elite", methods=["POST"])
def master_battle_elite():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중에는 사용할 수 없습니다."}), 400

    from .Map import _make_elite_encounter

    data    = _get_json_body()
    chapter = data.get("chapter")
    if chapter is None:
        # 맵 생성 전(new_game 직후)엔 gs["chapter"]가 None이라 or로 폴백 —
        # 생략 시 "현재 챕터"를 그대로 쓰는 기존 동작을 유지한다.
        chapter = gs.get("chapter") or 1
    try:
        chapter = int(chapter)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "chapter는 숫자여야 합니다."}), 400
    if chapter not in (1, 2):
        return jsonify({"ok": False, "error": "chapter는 1 또는 2여야 합니다."}), 400

    # ★ 실제 진행도(gs["chapter"])는 건드리지 않는다 — 이건 어떤 챕터의 엘리트
    #   풀에서 뽑을지만 결정하는 테스트용 오버라이드.
    hook  = gs["hook"]
    layer = gs.get("battle_map_layer") or 1
    # ★ 다대일 보정은 _make_elite_encounter()가 안에서 적용해 돌려준다 — 여기서 또
    #   곱하면 두 번 걸린다. 예전엔 이 세 호출부가 각자 곱했고 실제로 갈라져 있었다
    #   (montecarlo.py만 저레벨 완화 배율을 빼먹어 저레벨 엘리트가 실전과 달랐다).
    enemies, _grades = _make_elite_encounter(hook, chapter=chapter, layer=layer,
                                             player_lv=gs["player"].lv)

    gs["battle_node_type"] = "elite"
    gs["pending_node_id"]  = None

    if len(enemies) == 1:
        state = _start_battle(gs, enemies[0], is_boss=False)
    else:
        state = _start_battle_multi(gs, enemies, is_boss=False)

    return jsonify({
        "ok": True,
        "enemy": {"name": enemies[0].name, "hp": enemies[0].hp},
        "battle_state": state,
    })
