"""
app/battle.py — 전투 Blueprint
─────────────────────────────────────────────
엔드포인트:
  GET  /api/battle/state   — 현재 전투 상태
  POST /api/battle/action  — 전투 행동

내부 헬퍼:
  _start_battle()          — 단일 전투 시작
  _start_battle_multi()    — 다대일 전투 시작
  _finish_battle()         — 전투 종료 후 처리 (exp, 보스 보상, inv 재반영)
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from game.Lv        import LV_
from game.Inventory import Inventory
from ai.Battlesession import BattleSession
from core.ErrorLog import log_error

from .Shared import (
    _get_session,
    _player_to_snap,
    _player_dict,
    _save_battle_to_db,
)

battle_bp = Blueprint("battle", __name__)


# ─────────────────────────────────────────────
# 전투 시작 헬퍼
# ─────────────────────────────────────────────

def _get_current_map_layer(gs: dict) -> int:
    """현재 노드맵 층. 배틀 배경/로그 메타용."""
    try:
        if gs.get("battle_map_layer") is not None:
            return int(gs.get("battle_map_layer") or 0)
        return int((gs.get("map") or {}).get("current_layer") or 0)
    except Exception:
        return 0


def _unit_to_snap(unit) -> "EntitySnapshot":
    """
    _SnapUnit 또는 Unit → EntitySnapshot 변환.
    BattleSession이 EntitySnapshot을 요구할 때 사용.
    이미 EntitySnapshot이면 그대로 반환.
    """
    from ai.battle import EntitySnapshot as ES
    if isinstance(unit, ES):
        return unit
    snap = ES(
        name   = unit.name,
        hp     = unit.hp,     maxhp  = unit.hp,
        mp     = getattr(unit, "mp", 0),
        maxmp  = getattr(unit, "mp", 0),
        stg    = unit.stg,    arm    = unit.arm,
        sparm  = unit.sparm,  sp     = getattr(unit, "sp", 0),
        luc    = unit.luc,    lv     = unit.lv,
        spd    = getattr(unit, "spd", 10.0),
        physical_resist = getattr(unit, "physical_resist", 1.0),
        magical_resist  = getattr(unit, "magical_resist",  1.0),
        dodge_bonus     = getattr(unit, "dodge_bonus", 0.0),
        first_strike    = getattr(unit, "first_strike", False),
        first_attack_bonus = getattr(unit, "first_attack_bonus", 1.0),
        enemy_type      = getattr(unit, "enemy_type", unit.name),
        attack_element  = getattr(unit, "attack_element", ""),
    )
    # 원소 초기 큐 보존 (원소 슬라임 유실 방지)
    _init_q = getattr(unit, "init_element_queue", None) or getattr(unit, "element_queue", [])
    if _init_q:
        snap.element_queue = list(_init_q)
    return snap


def _start_battle(gs: dict, enemy, is_boss: bool = False) -> dict:
    """단일 전투 BattleSession 생성 후 초기 상태 반환."""
    from ai.battle import EntitySnapshot
    player_snap = _player_to_snap(gs["player"], gs["inventory"])
    enemy_snap  = EntitySnapshot.from_enemy(enemy)

    gs["battle"] = BattleSession(
        player_snap,
        enemy          = enemy_snap,
        items          = gs["inventory"].to_flat_list(),
        is_boss        = is_boss,
        enemy_origins  = [enemy],
        player_original= gs["player"],
    )
    # ★ 전투 시작 시 실제 큐 첫 행동자 반영 (적 선공이면 버튼 안 켜지게)
    bs = gs["battle"]
    bs.battle_meta = {
        "node_type":   gs.get("battle_node_type") or _get_current_node_type(gs) or "battle",
        "chapter":     gs.get("chapter", 1),
        "current_layer": _get_current_map_layer(gs),
        "battle_type": "1v1",
        "source":      "human",
    }
    na, aidx = bs._peek_next_actor()
    return bs._state(messages=[f"{enemy.name}이(가) 나타났다!"],
                     next_actor=na, acting_enemy_idx=aidx)


def _start_battle_multi(gs: dict, enemies: list, is_boss: bool = False) -> dict:
    """다대일 전투 BattleSession 생성 후 초기 상태 반환."""
    from ai.battle import EntitySnapshot
    player_snap  = _player_to_snap(gs["player"], gs["inventory"])
    enemy_snaps  = [EntitySnapshot.from_enemy(e) for e in enemies]

    gs["battle"] = BattleSession(
        player_snap,
        enemies        = enemy_snaps,
        items          = gs["inventory"].to_flat_list(),
        is_boss        = is_boss,
        enemy_origins  = list(enemies),
        player_original= gs["player"],
    )
    counts = {}
    for e in enemies:
        counts[e.name] = counts.get(e.name, 0) + 1
    parts = [f"{n}마리의 {name}" if n > 1 else name for name, n in counts.items()]
    msg = f"⚠ {', '.join(parts)}이(가) 나타났다!"
    # ★ 전투 시작 시 실제 큐 첫 행동자를 next_actor로 반영
    #   (기본 "player"로 나가면 적 선공인데도 버튼이 켜져 첫 입력이 유실됨)
    bs = gs["battle"]
    # 행동 로그(state_t)용 메타 — 노드/챕터/전투타입 주입
    bs.battle_meta = {
        "node_type":   gs.get("battle_node_type") or _get_current_node_type(gs) or "battle",
        "chapter":     gs.get("chapter", 1),
        "current_layer": _get_current_map_layer(gs),
        "battle_type": f"1v{len(bs.enemies)}",
        "source":      "human",
    }
    na, aidx = bs._peek_next_actor()
    return bs._state(messages=[msg], next_actor=na, acting_enemy_idx=aidx)


# ─────────────────────────────────────────────
# 경험치 계산 — 몬스터 난이도/마릿수 기반
# ─────────────────────────────────────────────

# 다대일 경험치 배율 (스탯 90%/80% 감소와 별개로 exp도 감소)
_MULTI_EXP_MULT = {1: 1.00, 2: 0.90, 3: 0.75}

# 등급/난이도 → maxexp 비율 (Enemy_Class.exp_reward와 동일 기준)
_EXP_RATIO_BY_GRADE = {"상": 0.80, "중": 0.55, "하": 0.45}
_EXP_RATIO_BY_DIFF  = {"hard": 0.80, "normal": 0.55, "easy": 0.45}


def _enemy_exp(e, player_maxexp: int) -> int:
    """몬스터 1마리의 기본 경험치.

    우선순위:
      1) 보스 — 중간 보스 = maxexp×1.00 / 최종 보스 = 0
      2) exp_reward() 보유 (game.Enemy_Class.Unit) — grade 기반 정확값
      3) difficulty (hook 경유 _SnapUnit/EntitySnapshot — easy/normal/hard)
      4) grade (명시값이 있는 경우)
      5) 기본 '중' (0.55)
    ※ 3을 4보다 먼저 보는 이유: _SnapUnit의 grade는 getattr 기본값 '중'으로
      채워질 수 있어, 실측값인 difficulty가 있으면 그쪽이 신뢰도가 높음.
    """
    name = getattr(e, "name", "")
    if name == "최종 보스":
        return 0
    if name == "중간 보스":
        return int(player_maxexp * 1.00)

    if hasattr(e, "exp_reward"):
        try:
            return int(e.exp_reward(player_maxexp))
        except Exception:
            pass

    diff = getattr(e, "difficulty", "") or ""
    if diff in _EXP_RATIO_BY_DIFF:
        return int(player_maxexp * _EXP_RATIO_BY_DIFF[diff])

    grade = getattr(e, "grade", "") or ""
    if grade in _EXP_RATIO_BY_GRADE:
        return int(player_maxexp * _EXP_RATIO_BY_GRADE[grade])

    return int(player_maxexp * 0.55)   # 기본 '중'


def _get_defeated_list(battle) -> list:
    """처치 몬스터 목록: defeated_origins 우선 (원본 Unit — 정확값),
    비어 있으면 battle.enemies로 폴백. (경험치/보상 공용)"""
    defeated = [o for o in getattr(battle, "defeated_origins", []) if o is not None]
    if not defeated:
        enemies = list(getattr(battle, "enemies", []) or [])
        # 승리 시점이므로 전부 처치됐다고 간주 (hp 기준 필터는 안전용)
        defeated = [e for e in enemies if getattr(e, "hp", 0) <= 0] or enemies
    return defeated


def _get_current_node_type(gs: dict):
    """현재 전투의 node_type ("battle"/"elite"/...) 또는 None.

    1순위: gs["battle_node_type"] — 전투 시작 시점에 노드 진입 라우트가
           명시적으로 저장한 값 (엘리트 판정용, 없으면 무시)
    2순위: pending_node_id + gs["map"] dict 직접 스캔 (폴백)
    """
    nt = gs.get("battle_node_type")
    if nt:
        return nt
    node_id = gs.get("pending_node_id")
    map_data = gs.get("map")
    if not node_id or not map_data:
        return None
    for nd in map_data.get("nodes", []):
        if nd.get("node_id") == node_id:
            return nd.get("node_type")
    return None


def _calc_victory_exp(player, battle) -> int:
    """승리 경험치 = Σ(각 몬스터 기본 exp) × 다대일 배율."""
    defeated = _get_defeated_list(battle)
    if not defeated:
        return 0
    total_base = sum(_enemy_exp(e, player.maxexp) for e in defeated)
    mult = _MULTI_EXP_MULT.get(len(defeated), _MULTI_EXP_MULT[3])
    return int(total_base * mult)


def _finish_battle(gs: dict, battle, result: dict, winner: str) -> None:
    """
    전투 종료 공통 처리:
      1. 플레이어 HP/MP/경험치 처리 (승/패/도망)
      2. BattleSession items → Inventory 재반영 (★보상보다 먼저)
      3. 전투 보상 (골드+드랍, 승리+비보스만)
      4. 중간 보스 보상
      5. result["player"] 스냅샷 → DB 저장
      6. gs["battle"] 정리
    """
    player = gs["player"]

    if winner == "player":
        player.hp = result["player_hp"]
        player.mp = result["player_mp"]
        exp = _calc_victory_exp(player, battle)
        LV_(player).Get_exp(player, reward_exp=exp)
        gs["hook"].check_level_up()
        result["exp_gained"] = exp
        result["level_up"]   = player.lv

    elif winner == "enemy":
        player.hp = 0
        result["exp_gained"] = 0

    elif winner == "escaped":
        player.hp = result["player_hp"]
        player.mp = result["player_mp"]
        result["exp_gained"] = 0

    # ── (순서 중요) BattleSession items → Inventory 재반영을 "먼저" 수행 ──
    #    전투 중 소비/획득 반영. 이걸 보상 지급 뒤에 하면 new_inv가
    #    보상 아이템을 덮어써 사라지는 버그가 있었음 → 재반영 → 보상 순서 고정.
    bs_items = getattr(battle, "items", None)
    if bs_items is not None:
        new_inv = Inventory.new()
        for item_name in bs_items:
            new_inv.add(item_name)
        gs["inventory"] = new_inv
        gs["items"]     = new_inv.to_flat_list()

    # ── 전투 보상: 골드 + 아이템 드랍 (승리 + 보스 전투 제외) ──
    if winner == "player" and not getattr(battle, "is_boss", False):
        from game.Rewards import calc_battle_rewards
        node_type = _get_current_node_type(gs)
        rw = calc_battle_rewards(_get_defeated_list(battle), node_type)
        gs["gold"] = gs.get("gold", 0) + rw["gold"]
        gained = []   # 실제 획득 성공한 아이템만
        for it in rw["items"]:
            add_res = gs["inventory"].add(it)
            if add_res.get("ok"):
                gained.append(it)
            else:
                rw["messages"].append(f"가방이 가득 차 {it}을(를) 놓쳤다...")
        gs["items"] = gs["inventory"].to_flat_list()
        result["gold_gained"]   = rw["gold"]
        result["items_gained"]  = gained          # 성공분만 (실패는 메시지로만)
        result["relics_gained"] = rw["relics"]    # 유물 자리 (현재 항상 [])
        result["gold"]          = gs["gold"]
        # 보상 로그는 messages로만 표시 (gold_gained/items_gained는 데이터용)
        result["messages"].extend(rw["messages"])

    # 중간 보스 클리어 보상 (재반영 이후 지급 — 덮어쓰기 방지)
    if battle.enemy.name == "중간 보스" and winner == "player":
        gs["mid_boss_cleared"] = True
        gs["inventory"].add("HP_L_potion")
        gs["items"] = gs["inventory"].to_flat_list()
        result["messages"].append("보상: HP_L_potion 획득!")

    # 모든 보상 지급 후 플레이어/인벤토리 스냅샷
    result["player"] = _player_dict(player, gs["inventory"])

    # 행동 로그 마지막 레코드에 최종 보상 병합 (state-action-result 완결)
    if hasattr(battle, "rl_finalize"):
        battle.rl_finalize({
            "winner":       winner,
            "exp_gained":   result.get("exp_gained", 0),
            "gold_gained":  result.get("gold_gained", 0),
            "items_gained": result.get("items_gained", []),
        })

    # DB 저장 (보상 반영된 result 기준)
    _save_battle_to_db(gs, battle, result, winner)

    # ── 패배 시 AI 복기 리포트 생성 (BehaviorAnalyzer/FeedbackEngine) ──
    #    core/Balance_Hook.py의 after_battle() 참고 — 실패해도 게임 진행에는
    #    영향 없어야 하므로 별도 try/except로 감쌈.
    if winner == "enemy":
        try:
            battle_result = battle.to_battle_result()
            report = gs["hook"].after_battle(battle_result)
            if report:
                result["feedback"] = {
                    "headline":    report.headline,
                    "good_plays":  report.good_plays,
                    "bad_plays":   report.bad_plays,
                    "suggestions": report.suggestions,
                    "score":       report.score,
                }
        except Exception as e:
            log_error("battle_feedback_generation", e)

    gs["battle"] = None
    gs.pop("battle_node_type", None)   # 전투 종료 — 노드 타입 캐시 초기화
    gs.pop("battle_map_layer", None)   # 전투 종료 — 배틀 배경 층 캐시 초기화

    # 노드맵 사용 중이면 승리 시에만 노드 완료 (패배/도망은 노드 유지)
    if winner == "player" and gs.get("pending_node_id") and gs.get("map"):
        try:
            from game.Map import FloorMap
            fmap = FloorMap.from_dict(gs["map"])
            fmap.mark_visited(gs["pending_node_id"])
            gs["map"] = fmap.to_dict()
            result["map"] = fmap.get_state()
            result["map_done"] = fmap.completed
            gs["pending_node_id"] = None

            if fmap.completed:
                # 런 종료 처리
                from app.Map import _finish_run
                _finish_run(gs, "clear" if winner == "player" else "dead")
        except Exception as e:
            print(f"[Map] node complete failed: {e}")


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@battle_bp.route("/api/battle/state", methods=["GET"])
def battle_state():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404
    if gs["battle"] is None:
        return jsonify({"ok": False, "error": "전투 중이 아닙니다."}), 400
    return jsonify(gs["battle"]._state())


@battle_bp.route("/api/battle/action", methods=["POST"])
def battle_action():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data   = request.get_json() or {}
    action = data.get("action", "").strip()
    if not action:
        return jsonify({"ok": False, "error": "action이 필요합니다."}), 400

    battle = gs["battle"]
    if battle is None:
        return jsonify({"ok": False, "error": "전투 중이 아닙니다."}), 400

    result = battle.step(action)

    if result["done"]:
        winner = result["winner"]
        _finish_battle(gs, battle, result, winner)

    return jsonify({"ok": True, **result})
