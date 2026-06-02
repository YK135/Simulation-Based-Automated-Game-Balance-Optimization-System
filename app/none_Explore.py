"""
app/explore.py — 탐험 Blueprint
─────────────────────────────────────────────
엔드포인트:
  POST /api/explore  — 탐험 (랜덤 이벤트)

노드맵 전환 시 이 파일만 수정하면 됨.
  - explore() → chooseNode(node_id) 로 교체
  - 기존 랜덤 이벤트 로직은 그대로 유지하거나 map_service.py로 이동
"""
from __future__ import annotations

from random import randint, random, choice

from flask import Blueprint, jsonify

from game.Enemy_Class import Make_MidBoss, Make_FinalBoss
from game.Inventory   import Inventory

from .Shared  import _get_session, _player_dict
from .Battle  import _start_battle, _start_battle_multi

explore_bp = Blueprint("explore", __name__)

@explore_bp.route("/api/explore", methods=["POST"])
def explore():
    """
    탐험 버튼 누를 때 호출.
    이벤트 확률 (rd 1~20):
      1~12  (60%): 전투
        └ 1~7  (58%): 1대1
        └ 8~10 (25%): 2대1
        └ 11~12(17%): 3대1
      13~15 (15%): 아이템 획득
      16~17 (10%): 휴식 (HP 소량 회복)
      18~20 (15%): 평화 (아무 일 없음)
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    player = gs["player"]
    turn   = gs["turn"]

    if player.hp <= 0:
        return jsonify({"ok": True, "event": "gameover"})

    if gs["battle"] is not None:
        return jsonify({"ok": False, "error": "전투 중입니다. 먼저 전투를 완료하세요."})

    # ── 보스 체크 ──
    if turn >= 50:
        boss  = Make_FinalBoss(player.lv)
        state = _start_battle(gs, boss, is_boss=True)
        return jsonify({"ok": True, "event": "finalboss",
                        "enemy": {"name": boss.name, "hp": boss.hp},
                        "battle_state": state})

    if turn == 25 and not gs["mid_boss_cleared"]:
        cached = gs["hook"]._get_cached_monsters("고블린")
        base   = cached.get("normal", (None, None))[0] if cached else None
        boss   = Make_MidBoss(player.lv, base)
        state  = _start_battle(gs, boss, is_boss=True)
        return jsonify({"ok": True, "event": "midboss",
                        "enemy": {"name": boss.name, "hp": boss.hp},
                        "battle_state": state})

    # ── 일반 이벤트 ──
    gs["turn"] += 1
    rd = randint(1, 20)

    # 전투
    if 1 <= rd <= 12:
        enemy_type = gs["hook"].pick_random_enemy_type()

        if rd <= 7:
            # 1대1
            enemy_snap = gs["hook"].get_enemy(enemy_type)
            enemy      = gs["hook"].make_battle_unit(enemy_snap)
            state      = _start_battle(gs, enemy)
            return jsonify({
                "ok":           True,
                "event":        "battle",
                "enemy":        {"name": enemy.name, "hp": enemy.hp},
                "battle_state": state,
            })
        else:
            # 다대일 (2마리 or 3마리)
            n_enemies = 2 if rd <= 10 else 3
            enemies   = []
            for _ in range(n_enemies):
                t    = gs["hook"].pick_random_enemy_type()
                snap = gs["hook"].get_enemy(t)
                enemies.append(gs["hook"].make_battle_unit(snap))
            state = _start_battle_multi(gs, enemies)
            return jsonify({
                "ok":           True,
                "event":        "battle_multi",
                "enemy_count":  n_enemies,
                "enemies":      [{"name": e.name, "hp": e.hp} for e in enemies],
                "battle_state": state,
            })

    # 아이템 획득
    elif 13 <= rd <= 15:
        from random import choices
        DROP_POOL = [
            ("HP_S_potion", 4), ("MP_S_potion", 4),
            ("HP_M_potion", 2), ("MP_M_potion", 2),
            ("HP_L_potion", 1), ("MP_L_potion", 1),
        ]
        names   = [x[0] for x in DROP_POOL]
        weights = [x[1] for x in DROP_POOL]
        gained  = choices(names, weights=weights, k=1)[0]

        inv    = gs["inventory"]
        result = inv.add(gained)
        gs["items"] = inv.to_flat_list()

        if result["ok"]:
            return jsonify({"ok": True, "event": "item", "item": gained,
                            "message": f"[아이템 획득] {gained}을(를) 발견했다!",
                            "player": _player_dict(player, inv)})
        elif result["reason"] == "special_full":
            return jsonify({"ok": True, "event": "item_full",
                            "incoming": gained,
                            "candidates": result["candidates"],
                            "message": result["message"],
                            "player": _player_dict(player, inv)})
        else:
            return jsonify({"ok": True, "event": "item_rejected",
                            "incoming": gained,
                            "message": result["message"],
                            "player": _player_dict(player, inv)})

    # 휴식 — 바로 회복하지 않고 options 반환 후 /api/rest 별도 호출
    elif 16 <= rd <= 17:
        return jsonify({"ok": True, "event": "rest",
                        "message": "휴식 지점에 도착했다.",
                        "options": [
                            {"key": "heal",  "label": "체력 회복 (maxHP의 1/3)"},
                            {"key": "train", "label": "수련 (경험치 60~80%)"},
                        ]})

    # 아무 일도 없음
    else:
        return jsonify({"ok": True, "event": "nothing",
                        "message": "조용하다... 아무 일도 일어나지 않았다."})