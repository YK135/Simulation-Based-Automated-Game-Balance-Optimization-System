"""
app/Map.py — 노드맵 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/map/generate      — 챕터 맵 생성 (챕터 시작 시 1회)
  GET  /api/map/state         — 현재 맵 상태 (선택 가능 노드 목록)
  POST /api/map/choose        — 노드 선택 → 이벤트 결정
  POST /api/map/node/complete — 노드 처리 완료 후 다음 노드 활성화
  POST /api/map/next_chapter  — 챕터 1 클리어 후 챕터 2 시작

노드 타입별 처리 (choose 응답):
  battle  → BattleSession 생성 (기존 explore.py 로직 재사용)
  elite   → BattleSession 생성 (엘리트 몬스터, 나중에 패턴 추가)
  event   → 랜덤 이벤트 결과 바로 반환
  rest    → options 반환 (heal / train 선택)
  shop    → 상점 목록 반환
  boss    → 보스 BattleSession 생성
"""
from __future__ import annotations

import json
from random import choices as rand_choices, random, randint, choice

from flask import Blueprint, jsonify, request

from game.Map      import FloorMap, TOTAL_LAYERS, BOSS_LAYER
from game.Enemy_Class import (
    Make_MidBoss, Make_FinalBoss,
)

from app.Shared  import _get_session, _player_dict
from app.Battle  import _start_battle, _start_battle_multi

map_bp = Blueprint("map", __name__)


# ─────────────────────────────────────────────
# 이벤트 풀 (확장 가능)
# ─────────────────────────────────────────────
_EVENTS = [
    {
        "id":      "item_found",
        "label":   "아이템 발견",
        "handler": "_event_item_found",
    },
    # 추가 이벤트는 여기에 dict로 추가
]

_ITEM_DROP_POOL = [
    ("HP_S_potion", 4), ("MP_S_potion", 4),
    ("HP_M_potion", 2), ("MP_M_potion", 2),
    ("HP_L_potion", 1), ("MP_L_potion", 1),
]

# ─────────────────────────────────────────────
# 전투 노드 생성 규칙
# ─────────────────────────────────────────────
# 일반 전투: 1~3마리, 3마리일 때 hard 금지
# 엘리트:    1~2마리, hard 고정
# 스탯 보정:
#   일반 1마리: 100%  / 2마리: 90%  / 3마리: 80%
#   엘리트 1마리: 100% / 2마리: 90%

NORMAL_GRADE_POOL  = {"하": 0.35, "중": 0.45, "상": 0.20}
NORMAL_GRADE_3     = {"하": 0.45, "중": 0.55}          # 3마리: hard 금지
ELITE_GRADE        = {"상": 1.0}                        # 엘리트: hard 고정
STAT_SCALE         = {1: 1.00, 2: 0.90, 3: 0.80}
ELITE_STAT_SCALE   = {1: 1.00, 2: 0.90}


def _pick_grade(pool: dict) -> str:
    """가중치 기반 난이도 선택."""
    from random import choices as _rc
    keys = list(pool.keys())
    wts  = list(pool.values())
    return _rc(keys, weights=wts, k=1)[0]


def _apply_stat_scale(enemies: list, scale: float) -> None:
    """다대일 스탯 보정 적용 (인플레이스)."""
    if scale >= 1.0:
        return
    for e in enemies:
        for attr in ("hp", "maxhp"):
            if hasattr(e, attr):
                setattr(e, attr, int(getattr(e, attr) * scale))
        for attr in ("stg", "sp", "arm", "sparm"):
            if hasattr(e, attr):
                setattr(e, attr, round(getattr(e, attr) * scale, 1))


# 난이도 한글 → 내부 키 매핑 (BalanceHook 캐시 키)
_GRADE_TO_KEY = {"하": "easy", "중": "normal", "상": "hard"}


