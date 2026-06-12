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

from random import randint

from flask import Blueprint, jsonify, request

from game.Lv        import LV_
from game.Inventory import Inventory
from ai.Battlesession import BattleSession

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
    return gs["battle"]._state(messages=[f"{enemy.name}이(가) 나타났다!"])


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
    return gs["battle"]._state(messages=[msg])


def _finish_battle(gs: dict, battle, result: dict, winner: str) -> None:
    """
    전투 종료 공통 처리:
      1. 플레이어 HP/MP 동기화
      2. 경험치 지급 (승리 시)
      3. 중간 보스 보상
      4. DB 저장
      5. BattleSession items → Inventory 재반영
      6. gs["battle"] 초기화
    """
    player = gs["player"]

    if winner == "player":
        player.hp = result["player_hp"]
        player.mp = result["player_mp"]
        exp = randint(45, 60)
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

    # 중간 보스 클리어 보상
    if battle.enemy.name == "중간 보스" and winner == "player":
        gs["mid_boss_cleared"] = True
        gs["inventory"].add("HP_L_potion")
        gs["items"] = gs["inventory"].to_flat_list()
        result["messages"].append("보상: HP_L_potion 획득!")

    # DB 저장
    _save_battle_to_db(gs, battle, result, winner)

    # BattleSession items → Inventory 재반영
    bs_items = getattr(battle, "items", None)
    if bs_items is not None:
        new_inv = Inventory.new()
        for item_name in bs_items:
            new_inv.add(item_name)
        gs["inventory"] = new_inv
        gs["items"]     = new_inv.to_flat_list()

    gs["battle"] = None
    result["player"] = _player_dict(player, gs["inventory"])

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