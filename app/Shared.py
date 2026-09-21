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
import os
import secrets
import threading
import time
from typing import Optional

from flask import session, request

from game.Inventory import Inventory
from game.Relics import relic_list_public
from ai.battle.Relics import relic_potion_slot_penalty, relic_maxhp_cost_mult
from ai.battle import EntitySnapshot
from core.RedisCache import redis_get, redis_set
from core.ErrorLog import log_error


# ─────────────────────────────────────────────
# 전역 세션 저장소 (워커별 인메모리 — 1차 캐시)
# ─────────────────────────────────────────────
GAME_SESSIONS: dict = {}


def _get_json_body() -> dict:
    """요청 바디를 JSON dict로 안전하게 파싱한다 — dict가 아닌 JSON(배열,
    숫자, 문자열, bool)이나 빈/잘못된 바디는 전부 빈 dict로 취급한다.
    ★ 예전엔 각 라우트가 직접 `request.get_json() or {}`를 썼는데, `or {}`는
      falsy 값(None, 빈 문자열 등)만 걸러낼 뿐 `[1,2,3]`이나 `42`처럼
      truthy한 non-dict JSON은 그대로 통과시켰다 — 그 값에 .get()/.items()를
      호출하는 순간 500(AttributeError)이 났다(정상적인 잘못된 입력에 대해
      400이 아니라 서버 오류로 응답한 셈)."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    return body if isinstance(body, dict) else {}


def _get_str_field(data: dict, key: str, default: str = "") -> str:
    """data[key]가 실제로 문자열일 때만 strip해서 반환, 아니면 default.
    ★ `data.get(key, default).strip()` 패턴은 요청 JSON에 그 키가 null/숫자/
      배열 등 비-문자열 값으로 존재하면(예: {"name": null}) dict.get()의
      default는 "키가 아예 없을 때만" 적용되므로 그 비-문자열 값이 그대로
      나와 .strip()에서 AttributeError(→500)로 이어졌다."""
    val = data.get(key, default)
    return val.strip() if isinstance(val, str) else default


# ─────────────────────────────────────────────
# 사용자별 요청 락 (동시 요청 직렬화)
# ─────────────────────────────────────────────
# gunicorn --threads 8로 뜨는데, GAME_SESSIONS[uid] 안의 player/battle/
# inventory/map은 요청 사이에 공유되는 가변 객체라 아무 잠금도 없었다 —
# 같은 유저가(중복 클릭, 여러 탭, 또는 API 직접 호출) 동시에 두 요청을
# 보내면 battle.step() 중복 실행, 수련 경험치 중복 지급, 상점에서 같은
# 골드로 동시 구매 같은 경쟁 상태가 그대로 발생할 수 있었다. app/__init__.py
# 의 before_request/teardown_request가 이 락으로 "같은 유저의 요청은 한
# 번에 하나씩"만 처리되게 감싼다 — 다른 유저끼리는 서로 막지 않는다.
_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()

# 락을 오래 못 얻으면(직전 요청이 예외 없이 영원히 안 끝나는 등 극단적 상황)
# 무한정 대기하지 않고 에러로 빠르게 응답한다 — 정상 요청은 전투 계산 포함
# 수십 ms~수백 ms 안에 끝나므로 이 값이면 충분히 여유 있다.
USER_LOCK_TIMEOUT_SECONDS = 8.0


def _get_user_lock(uid: str) -> threading.Lock:
    lock = _user_locks.get(uid)
    if lock is not None:
        return lock
    with _user_locks_guard:
        lock = _user_locks.get(uid)
        if lock is None:
            lock = threading.Lock()
            _user_locks[uid] = lock
        return lock


# ─────────────────────────────────────────────
# 세션 유휴 정리 (인메모리 캐시 무한 증가 방지)
# ─────────────────────────────────────────────
# GAME_SESSIONS는 TTL/최대 크기가 없어서, 서버가 오래 떠 있을수록 한 번이라도
# 접속했던 모든 게스트의 player/BalanceHook 객체가 워커 메모리에 영구히
# 쌓였다. player/inventory/map 등은 매 요청마다 Redis+DB로 write-through
# 되므로(_persist_session), 메모리 캐시에서만 방출해도 다음 요청이 오면
# _get_session()이 Redis→DB 순으로 그대로 복구한다 — 워커 재시작과 동일한
# battle=None 트레이드오프(이미 문서화된 설계)를 오래 유휴한 세션에도
# 적용하는 것뿐, 데이터 유실은 아니다.
_SESSION_MAX_IDLE_SECONDS = 3600       # 1시간 미접속 시 메모리에서만 방출
_SESSION_PRUNE_INTERVAL_SECONDS = 300  # 5분에 한 번만 전수 스캔(매 요청 스캔은 낭비)

_session_last_seen: dict[str, float] = {}
_last_seen_guard = threading.Lock()   # _session_last_seen 전용 — 아래 참고
_last_prune_at = 0.0
_prune_guard = threading.Lock()


def _touch_session(uid: str) -> None:
    # ★ 락 없이 매 요청마다 이 dict에 새 키를 추가할 수 있었는데, 그 상태로
    #   _prune_idle_sessions()가 같은 dict를 순회 중이면(다른 스레드) 파이썬이
    #   "dictionary changed size during iteration"으로 죽을 수 있었다 — 값
    #   갱신(기존 키)만이면 GIL 덕에 괜찮지만, 새 uid의 첫 접속(신규 키 삽입)은
    #   딕셔너리 크기를 바꾸는 경우라 안전하지 않았다.
    with _last_seen_guard:
        _session_last_seen[uid] = time.monotonic()


def _prune_idle_sessions() -> None:
    global _last_prune_at
    now = time.monotonic()
    if now - _last_prune_at < _SESSION_PRUNE_INTERVAL_SECONDS:
        return
    if not _prune_guard.acquire(blocking=False):
        return  # 다른 스레드가 이미 정리 중
    try:
        if now - _last_prune_at < _SESSION_PRUNE_INTERVAL_SECONDS:
            return
        _last_prune_at = now
        cutoff = now - _SESSION_MAX_IDLE_SECONDS
        with _last_seen_guard:
            stale = [uid for uid, ts in _session_last_seen.items() if ts < cutoff]

        for uid in stale:
            # ★ 이 uid의 락을 "지금 실제로 아무도 안 쓰고 있을 때만"(non-blocking
            #   acquire 성공) 정리한다. 예전엔 이 확인 없이 곧장 pop()해서,
            #   진행 중인 요청(POST, 락 보유 중)이 있는 uid의 락 항목이
            #   지워지면 그 틈에 도착한 또 다른 요청이 _get_user_lock()에서
            #   새 Lock()을 만들어 바로 획득해버릴 수 있었다 — "같은 uid의
            #   요청은 한 번에 하나씩만"이라는 보장이 정확히 그 경로로 깨짐
            #   (수련 경험치 중복 지급 등을 막으려고 이 락을 도입한 것과 같은
            #   종류의 문제가 락 자신의 정리 과정에서 재발할 수 있었던 것).
            #   락을 못 잡으면(사용 중) 이번 주기는 건너뛴다 — 처리가 끝나면
            #   다음 5분 주기에 다시 시도되고, 그 사이 실제로 활동했다면
            #   아래 last_seen 재확인에서 애초에 걸러진다.
            with _user_locks_guard:
                lock = _user_locks.get(uid)
                if lock is not None:
                    if not lock.acquire(blocking=False):
                        continue
                    lock.release()
                with _last_seen_guard:
                    # GET 요청은 락을 안 잡으므로 위 확인만으론 "그 사이 다시
                    #   조회했는지"를 못 잡는다 — last_seen을 한 번 더 확인.
                    ts = _session_last_seen.get(uid)
                    if ts is not None and ts >= cutoff:
                        continue
                    _session_last_seen.pop(uid, None)
                GAME_SESSIONS.pop(uid, None)
                _user_locks.pop(uid, None)
    finally:
        _prune_guard.release()


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
        # ★ 런이 이미 clear/dead로 끝났는지 — 이게 빠져 있어서 세션이 복구되면
        #   표시가 사라졌고, 그 뒤 "새 게임"을 누르면 이미 끝난 런을 abandon으로
        #   덮어썼다. DB 쪽에도 안전장치를 뒀다(app/Map.py의 _finish_run).
        "run_finished": bool(gs.get("run_finished", False)),
        "pending_node_id":  gs.get("pending_node_id"),
        "battle_node_type": gs.get("battle_node_type"),
        "battle_map_layer": gs.get("battle_map_layer"),
        # ★ Redis 스냅샷에는 포함(그대로 dict로 저장돼 왕복됨) — DB PlayerState엔
        #   전용 컬럼이 없어 _apply_snapshot_to_row()가 이 필드를 쓰지 않는다.
        #   battle(BattleSession)과 같은 급의 트레이드오프: Redis까지 완전히
        #   사라진 뒤 DB로만 복구하는 극단적 상황에서만 대기 티켓이 유실된다.
        "pending_swaps":    gs.get("pending_swaps", []),
        # 유물 선택 대기 티켓 — pending_swaps와 같은 급 (Redis까지만, DB 컬럼 없음)
        "pending_relic_offer": gs.get("pending_relic_offer"),
        # ★ 이게 빠져있으면 워커 재시작이나 유휴 세션 방출(1시간) 후 같은
        #   pending_node_id로 복구됐을 때 "이 휴식 노드 이미 썼음" 표시가
        #   사라져서, 같은 휴식 노드에서 수련 보상을 다시 받을 수 있었다
        #   (app/Rest.py 참고).
        "rest_used_node_id": gs.get("rest_used_node_id"),
    }


def _gs_from_snapshot(uid: str, snap: dict) -> Optional[dict]:
    """스냅샷 → 런타임 gs 재구성. hook은 새로 생성, battle은 None."""
    if not snap or not snap.get("player"):
        return None

    from game.Player_Class import Player
    from core.Balance_Hook import BalanceHook

    player = Player.from_dict(snap["player"])
    inv = Inventory.from_dict(snap.get("inventory") or {})
    inv.potion_penalty = relic_potion_slot_penalty(getattr(player, "relics", []))   # 유물 → 포션 슬롯
    # ★ 게임에서 없앤 아이템(원소 부착 3종)이 옛 세이브에 남아 있으면 여기서 정리한다 —
    #   안 그러면 쓸 수 없는 아이템이 특수 칸을 영구히 차지한다(game/Inventory.drop_unknown).
    _dropped = inv.drop_unknown()
    if _dropped:
        print(f"[session] 삭제된 아이템 정리: {', '.join(_dropped)} (uid={uid})")
    items = inv.to_flat_list()
    # ★ auto_prewarm=False — 이건 새 게임이 아니라 기존 세션 복구(워커
    #   재시작/유휴 세션 방출/Redis 히트마다 여기로 옴)라, 매번 고블린/박쥐
    #   시뮬 job을 다시 큐에 넣을 필요가 없다.
    hook = BalanceHook(player, items, show_graph=False, verbose=False, auto_prewarm=False)
    hook.attach_items_source(inv.to_flat_list)   # app/Game.py의 새 게임 경로와 동일

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
        "run_finished":     bool(snap.get("run_finished", False)),
        "gold":             snap.get("gold", 100),
        "battle_node_type": snap.get("battle_node_type"),
        "battle_map_layer": snap.get("battle_map_layer"),
        "pending_swaps":    snap.get("pending_swaps", []),
        "pending_relic_offer": snap.get("pending_relic_offer"),
        "rest_used_node_id": snap.get("rest_used_node_id"),
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
                "rest_used_node_id": row.rest_used_node_id,
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
        row.rest_used_node_id = snap["rest_used_node_id"]

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
# 인벤토리 교체 대기 티켓 (pending_swaps)
# ─────────────────────────────────────────────
# 포션/특수 슬롯이 가득 차서 즉시 못 받은 아이템(상점 구매/이벤트 발견/전투
# 보상)은 클라이언트에 "버릴 아이템을 골라라" 모달을 띄우고, 확정되면
# POST /api/inventory/swap로 {ticket_id, drops}를 보낸다. 예전엔 new(획득할
# 아이템)를 클라이언트가 보낸 문자열 그대로 믿고 인벤토리에 넣었다 — 즉 서버가
# 실제로 발급한 적 없는 아이템 id를 new에 넣어 보내면 그대로 생성돼 들어갔다.
# 여기서 "서버가 실제로 발급 대기 중인 아이템"만 티켓으로 등록해두고,
# /api/inventory/swap은 요청의 ticket_id가 정확히 일치할 때만 처리한다(1개
# 소모). 상점 구매(source="shop")는 슬롯이 가득 찬 시점엔 아직 결제 전이므로
# price를 함께 기록해 스왑이 실제로 확정되는 순간 결제한다.
#
# ★ 이름이 아니라 ticket_id로 식별하는 이유: 같은 아이템에 대해 출처가 다른
#   (상점=유료 / 보상=무료) 티켓이 동시에 대기 중일 수 있는데, 이름 매칭이면
#   둘 중 아무거나 먼저 매칭된 게 소모돼 엉뚱한 티켓이 결제/무료 처리될 수
#   있었다. ticket_id는 예측 불가능한 값이라 클라이언트가 다른 유저/세션의
#   티켓을 추측해 소모할 수도 없다.
def _register_pending_swap(gs: dict, item: str, source: str, price: int = 0) -> str:
    """대기 티켓을 등록하고 그 ticket_id를 반환한다."""
    ticket_id = secrets.token_hex(8)
    gs.setdefault("pending_swaps", []).append(
        {"ticket_id": ticket_id, "item": item, "source": source, "price": price}
    )
    return ticket_id


def _pop_pending_swap(gs: dict, ticket_id: str) -> Optional[dict]:
    """ticket_id와 일치하는 대기 티켓 1개를 꺼내 제거. 없으면 None."""
    if not ticket_id:
        return None
    pending = gs.get("pending_swaps") or []
    for i, ticket in enumerate(pending):
        if ticket.get("ticket_id") == ticket_id:
            return pending.pop(i)
    return None


def _restore_pending_swap(gs: dict, ticket: dict) -> None:
    """실패한 스왑 시도(골드 부족/드롭 실패 등) 후 이미 꺼낸 티켓을 그대로
    되돌려놓는다 — 새 ticket_id를 발급하지 않고 원래 id를 유지해야 클라이언트가
    들고 있는 ticket_id로 재시도할 수 있다."""
    gs.setdefault("pending_swaps", []).append(ticket)


# ─────────────────────────────────────────────
# 유물 (game/Relics.py · 11-1 2차 7번) — 선택 대기 티켓 + 지급
#   pending_swaps와 같은 원칙: 클라이언트는 ticket_id와 고른 id만 보내고, 무엇이 제시됐는지는
#   서버 티켓이 안다. 한 번에 하나만 대기(새 제시가 오면 덮어쓴다).
# ─────────────────────────────────────────────

def _register_relic_offer(gs: dict, choices: list) -> str:
    ticket_id = secrets.token_hex(8)
    gs["pending_relic_offer"] = {"ticket_id": ticket_id, "choices": list(choices)}
    return ticket_id


def _pop_relic_offer(gs: dict, ticket_id: str) -> Optional[dict]:
    ticket = gs.get("pending_relic_offer")
    if not ticket_id or not ticket or ticket.get("ticket_id") != ticket_id:
        return None
    gs["pending_relic_offer"] = None
    return ticket


def _restore_relic_offer(gs: dict, ticket: dict) -> None:
    gs["pending_relic_offer"] = ticket


def _sync_inventory_relics(gs: dict) -> None:
    """플레이어 유물 → 인벤토리 규칙(탐욕의 인장: 포션 슬롯 −1). 인벤토리를 새로 만들거나 유물이 바뀔 때 부른다."""
    inv = gs.get("inventory")
    player = gs.get("player")
    if isinstance(inv, Inventory) and player is not None:
        inv.potion_penalty = relic_potion_slot_penalty(getattr(player, "relics", []))


def _grant_relic(gs: dict, relic_id: str) -> bool:
    """유물 지급 — 이미 가졌으면 False. 인벤토리 규칙도 같이 맞춘다."""
    player = gs["player"]
    relics = getattr(player, "relics", None)
    if relics is None:
        player.relics = relics = []
    if relic_id in relics:
        return False
    relics.append(relic_id)
    # 「굶주린 칼날」의 대가 — 얻는 순간 최대 HP를 한 번 깎는다(되돌릴 수 없다).
    # 레벨업 증가분(game/Lv.py는 maxhp에 더하기만 한다)은 깎지 않으므로
    # 늦게 얻을수록 체감 비용이 작아진다 — 의도된 절충이다.
    mult = relic_maxhp_cost_mult(relic_id)
    if mult < 1.0:
        player.maxhp = max(1, int(player.maxhp * mult))
        player.hp = min(player.hp, player.maxhp)
    _sync_inventory_relics(gs)
    return True


# ─────────────────────────────────────────────
# 세션 헬퍼
# ─────────────────────────────────────────────

def _get_session() -> Optional[dict]:
    """Flask session 쿠키의 user_id로 세션 조회.
    메모리(GAME_SESSIONS) → Redis → DB 순으로 찾고, 찾으면 상위 캐시에 채워둔다."""
    uid = session.get("user_id")
    if not uid:
        return None

    _prune_idle_sessions()   # 매 호출마다 스캔하진 않음 — 내부에서 주기 제한

    gs = GAME_SESSIONS.get(uid)
    if gs is not None:
        _touch_session(uid)
        return gs

    snap = redis_get(f"session:{uid}")
    if snap:
        gs = _gs_from_snapshot(uid, snap)
        if gs:
            GAME_SESSIONS[uid] = gs
            _touch_session(uid)
            return gs

    gs = _load_session_from_db(uid)
    if gs:
        GAME_SESSIONS[uid] = gs
        _touch_session(uid)
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

def _pending_node_type(gs: dict):
    """gs["pending_node_id"]가 가리키는 노드의 node_type. 없으면 None.

    ★ 세 블루프린트가 같은 판정을 쓴다 — app/Rest.py(휴식 노드에서만 수련),
      app/Map.py(전투 노드는 노드 완료 API로 끝낼 수 없다),
      app/Battle.py(gs["battle_node_type"]이 없을 때의 폴백).
      각자 복사해 두면 한 곳만 고쳐지는 종류의 판정이라 여기로 모은다."""
    node_id  = gs.get("pending_node_id")
    map_data = gs.get("map")
    if not node_id or not map_data:
        return None
    node = (map_data.get("nodes") or {}).get(node_id)
    return node.get("node_type") if node else None


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
        relics=list(getattr(player, "relics", []) or []),
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
        # 유물 — 이름·아이콘·설명까지 서버가 내려준다 (프론트 표를 늘리지 않기 위해)
        "relics":         relic_list_public(getattr(player, "relics", [])),
        # 스킬 2택 1 대기 — [{lv, options:[{name, mp, type, desc}]}] (game/Lv.py JOB_SKILL_CHOICES)
        "pending_skill_choices": _skill_choice_payload(player),
    }


def _skill_choice_payload(player) -> list:
    from game.Lv import skill_choice_pair
    from game.Skill import SKILL_BRIEF
    from ai.battle import SKILL_META
    out = []
    for lv in getattr(player, "pending_skill_choices", None) or []:
        pair = skill_choice_pair(player, lv)
        if not pair:
            continue
        out.append({"lv": lv, "options": [{
            "name": sk,
            "mp": SKILL_META.get(sk, {}).get("mp", 0),
            "hp_cost": int(round(SKILL_META.get(sk, {}).get("hp_cost_ratio", 0.0) * 100)),   # 피의 격노: 현재 HP %
            "type": SKILL_META.get(sk, {}).get("type", ""),
            "desc": SKILL_BRIEF.get(sk, ""),
        } for sk in pair]})
    return out


# ─────────────────────────────────────────────
# DB 저장 헬퍼
# ─────────────────────────────────────────────

# RL 로그 레코드 포맷 자체가 바뀔 때(필드 추가/제거/의미 변경) 올려서, 나중에
# 이 데이터로 학습할 때 어느 버전 이후 로그만 쓸지 걸러낼 수 있게 한다.
_RL_LOG_SCHEMA_VERSION = 2  # v2: run_id/battle_id/schema_version/code_revision 추가

_code_revision_cache: Optional[str] = None


def _code_revision() -> str:
    """현재 배포된 코드의 짧은 git 커밋 해시(가능하면) — best-effort, 실패하면
    'unknown'.
    ★ 밸런스 상수(GRADE_MULT, STAT_SCALE 등)가 수동 버전 문자열 없이 자주
      바뀌는 프로젝트라, 사람이 매번 올려야 하는 "balance_version" 문자열은
      깜빡하고 안 올리면 오히려 거짓 정보가 된다 — 커밋 해시는 커밋할 때마다
      자동으로 바뀌므로 유지보수 없이도 "이 로그가 정확히 어느 코드 시점에
      만들어졌는지"를 정확하게 알려준다. 프로세스 생애 동안 1회만 계산해 캐싱
      (매 전투마다 서브프로세스를 새로 띄우면 낭비)."""
    global _code_revision_cache
    if _code_revision_cache is not None:
        return _code_revision_cache
    try:
        import subprocess
        rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ).stdout.strip()
        _code_revision_cache = rev or "unknown"
    except Exception:
        _code_revision_cache = "unknown"
    return _code_revision_cache


def _save_rl_log(gs: dict, battle, run_id: Optional[int] = None,
                  battle_id: Optional[int] = None) -> None:
    """(state, action, result) 행동 로그를 BattleLog 테이블에 저장.
    ※ 예전엔 data/RL_LOG/user_{id}/*.json 로컬 파일이었음 — 호스팅 디스크가
      ephemeral이면 재배포마다 학습 데이터가 사라질 수 있어 DB로 이전.
      실패해도 게임은 계속 진행.

    run_id/battle_id: 있으면 함께 저장해 user_id와 함께 3중 식별자로 이
      로그가 어느 유저의 어느 런의 어느 전투에서 나왔는지 재구성 가능하게
      한다(게스트는 run_id는 있어도 db_user_id/battle_id가 없을 수 있음 —
      _save_battle_to_db에서 db_user_id가 없으면 Battle 자체를 안 만들므로
      battle_id는 항상 None).

    ※ RNG seed는 의도적으로 기록하지 않는다 — 이 프로세스 전체가 모듈 전역
      random(단일 공유 상태)을 스레드 세이프 처리 없이 쓰기 때문에(gunicorn
      --threads 8), 전투 시작 시점의 random.getstate()를 찍어도 그 사이 다른
      스레드의 동시 전투가 같은 전역 상태에서 난수를 소모하면 "이 상태에서
      재현 가능하다"는 보장 자체가 성립하지 않는다 — 잘못된 재현성을
      약속하느니 아예 기록하지 않는 편이 정직하다. 진짜 재현성이 필요해지면
      먼저 전투별로 독립된 random.Random() 인스턴스를 쓰도록(현재 모든 전투
      계산 코드가 공유하는) 리팩터링이 선행돼야 한다."""
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
            "job":            getattr(player, "job", "") if player else "",
            "level":          getattr(player, "lv", 0) if player else 0,
            "enemy_count":    len(getattr(battle, "enemies", [])),
            "enemies":        [e.name for e in getattr(battle, "enemies", [])],
            "schema_version": _RL_LOG_SCHEMA_VERSION,
            "code_revision":  _code_revision(),
        })

        with db_session() as db:
            db.add(BattleLog(
                user_id=db_user_id,
                run_id=run_id,
                battle_id=battle_id,
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

    ★ Battle 요약 행을 먼저 저장해 그 id를 확보한 뒤 RL 로그에 battle_id로
      실어 보낸다 — 순서를 반대로 하면(예전처럼 RL 로그 먼저) 그 시점엔
      Battle.id가 아직 존재하지 않아 연결할 방법이 없다.
    """
    from DB import get_session as db_session
    from DB.Models import Battle

    db_user_id = gs.get("db_user_id")
    run_id     = gs.get("run_id")
    battle_id  = None

    if db_user_id:
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
                    # ★ gs["turn"]은 초기화 후 어디서도 증가하지 않는 필드라
                    #   "몇 번째 탐험에서"를 항상 0으로 만들었다 — 실제로
                    #   증가하는 탐험 카운터는 map_turn(app/Map.py의
                    #   choose_node에서 매 노드 선택마다 +1).
                    explore_turn = gs.get("map_turn", 0),
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
                battle_id = new_battle.id
                print(f"[DB] Battle saved: id={new_battle.id}, user={db_user_id}, "
                      f"result={db_result}, turns={new_battle.turns}")
        except Exception as e:
            log_error("battle_save_db", e)
    else:
        print("[DB] Battle save skipped: no db_user_id in session")

    # ── RL 행동 로그는 DB 유저가 없어도(게스트) 항상 저장 ──
    _save_rl_log(gs, battle, run_id=run_id, battle_id=battle_id)