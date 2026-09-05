"""
app/shared.py — 공용 상태 + 헬퍼
─────────────────────────────────────────────
모든 Blueprint가 공유하는 것들:
  - GAME_SESSIONS dict (워커 인메모리 1차 캐시)
  - _get_session()      — 메모리 → Redis → DB 3단계 조회/복구
  - _persist_session()  — 세션을 Redis+DB에 write-through 저장
  - _get_db_user_id()
  - _player_to_snap()
  - _player_dict()
  - _save_battle_to_db()

세션 영속화 설계 (배포 인프라 하드닝 v2):
  진행 중인 battle(BattleSession)/hook(BalanceHook)은 저장하지 않는다 —
  스티키 세션(같은 유저는 항상 같은 워커) 전제라 워커가 살아있는 한
  GAME_SESSIONS(메모리)에서 바로 찾아진다. Redis/DB는 워커 재시작·스케일
  이벤트처럼 메모리가 비어있을 때만 타는 폴백이며, 그 경우 battle=None으로
  복구되고(진행 중이던 전투 1개만 다시 시작하면 됨) 나머지(player/inventory/
  map/챕터/골드 등)는 그대로 이어진다.
"""
from __future__ import annotations

import json
from typing import Optional

from flask import session

from game.Inventory import Inventory
from ai.battle import EntitySnapshot
from core.RedisCache import redis_get, redis_set
from core.ErrorLog import log_error


# ─────────────────────────────────────────────
# 전역 세션 저장소 (워커별 인메모리 — 1차 캐시)
# ─────────────────────────────────────────────
GAME_SESSIONS: dict = {}


# ─────────────────────────────────────────────
# 세션 영속화 — 직렬화/역직렬화
# ─────────────────────────────────────────────

def _snapshot_dict(gs: dict) -> dict:
    """gs(런타임 dict) → 직렬화 가능한 스냅샷. Redis에는 이 형태 그대로 저장,
    DB에는 player/inventory/map만 문자열로 dump해서 각 컬럼에 나눠 저장."""
    player = gs.get("player")
    inv = gs.get("inventory")
    return {
        "player":    player.to_dict() if player else None,
        "inventory": inv.to_dict() if inv else None,
        "map":       gs.get("map"),
        "chapter":   gs.get("chapter"),
        "turn":      gs.get("turn", 0),
        "map_turn":  gs.get("map_turn", 0),
        "mid_boss_cleared": bool(gs.get("mid_boss_cleared", False)),
        "gold":      gs.get("gold", 100),
        "run_id":    gs.get("run_id"),
        "pending_node_id":  gs.get("pending_node_id"),
        "battle_node_type": gs.get("battle_node_type"),
        "battle_map_layer": gs.get("battle_map_layer"),
    }


def _gs_from_snapshot(uid: str, snap: dict) -> Optional[dict]:
    """스냅샷 → 런타임 gs 재구성. hook은 새로 생성, battle은 None."""
    if not snap or not snap.get("player"):
        return None

    from game.Player_Class import Player
    from core.Balance_Hook import BalanceHook

    player = Player.from_dict(snap["player"])
    inv = Inventory.from_dict(snap.get("inventory") or {})
    items = inv.to_flat_list()
    hook = BalanceHook(player, items, show_graph=False, verbose=False)

    try:
        db_user_id = int(uid)
    except (TypeError, ValueError):
        db_user_id = None

    return {
        "player":           player,
        "inventory":        inv,
        "items":            items,
        "battle":           None,
        "turn":             snap.get("turn", 0),
        "mid_boss_cleared": bool(snap.get("mid_boss_cleared", False)),
        "last_event":       None,
        "hook":             hook,
        "db_user_id":       db_user_id,
        "nickname":         player.name,
        "map":              snap.get("map"),
        "chapter":          snap.get("chapter"),
        "map_turn":         snap.get("map_turn", 0),
        "pending_node_id":  snap.get("pending_node_id"),
        "run_id":           snap.get("run_id"),
        "gold":             snap.get("gold", 100),
        "battle_node_type": snap.get("battle_node_type"),
        "battle_map_layer": snap.get("battle_map_layer"),
    }


def _load_session_from_db(uid: str) -> Optional[dict]:
    """Redis에도 없을 때 최종 폴백 — DB(PlayerState)에서 복구."""
    try:
        user_id = int(uid)
    except (TypeError, ValueError):
        return None

    from DB import get_session as db_session
    from DB.Models import PlayerState

    try:
        with db_session() as db:
            row = db.query(PlayerState).filter_by(user_id=user_id).first()
            if not row:
                return None
            snap = {
                "player":    json.loads(row.player_json),
                "inventory": json.loads(row.inventory_json),
                "map":       json.loads(row.map_json) if row.map_json else None,
                "chapter":   row.chapter,
                "turn":      row.turn,
                "map_turn":  row.map_turn,
                "mid_boss_cleared": row.mid_boss_cleared,
                "gold":      row.gold,
                "run_id":    row.run_id,
                "pending_node_id":  row.pending_node_id,
                "battle_node_type": row.battle_node_type,
                "battle_map_layer": row.battle_map_layer,
            }
    except Exception as e:
        log_error("session_db_recovery", e)
        return None

    return _gs_from_snapshot(uid, snap)