# ─────────────────────────────────────────────
# 챕터별 몬스터 출현 풀
# ─────────────────────────────────────────────
# 몬스터 출현은 플레이어 레벨(min_lv)이 아니라 "챕터" 기준으로 고정.
#   챕터 1 (중간보스 전): 기본 몬스터 + 원소 슬라임 3종
#   챕터 2 (최종보스 전): 챕터 1 전체 + 사제/암살자/골렘
# elite 노드도 같은 풀에서 hard/상만 뽑는다 (grade_pool로 제어).
CHAPTER_ENEMY_POOL = {
    1: ["고블린", "박쥐", "슬라임", "화염 슬라임", "빙결 슬라임", "번개 슬라임"],
    2: ["고블린", "박쥐", "슬라임", "화염 슬라임", "빙결 슬라임", "번개 슬라임",
        "사제", "암살자", "골렘"],
}


def _make_enemies(hook, n: int, grade_pool: dict, chapter: int = 1) -> list:
    """n마리 적 생성 (챕터 풀에서 선택, 각자 독립 grade, BalanceHook 캐시 조회).

    ※ 구 방식(플레이어 레벨 min_lv 기반 hook.pick_random_enemy_type)은 폐기 —
      챕터 기준 고정 풀(CHAPTER_ENEMY_POOL)에서만 출현."""
    pool = CHAPTER_ENEMY_POOL.get(chapter, CHAPTER_ENEMY_POOL[2])
    enemies = []
    grades  = []
    for _ in range(n):
        enemy_type = choice(pool)
        grade      = _pick_grade(grade_pool)
        diff_key   = _GRADE_TO_KEY.get(grade, "normal")
        # difficulty 파라미터로 원하는 난이도 직접 지정
        snap       = hook.get_enemy(enemy_type, difficulty=diff_key)
        unit       = hook.make_battle_unit(snap)
        enemies.append(unit)
        grades.append(grade)
    return enemies, grades


def _event_item_found(gs: dict) -> dict:
    """이벤트: 아이템 발견."""
    player = gs["player"]
    names   = [x[0] for x in _ITEM_DROP_POOL]
    weights = [x[1] for x in _ITEM_DROP_POOL]
    gained  = rand_choices(names, weights=weights, k=1)[0]

    inv    = gs["inventory"]
    result = inv.add(gained)
    gs["items"] = inv.to_flat_list()

    base = {
        "event_id": "item_found",
        "player":   _player_dict(player, inv),
    }
    if result["ok"]:
        return {**base, "message": f"[아이템 발견] {gained}을(를) 발견했다!",
                "item": gained}
    elif result.get("reason") == "special_full":
        return {**base, "event": "item_full",
                "incoming":   gained,
                "candidates": result["candidates"],
                "message":    result["message"]}
    else:
        return {**base, "message": result["message"]}


# ─────────────────────────────────────────────
# DB 로그 헬퍼
# ─────────────────────────────────────────────

def _log_node_choice(gs: dict, node, battle_result: str = None,
                     battle_turns: int = None, extra: dict = None) -> None:
    """노드 선택을 DB에 기록."""
    try:
        from DB import get_session as db_session
        from DB.Models import NodeChoice
        import json as _json

        run_id = gs.get("run_id")
        if not run_id:
            return

        player = gs["player"]
        with db_session() as db:
            nc = NodeChoice(
                run_id         = run_id,
                turn           = gs.get("map_turn", 1),
                layer          = node.layer,
                node_id        = node.node_id,
                node_type      = node.node_type,
                player_hp_ratio= round(player.hp / player.maxhp, 3) if player.maxhp > 0 else 0,
                player_lv      = player.lv,
                battle_result  = battle_result,
                battle_turns   = battle_turns,
                extra_data     = _json.dumps(extra or {}, ensure_ascii=False),
            )
            db.add(nc)
    except Exception as e:
        print(f"[DB] NodeChoice log failed: {e}")


def _create_run(gs: dict, chapter: int) -> None:
    """런 시작 시 DB Run 레코드 생성."""
    try:
        from DB import get_session as db_session
        from DB.Models import Run

        db_user_id = gs.get("db_user_id")
        if not db_user_id:
            return

        player = gs["player"]
        with db_session() as db:
            run = Run(
                user_id        = db_user_id,
                chapter        = chapter,
                player_job     = player.job,
                player_lv_start= player.lv,
            )
            db.add(run)
            db.flush()
            gs["run_id"] = run.id
            print(f"[DB] Run created: id={run.id}, chapter={chapter}")
    except Exception as e:
        print(f"[DB] Run creation failed: {e}")


