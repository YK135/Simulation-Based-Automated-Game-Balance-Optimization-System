"""
app/shared.py — 공용 상태 + 헬퍼
─────────────────────────────────────────────
모든 Blueprint가 공유하는 것들:
  - GAME_SESSIONS dict
  - _get_session()
  - _get_db_user_id()
  - _player_to_snap()
  - _player_dict()
  - _save_battle_to_db()
"""
from __future__ import annotations

import json
from typing import Optional

from flask import session

from game.Inventory import Inventory
from ai.battle import EntitySnapshot


# ─────────────────────────────────────────────
# 전역 세션 저장소
# ─────────────────────────────────────────────
# user_id(str) → gs(dict) 매핑.
# 2학기 PostgreSQL 전환 시 이 dict만 DB로 교체.
GAME_SESSIONS: dict = {}


# ─────────────────────────────────────────────
# 세션 헬퍼
# ─────────────────────────────────────────────

def _get_session() -> Optional[dict]:
    """Flask session 쿠키의 user_id로 GAME_SESSIONS 조회. 없으면 None."""
    uid = session.get("user_id")
    if not uid:
        return None
    return GAME_SESSIONS.get(uid)


def _get_db_user_id() -> Optional[int]:
    """GAME_SESSIONS에 저장된 db_user_id 반환. 없으면 None."""
    gs = _get_session()
    if not gs:
        return None
    return gs.get("db_user_id")


# ─────────────────────────────────────────────
# 직렬화 헬퍼
# ─────────────────────────────────────────────

def _player_to_snap(player, inv) -> EntitySnapshot:
    """
    Player + Inventory → EntitySnapshot 변환.
    BattleSession은 평탄 list를 받으므로 inv.to_flat_list() 사용.
    inv: Inventory 객체 또는 list 호환.
    """
    skills = list(player.skill.learned_skills) if player.skill else []
    if isinstance(inv, Inventory):
        items_list = inv.to_flat_list()
    else:
        items_list = list(inv) if inv else []
    return EntitySnapshot(
        name=player.name,
        hp=player.hp,       maxhp=player.maxhp,
        mp=player.mp,       maxmp=player.maxmp,
        stg=player.stg,     arm=player.arm,
        sparm=player.sparm, sp=player.sp,
        luc=player.luc,     lv=player.lv,
        spd=getattr(player, "spd", 10.0),
        learned_skills=skills,
        items=items_list,
        job=getattr(player, "job", ""),
    )


def _player_dict(player, inv) -> dict:
    """
    Player + Inventory → JSON 직렬화 가능 dict.
    응답에는 items(평탄, 호환용) + inventory(구조화) 둘 다 포함.
    inv: Inventory 객체 또는 list 호환.
    """
    if isinstance(inv, Inventory):
        flat_items = inv.to_flat_list()
        inv_dict   = inv.to_response_dict()
    else:
        flat_items = list(inv) if inv else []
        tmp = Inventory.new()
        for it in flat_items:
            tmp.add(it)
        inv_dict = tmp.to_response_dict()

    return {
        "name":           player.name,
        "job":            player.job,
        "lv":             player.lv,
        "hp":             round(player.hp, 1),
        "maxhp":          round(player.maxhp, 1),
        "mp":             round(player.mp, 1),
        "maxmp":          round(player.maxmp, 1),
        "stg":            round(player.stg, 1),
        "arm":            round(player.arm, 1),
        "sp":             round(player.sp, 1),
        "sparm":          round(player.sparm, 1),
        "spd":            round(getattr(player, "spd", 10.0), 1),
        "luc":            round(player.luc, 1),
        "exp":            player.exp,
        "maxexp":         player.maxexp,
        "skills":         list(player.skill.learned_skills) if player.skill else [],
        "items":          flat_items,
        "inventory":      inv_dict,
        "pending_points": getattr(player, "pending_points", 0),
    }


# ─────────────────────────────────────────────
# DB 저장 헬퍼
# ─────────────────────────────────────────────

def _save_battle_to_db(gs: dict, battle, result: dict, winner: str) -> None:
    """
    전투 결과를 DB에 저장. 실패해도 게임은 계속 진행.
    """
    from DB import get_session as db_session
    from DB.Models import Battle

    db_user_id = gs.get("db_user_id")
    if not db_user_id:
        print("[DB] Battle save skipped: no db_user_id in session")
        return

    player = gs["player"]

    enemies_payload = []
    for e in getattr(battle, "enemies", []):
        diff  = getattr(e, "difficulty", None) or getattr(e, "_difficulty", None)
        label = e.name
        if diff:
            diff_map = {"hard": "상", "normal": "중", "easy": "하"}
            label = f"{e.name}({diff_map.get(diff, diff)})"
        enemies_payload.append({
            "name":       e.name,
            "lv":         getattr(e, "lv", 1),
            "difficulty": diff,
            "label":      label,
        })

    db_result = (
        "win"    if winner == "player"
        else "lose"   if winner == "enemy"
        else "escape"
    )

    try:
        with db_session() as db:
            new_battle = Battle(
                user_id      = db_user_id,
                explore_turn = gs.get("turn", 0),
                enemies      = json.dumps(enemies_payload, ensure_ascii=False),
                is_boss      = bool(getattr(battle, "is_boss", False)),
                is_multi     = len(getattr(battle, "enemies", [])) > 1,
                result       = db_result,
                turns        = result.get("turn", battle.turn),
                player_job   = player.job,
                player_lv    = player.lv,
                hp_remaining = float(result.get("player_hp", player.hp)),
                exp_gained   = int(result.get("exp_gained", 0)),
                skills_used  = getattr(battle, "skills_used", 0),
                items_used   = getattr(battle, "items_used", 0),
            )
            db.add(new_battle)
            db.flush()
            print(f"[DB] Battle saved: id={new_battle.id}, user={db_user_id}, "
                  f"result={db_result}, turns={new_battle.turns}")
    except Exception as e:
        print(f"[DB] Battle save failed: {e}")