def _persist_session(uid: str, gs: dict) -> None:
    """세션을 Redis(있으면)+DB에 write-through. app/__init__.py의
    after_request 훅에서 매 요청마다 호출됨 — 실패해도 응답엔 영향 없음."""
    if not gs or not gs.get("player"):
        return

    snap = _snapshot_dict(gs)
    redis_set(f"session:{uid}", snap)

    try:
        user_id = int(uid)
    except (TypeError, ValueError):
        return  # DB 유저 생성이 실패했던 게스트는 FK가 없어 DB 저장 스킵 (Redis만)

    def _apply_snapshot_to_row(row) -> None:
        row.player_json     = json.dumps(snap["player"], ensure_ascii=False)
        row.inventory_json  = json.dumps(snap["inventory"], ensure_ascii=False)
        row.map_json        = json.dumps(snap["map"], ensure_ascii=False) if snap["map"] else None
        row.chapter          = snap["chapter"]
        row.turn              = snap["turn"]
        row.map_turn          = snap["map_turn"]
        row.mid_boss_cleared  = snap["mid_boss_cleared"]
        row.gold              = snap["gold"]
        row.run_id            = snap["run_id"]
        row.pending_node_id   = snap["pending_node_id"]
        row.battle_node_type  = snap["battle_node_type"]
        row.battle_map_layer  = snap["battle_map_layer"]

    try:
        from DB import get_session as db_session
        from DB.Models import PlayerState
        from sqlalchemy.exc import IntegrityError

        with db_session() as db:
            row = db.query(PlayerState).filter_by(user_id=user_id).first()
            if row is None:
                # ★ 멀티 스레드(gunicorn --threads N)에서 같은 user_id로 두 요청이
                #   동시에 여기 들어오면 둘 다 row=None을 보고 INSERT를 시도할 수
                #   있음 — PK 충돌(IntegrityError) 시 조용히 버리지 않고 UPDATE로
                #   전환해서 재시도.
                row = PlayerState(user_id=user_id)
                db.add(row)
                _apply_snapshot_to_row(row)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    row = db.query(PlayerState).filter_by(user_id=user_id).first()
                    if row is None:
                        raise
                    _apply_snapshot_to_row(row)
            else:
                _apply_snapshot_to_row(row)
    except Exception as e:
        log_error("session_persist_db", e)


# ─────────────────────────────────────────────
# 세션 헬퍼
# ─────────────────────────────────────────────

def _get_session() -> Optional[dict]:
    """Flask session 쿠키의 user_id로 세션 조회.
    메모리(GAME_SESSIONS) → Redis → DB 순으로 찾고, 찾으면 상위 캐시에 채워둔다."""
    uid = session.get("user_id")
    if not uid:
        return None

    gs = GAME_SESSIONS.get(uid)
    if gs is not None:
        return gs

    snap = redis_get(f"session:{uid}")
    if snap:
        gs = _gs_from_snapshot(uid, snap)
        if gs:
            GAME_SESSIONS[uid] = gs
            return gs

    gs = _load_session_from_db(uid)
    if gs:
        GAME_SESSIONS[uid] = gs
        redis_set(f"session:{uid}", _snapshot_dict(gs))
        return gs

    return None


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

def _save_rl_log(gs: dict, battle) -> None:
    """(state, action, result) 행동 로그를 BattleLog 테이블에 저장.
    ※ 예전엔 data/RL_LOG/user_{id}/*.json 로컬 파일이었음 — 호스팅 디스크가
      ephemeral이면 재배포마다 학습 데이터가 사라질 수 있어 DB로 이전.
      실패해도 게임은 계속 진행."""
    rl_log = getattr(battle, "rl_log", None)
    if not rl_log:
        return
    try:
        from DB import get_session as db_session
        from DB.Models import BattleLog

        db_user_id = gs.get("db_user_id")
        player = gs.get("player")
        meta = dict(getattr(battle, "battle_meta", {}) or {})
        meta.update({
            # 최소 메타 필드 (개인정보 없음 — email/nickname 저장 금지, uid는 익명 숫자)
            "job":         getattr(player, "job", "") if player else "",
            "level":       getattr(player, "lv", 0) if player else 0,
            "enemy_count": len(getattr(battle, "enemies", [])),
            "enemies":     [e.name for e in getattr(battle, "enemies", [])],
        })

        with db_session() as db:
            db.add(BattleLog(
                user_id=db_user_id,
                meta_json=json.dumps(meta, ensure_ascii=False),
                records_json=json.dumps(rl_log, ensure_ascii=False),
            ))
    except Exception as ex:
        # ★ 이 데이터가 이 프로젝트의 실제 목적(모방학습/RL용 로그 수집)이라
        #   조용히 유실되면 안 됨 — log_error()로 DB에 남겨서 나중에라도 확인 가능.
        log_error("rl_log_save", ex)


def _save_battle_to_db(gs: dict, battle, result: dict, winner: str) -> None:
    """
    전투 결과를 DB에 저장. 실패해도 게임은 계속 진행.
    """
    from DB import get_session as db_session
    from DB.Models import Battle

    # ── RL 행동 로그는 DB 유저가 없어도(게스트) 항상 저장 ──
    _save_rl_log(gs, battle)

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
        log_error("battle_save_db", e)