def _finish_run(gs: dict, result: str) -> None:
    """런 종료 시 DB Run 업데이트."""
    try:
        from DB import get_session as db_session
        from DB.Models import Run

        run_id = gs.get("run_id")
        if not run_id:
            return

        player = gs["player"]
        with db_session() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run:
                run.result        = result
                run.player_lv_end = player.lv
                run.total_nodes   = gs.get("map_turn", 0)
                run.boss_cleared  = (result == "clear")
    except Exception as e:
        print(f"[DB] Run finish failed: {e}")


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@map_bp.route("/api/map/generate", methods=["POST"])
def map_generate():
    """
    챕터 맵 생성.
    요청: { "chapter": 1 }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data    = request.get_json() or {}
    chapter = int(data.get("chapter", 1))

    if chapter not in (1, 2):
        return jsonify({"ok": False, "error": f"잘못된 챕터: {chapter}"}), 400

    fmap = FloorMap.generate(chapter)
    gs["map"]      = fmap.to_dict()    # 직렬화해서 저장
    gs["map_turn"] = 0
    gs["chapter"]  = chapter

    _create_run(gs, chapter)

    return jsonify({
        "ok":      True,
        "chapter": chapter,
        "map":     fmap.get_state(),
        "message": f"챕터 {chapter} 시작!",
    })


@map_bp.route("/api/map/state", methods=["GET"])
def map_state():
    """현재 맵 상태 반환."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if not gs.get("map"):
        return jsonify({"ok": False, "error": "맵이 없습니다. /api/map/generate 먼저 호출하세요."}), 400

    fmap = FloorMap.from_dict(gs["map"])
    return jsonify({"ok": True, "map": fmap.get_state(),
                    "player": _player_dict(gs["player"], gs["inventory"])})


@map_bp.route("/api/map/choose", methods=["POST"])
def map_choose():
    """
    노드 선택 → 타입별 처리 후 결과 반환.
    요청: { "node_id": "3_1" }

    응답 event 필드:
      battle / elite / boss → battle_state 포함
      event                 → message + item 등
      rest                  → options 포함
      shop                  → shop_items 포함
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if gs.get("battle"):
        return jsonify({"ok": False, "error": "전투 중입니다. 먼저 전투를 완료하세요."})

    data    = request.get_json() or {}
    node_id = data.get("node_id", "").strip()
    if not node_id:
        return jsonify({"ok": False, "error": "node_id가 필요합니다."}), 400

    fmap = FloorMap.from_dict(gs["map"])
    ok, node, err = fmap.choose(node_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    gs["map_turn"] = gs.get("map_turn", 0) + 1
    gs["pending_node_id"] = node_id   # node/complete 호출 시 참조

    player  = gs["player"]
    node_type = node.node_type

    # ── 전투 / 엘리트 / 보스 ──────────────────
    if node_type in ("battle", "elite", "boss"):
        gs["battle_node_type"] = node_type
        gs["battle_map_layer"] = node.layer
        is_boss = (node_type == "boss")
        chapter = gs.get("chapter", 1)

        if is_boss:
            boss = _get_boss(chapter, player.lv)
            state = _start_battle(gs, boss, is_boss=True)
            _log_node_choice(gs, node)
            _save_map(gs, fmap)
            return jsonify({
                "ok": True, "event": node_type,
                "node_id": node_id,
                "enemy": {"name": boss.name, "hp": boss.hp},
                "battle_state": state,
            })

        hook = gs["hook"]

        if node_type == "elite":
            # ── 엘리트: 1~2마리, hard 고정, 스탯 보정 적용 ──
            n_enemies  = randint(1, 2)
            grade_pool = ELITE_GRADE
            scale      = ELITE_STAT_SCALE[n_enemies]
        else:
            # ── 일반: 1~3마리, 3마리일 때 hard 금지 ──
            rd = randint(1, 20)
            n_enemies  = 1 if rd <= 11 else (2 if rd <= 15 else 3)
            grade_pool = NORMAL_GRADE_3 if n_enemies == 3 else NORMAL_GRADE_POOL
            scale      = STAT_SCALE[n_enemies]

        enemies, grades = _make_enemies(hook, n_enemies, grade_pool, chapter)

        # 다대일 스탯 보정 (BattleSession 내 보정과 중복 방지 — 외부에서만 처리)
        if n_enemies > 1:
            _apply_stat_scale(enemies, scale)

        # 전투 시작
        if n_enemies == 1:
            state = _start_battle(gs, enemies[0])
        else:
            state = _start_battle_multi(gs, enemies)

        # 로그 기록
        _log_node_choice(gs, node, extra={
            "node_type":   node_type,
            "enemy_count": n_enemies,
            "grades":      grades,
            "stat_scale":  scale,
        })
        _save_map(gs, fmap)

        resp = {
            "ok":          True,
            "event":       node_type,
            "node_id":     node_id,
            "enemy_count": n_enemies,
            "grades":      grades,
            "stat_scale":  scale,
            "battle_state": state,
        }
        if n_enemies == 1:
            resp["enemy"] = {"name": enemies[0].name, "hp": enemies[0].hp}
        else:
            resp["enemies"] = [{"name": e.name, "hp": e.hp} for e in enemies]

        return jsonify(resp)

    # ── 이벤트 ────────────────────────────────
    elif node_type == "event":
        event_def = _pick_event()
        handler   = globals().get(event_def["handler"])
        result    = handler(gs) if handler else {"message": "알 수 없는 이벤트"}
        _log_node_choice(gs, node)
        # 이벤트는 즉시 완료 → 바로 visited 처리
        fmap.mark_visited(node_id)
        _save_map(gs, fmap)
        return jsonify({
            "ok": True, "event": "event",
            "node_id": node_id,
            "event_id": event_def["id"],
            "node_done": True,    # 프론트에 즉시 완료 신호
            **result,
        })

    # ── 휴식 ──────────────────────────────────
    elif node_type == "rest":
        _log_node_choice(gs, node)
        _save_map(gs, fmap)   # ★ choose()의 갈래 잠금(player_branch) 저장 — 새로고침 시 유지
        return jsonify({
            "ok": True, "event": "rest",
            "node_id": node_id,
            "message": "휴식 지점에 도착했다.",
            "options": [
                {"key": "heal",  "label": f"체력 회복 (maxHP의 1/3)"},
                {"key": "train", "label": "수련 (경험치 60~80%)"},
            ],
        })

    # ── 상점 ──────────────────────────────────
    elif node_type == "shop":
        _log_node_choice(gs, node)
        _save_map(gs, fmap)   # ★ choose()의 갈래 잠금(player_branch) 저장 — 새로고침 시 유지
        shop_items = _get_shop_items(player.lv)
        return jsonify({
            "ok": True, "event": "shop",
            "node_id":    node_id,
            "message":    "상점에 도착했다.",
            "shop_items": shop_items,
            "gold":       gs.get("gold", 0),
        })

    return jsonify({"ok": False, "error": f"알 수 없는 노드 타입: {node_type}"}), 400


@map_bp.route("/api/map/node/complete", methods=["POST"])
def map_node_complete():
    """
    노드 처리 완료 후 호출 (휴식 선택/상점 구매 완료 등).
    전투 완료는 battle_action에서 자동 처리.
    요청: { "node_id": "3_1" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data    = request.get_json() or {}
    node_id = data.get("node_id") or gs.get("pending_node_id", "")
    if not node_id:
        return jsonify({"ok": False, "error": "node_id가 필요합니다."}), 400

    fmap = FloorMap.from_dict(gs["map"])
    fmap.mark_visited(node_id)
    _save_map(gs, fmap)

    if fmap.completed:
        _finish_run(gs, "clear")
        chapter = gs.get("chapter", 1)
        if chapter >= 2:
            return jsonify({
                "ok": True, "map_done": True,
                "game_clear": True,
                "message": "🎉 모든 챕터를 클리어했습니다!",
                "map": fmap.get_state(),
            })
        return jsonify({
            "ok": True, "map_done": True,
            "next_chapter": chapter + 1,
            "message": f"챕터 {chapter} 클리어! 챕터 {chapter + 1}로 진행합니다.",
            "map": fmap.get_state(),
        })

    gs["pending_node_id"] = None
    return jsonify({
        "ok":    True,
        "map":   fmap.get_state(),
        "player": _player_dict(gs["player"], gs["inventory"]),
    })


@map_bp.route("/api/map/next_chapter", methods=["POST"])
def map_next_chapter():
    """챕터 1 클리어 후 챕터 2 맵 생성."""
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    next_ch = gs.get("chapter", 1) + 1
    if next_ch not in (1, 2):
        return jsonify({"ok": False, "error": "더 이상 챕터가 없습니다."}), 400

    fmap = FloorMap.generate(next_ch)
    gs["map"]      = fmap.to_dict()
    gs["map_turn"] = 0
    gs["chapter"]  = next_ch
    gs["pending_node_id"] = None

    _create_run(gs, next_ch)

    return jsonify({
        "ok":      True,
        "chapter": next_ch,
        "map":     fmap.get_state(),
        "message": f"챕터 {next_ch} 시작!",
    })


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _save_map(gs: dict, fmap: FloorMap) -> None:
    """FloorMap → gs["map"] 저장."""
    gs["map"] = fmap.to_dict()


def _pick_event() -> dict:
    """랜덤 이벤트 선택 (균등 확률)."""
    return random.choice(_EVENTS) if _EVENTS else {
        "id": "nothing", "label": "아무 일도 없음", "handler": None
    }


def _get_boss(chapter: int, player_lv: int):
    """챕터별 보스 생성."""
    if chapter == 1:
        return Make_MidBoss(player_lv, None)
    return Make_FinalBoss(player_lv)


def _get_shop_items(player_lv: int) -> list:
    """
    상점 아이템 목록 생성 (포션 + 특수 아이템).
    특수 아이템은 레벨 3 이상부터 노출.
    """
    items = [
        {"id": "HP_M_potion", "name": "HP 중형 포션", "type": "potion",
         "effect": "HP +60%", "price": 50},
        {"id": "HP_L_potion", "name": "HP 대형 포션", "type": "potion",
         "effect": "HP +100%", "price": 80},
        {"id": "MP_M_potion", "name": "MP 중형 포션", "type": "potion",
         "effect": "MP +60%", "price": 50},
        {"id": "MP_L_potion", "name": "MP 대형 포션", "type": "potion",
         "effect": "MP +100%", "price": 80},
    ]
    if player_lv >= 3:
        items += [
            {"id": "bomb",       "name": "폭탄",       "type": "special",
             "effect": "전체 데미지", "price": 120},
            {"id": "web_bomb",   "name": "거미줄 폭탄", "type": "special",
             "effect": "전체 데미지 + 속도 감소", "price": 150},
            {"id": "focus_drug", "name": "집중 물약",   "type": "special",
             "effect": "다음 스킬 추가 피해", "price": 100},
        ]
    return items


import random  # _pick_event에서 사용


# ─────────────────────────────────────────────
# 상점 구매 API
# ─────────────────────────────────────────────

@map_bp.route("/api/shop/buy", methods=["POST"])
def shop_buy():
    """
    상점 아이템 구매.
    요청: { "item_id": "HP_M_potion", "price": 50 }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data    = request.get_json() or {}
    item_id = data.get("item_id", "")
    price   = int(data.get("price", 0))
    gold    = gs.get("gold", 0)

    if gold < price:
        return jsonify({"ok": False, "error": f"골드가 부족합니다. (보유: {gold}G)"}), 400

    inv    = gs["inventory"]
    result = inv.add(item_id)
    if not result.get("ok"):
        reason = result.get("reason", "")
        if reason == "special_full":
            return jsonify({"ok": False, "error": "특수 아이템 칸이 가득 찼습니다.",
                           "reason": "special_full", "candidates": result.get("candidates", [])}), 400
        if reason == "potion_full":
            return jsonify({"ok": False,
                           "error": "포션 슬롯이 가득 찼습니다. 기존 포션을 사용한 뒤 구매하세요.",
                           "reason": "potion_full"}), 400
        return jsonify({"ok": False, "error": result.get("message", "인벤토리 가득 참")}), 400

    gs["gold"]  = gold - price
    gs["items"] = inv.to_flat_list()

    return jsonify({
        "ok":        True,
        "message":   f"{item_id} 구매! (-{price}G)",
        "gold":      gs["gold"],
        "player":    _player_dict(gs["player"], inv),
        "shop_items": _get_shop_items(gs["player"].lv),  # 상점 UI 재렌더용
    })
