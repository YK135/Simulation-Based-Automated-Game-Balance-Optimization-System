"""
app.py — Flask 진입점
─────────────────────────────────────────────
터미널 기반 Main.py를 REST API로 교체.
BattleSession.py가 전투 상태를 들고 있고,
브라우저 요청 하나 → API 응답 하나 구조.

엔드포인트:
  POST /api/new_game          — 게임 시작 (이름, 직업)
  GET  /api/status            — 현재 플레이어 상태
  POST /api/explore           — 탐험 (다음 이벤트 결정)
  GET  /api/battle/state      — 현재 전투 상태
  POST /api/battle/action     — 전투 행동 (공격/스킬/아이템/도망)
  POST /api/use_item          — 필드에서 아이템 사용
  GET  /api/skills            — 스킬 목록
  GET  /api/items             — 아이템 목록

세션:
  Flask session 쿠키로 user_id 관리.
  게임 상태는 서버 메모리(GAME_SESSIONS dict)에 저장.
  → 2학기 PostgreSQL 전환 시 이 dict만 DB로 교체하면 됨.
"""
from __future__ import annotations

import os
import sys
import copy
import uuid
from DB import init_db
from random import randint, random

from flask import Flask, request, jsonify, session, send_from_directory

# ── 경로 설정 ────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ["game", "ai", "core", "interface"]:
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, ROOT)

# ── 게임 모듈 import ─────────────────────────
from game.Player_Class import Player, create_player_by_job
from game.Enemy_Class  import Make_Random_Monster, Make_MidBoss, Make_FinalBoss
from game.Skill        import Ply_Skill
from game.Lv           import LV_, Allocate_Stat_Pooints
from game.Item         import Item_
from ai.Battle_Engine  import EntitySnapshot
from ai.Simulator      import MonsterFactory
from core.Balance_Hook import BalanceHook
from ai.Battlesession import BattleSession   # Flask용 전투 세션

# ── DB ─────────────────────────────────────
from DB import init_db, get_session as db_session
from DB.Models import User, Battle
from DB.Queries import (
    get_score_ranking,
    get_pioneer_ranking,
    get_user_rank_position,
)


# ── Flask 앱 ─────────────────────────────────
# Flask 앱 초기화.
# static_folder를 절대경로로 지정해서 작업 디렉토리(cwd)와 무관하게 동작하도록 함.
# 이 파일이 있는 폴더 기준 'static/' 을 정적 파일 디렉토리로 사용.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    static_folder=os.path.join(_THIS_DIR, "static"),
    static_url_path=""
)
init_db()  # DB 초기화 (테이블 생성)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

# ── DB 초기화 (테이블 자동 생성) ──
init_db()

# ── 게임 세션 저장소 (메모리) ─────────────────
# { user_id(uuid): {
#       "player":          Player,
#       "items":           list,
#       "hook":            BalanceHook,
#       "turn":            int,
#       "battle":          BattleSession | None,
#       "mid_boss_cleared":bool,
#       "last_event":      str,
#       "db_user_id":      int,         # ★ DB users.id (Phase 2 추가)
#       "nickname":        str,         # ★ 닉네임 캐싱 (Phase 2 추가)
#   } }
GAME_SESSIONS: dict = {}


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def _get_session() -> dict | None:
    uid = session.get("user_id")
    return GAME_SESSIONS.get(uid)


def _get_db_user_id() -> int | None:
    """
    현재 세션의 DB user.id 반환.
    GAME_SESSIONS에 저장된 db_user_id를 우선 사용.
    없으면 None.
    """
    gs = _get_session()
    if not gs:
        return None
    return gs.get("db_user_id")

def _save_battle_to_db(gs: dict, battle, result: dict, winner: str) -> None:
    """
    전투 결과를 DB에 저장. 실패해도 게임은 계속 진행.

    Args:
        gs:     GAME_SESSIONS의 현재 세션 dict
        battle: BattleSession 객체 (이미 종료 처리 끝난 상태)
        result: battle.step() 마지막 반환값
        winner: "player" | "enemy" | "escaped"
    """
    import json

    db_user_id = gs.get("db_user_id")
    if not db_user_id:
        print("[DB] Battle save skipped: no db_user_id in session")
        return

    player = gs["player"]

    # ── 적 목록 직렬화 ──
    enemies_payload = []
    for e in getattr(battle, "enemies", []):
        diff = getattr(e, "difficulty", None) or getattr(e, "_difficulty", None)
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

    # ── 결과 매핑 ──
    db_result = (
        "win"    if winner == "player"
        else "lose"   if winner == "enemy"
        else "escape"
    )

    # ── DB 저장 ──
    try:
        with db_session() as db:
            new_battle = Battle(
                user_id        = db_user_id,
                explore_turn   = gs.get("turn", 0),
                enemies        = json.dumps(enemies_payload, ensure_ascii=False),
                is_boss        = bool(getattr(battle, "is_boss", False)),
                is_multi       = len(getattr(battle, "enemies", [])) > 1,
                result         = db_result,
                turns          = result.get("turn", battle.turn),
                player_job     = player.job,
                player_lv      = player.lv,
                hp_remaining   = float(result.get("player_hp", player.hp)),
                exp_gained     = int(result.get("exp_gained", 0)),
                skills_used    = getattr(battle, "skills_used", 0),
                items_used     = getattr(battle, "items_used", 0),
            )
            db.add(new_battle)
            db.flush()
            print(f"[DB] Battle saved: id={new_battle.id}, user={db_user_id}, "
                  f"result={db_result}, turns={new_battle.turns}, "
                  f"enemies={len(enemies_payload)}")
    except Exception as e:
        # DB 실패해도 게임은 계속 (안전망)
        print(f"[DB] Battle save failed: {e}")

def _player_to_snap(player, items: list) -> EntitySnapshot:
    skills = list(player.skill.learned_skills) if player.skill else []
    return EntitySnapshot(
        name=player.name,
        hp=player.hp,       maxhp=player.maxhp,
        mp=player.mp,       maxmp=player.maxmp,
        stg=player.stg,     arm=player.arm,
        sparm=player.sparm, sp=player.sp,
        luc=player.luc,     lv=player.lv,
        spd=getattr(player, "spd", 10.0),
        learned_skills=skills,
        items=list(items),
        job=getattr(player, "job", ""),  # 직업 패시브 발동용 (전사/마법사/탱커/도적)
    )


def _player_dict(player, items: list) -> dict:
    """플레이어 상태를 JSON 직렬화 가능한 dict로 변환"""
    return {
        "name":   player.name,
        "job":    player.job,
        "lv":     player.lv,
        "hp":     round(player.hp, 1),
        "maxhp":  round(player.maxhp, 1),
        "mp":     round(player.mp, 1),
        "maxmp":  round(player.maxmp, 1),
        "stg":    round(player.stg, 1),
        "arm":    round(player.arm, 1),
        "sp":     round(player.sp, 1),
        "sparm":  round(player.sparm, 1),
        "spd":    round(getattr(player, "spd", 10.0), 1),
        "luc":    round(player.luc, 1),
        "exp":    player.exp,
        "maxexp": player.maxexp,
        "skills": list(player.skill.learned_skills) if player.skill else [],
        "items":  items,
        "pending_points": getattr(player, "pending_points", 0),
    }


# ─────────────────────────────────────────────
# API: 게임 시작
# ─────────────────────────────────────────────

@app.route("/api/new_game", methods=["POST"])
@app.route("/api/newgame",  methods=["POST"])   # ← 별칭 (언더스코어 없는 버전)
def new_game():
    """
    요청: { "name": "용사", "job": "전사" }
    응답: { "ok": true, "player": {...} }
 
    라우트 별칭: /api/new_game = /api/newgame
    프론트엔드 일부에서 경로가 혼재해 양쪽 다 처리.
    """
    data = request.get_json() or {}
    name = data.get("name", "용사").strip() or "용사"
    job  = data.get("job", "전사")

    if job not in ("전사", "마법사", "탱커", "도적"):
        return jsonify({"ok": False, "error": "잘못된 직업입니다."}), 400

    # 플레이어 생성
    player = create_player_by_job(name, job)
    player.skill = Ply_Skill(job=job)
    player.skill.update_skills(1)

    items = [
        "HP_S_potion", "HP_S_potion",
        "HP_M_potion",
        "MP_S_potion", "MP_S_potion",
        "MP_M_potion",
    ]

    hook = BalanceHook(player, items, show_graph=False, verbose=False)

    # 세션 저장
    # ── DB에 User 레코드 생성 (게스트) ──
    # auth_type='guest', email=None, 닉네임=name
    # 같은 닉네임이라도 매번 새 User 생성 (캡스톤 단계에선 단순화).
    # 추후 이메일 인증 추가 시 email 기반 중복 체크 가능.
    db_user_id = None
    try:
        with db_session() as db:
            new_user = User(
                auth_type='guest',
                nickname=name,
                email=None,
                is_active=True,
            )
            db.add(new_user)
            db.flush()       # commit 전에 id 받기
            db_user_id = new_user.id
        print(f"[DB] User created: id={db_user_id}, nickname={name}, job={job}")
    except Exception as e:
        # DB 실패해도 게임은 계속 진행 (안전망)
        # 실서비스에선 여기서 에러 응답하는 게 맞음
        print(f"[DB] User creation failed: {e}")
        db_user_id = None

    # ── 메모리 세션 저장 ──
    uid = str(uuid.uuid4())
    session["user_id"] = uid
    GAME_SESSIONS[uid] = {
        "player":           player,
        "items":            items,
        "hook":             hook,
        "turn":             0,
        "battle":           None,
        "mid_boss_cleared": False,
        "last_event":       None,
        "db_user_id":       db_user_id,    # ★ DB users.id 보관
        "nickname":         name,           # ★ 닉네임 캐싱 (랭킹 표시 등)
    }

    return jsonify({
        "ok":         True,
        "player":     _player_dict(player, items),
        "db_user_id": db_user_id,           # ★ 프론트에 user_id 전달 (디버그용)
        "message":    f"안녕하세요, {name}님! ({job}) 모험을 시작합니다.",
    })

# ─────────────────────────────────────────────
# API: 플레이어 상태
# ─────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def status():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    payload = {
        "ok":     True,
        "player": _player_dict(gs["player"], gs["items"]),
        "turn":   gs["turn"],
        "in_battle": gs["battle"] is not None,
        # ★ user 정보 (Phase 2 추가)
        "user": {
            "db_user_id": gs.get("db_user_id"),
            "nickname":   gs.get("nickname"),
        },
    }

    # 진행 중인 전투가 있으면 전투 상태 페이로드도 포함.
    if gs["battle"] is not None:
        try:
            payload["battle"] = gs["battle"]._state()
        except Exception:
            pass

    return jsonify(payload)

@app.route("/api/levelup/allocate", methods=["POST"])
def levelup_allocate():
    """
    레벨업 시 쌓인 선택 포인트를 스탯에 분배.

    요청: { "allocation": { "stg": 2, "spd": 1 } }
    응답: { "ok": true, "player": {...}, "remaining": 0, "message": "..." }

    규칙:
      - 총 투입 포인트 <= pending_points
      - SPD는 1포인트당 +0.5, 나머지는 +1
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data = request.get_json() or {}
    allocation = data.get("allocation", {})

    if not isinstance(allocation, dict):
        return jsonify({"ok": False, "error": "allocation은 dict여야 합니다."}), 400

    # 정수 변환 (프론트에서 문자열로 올 수 있음)
    clean_alloc = {}
    for stat, pts in allocation.items():
        try:
            clean_alloc[stat] = int(pts)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": f"잘못된 포인트 값: {stat}={pts}"}), 400

    player = gs["player"]
    result = Allocate_Stat_Pooints(player, clean_alloc)

    if not result["ok"]:
        return jsonify({"ok": False, "error": result["msg"],
                        "remaining": result["remaining"]}), 400

    return jsonify({
        "ok":        True,
        "player":    _player_dict(player, gs["items"]),
        "remaining": result["remaining"],
        "message":   result["msg"],
    })

@app.route("/api/ranking", methods=["GET"])
def ranking():
    #점수 기반 랭킹 TOP 20.
    try:
        limit = int(request.args.get("limit", 20)) # 쿼리 파라미터로 랭킹 수 조절 가능 (예: ?limit=10)
    except (ValueError, TypeError):
        limit = 20 # 기본값 20, 잘못된 입력은 무시하고 기본값 사용
    limit = max(1, min(100, limit))   # 1~100 사이로 제한

    try:
        with db_session() as db:
            rankings = get_score_ranking(db, limit=limit)

            # 현재 로그인한 사용자의 랭킹 위치도 같이 반환 (선택)
            my_rank = None
            db_user_id = _get_db_user_id()
            if db_user_id:
                my_rank = get_user_rank_position(db, db_user_id)

        return jsonify({
            "ok":       True,
            "rankings": rankings,
            "my_rank":  my_rank,
            "limit":    limit,
        })

    except Exception as e:
        print(f"[DB] Ranking query failed: {e}")
        return jsonify({"ok": False, "error": "랭킹 조회 실패"}), 500
    
@app.route("/api/ranking/pioneers", methods=["GET"])
def ranking_pioneers():
    # 선구자 랭킹 TOP 10.
    try:
        limit = int(request.args.get("limit", 10)) # 쿼리 파라미터로 랭킹 수 조절 가능 (예: ?limit=5)
    except (ValueError, TypeError):
        limit = 10 # 기본값 10, 잘못된 입력은 무시하고 기본값 사용
    limit = max(1, min(50, limit))

    try:
        with db_session() as db:
            pioneers = get_pioneer_ranking(db, limit=limit)

        return jsonify({
            "ok":       True,
            "pioneers": pioneers,
            "limit":    limit,
        })

    except Exception as e:
        print(f"[DB] Pioneer ranking failed: {e}")
        return jsonify({"ok": False, "error": "선구자 랭킹 조회 실패"}), 500

# ─────────────────────────────────────────────
# API: 탐험 (이벤트 결정)
# ─────────────────────────────────────────────

@app.route("/api/explore", methods=["POST"])
def explore():
    """
    탐험 버튼 누를 때 호출.
    이벤트를 결정하고 필요하면 전투 세션 생성.

    응답:
      { "event": "battle", "enemy": {...}, "battle_state": {...} }
      { "event": "item",   "item": "HP_M_potion" }
      { "event": "rest" }
      { "event": "nothing" }
      { "event": "midboss", "battle_state": {...} }
      { "event": "finalboss", "battle_state": {...} }
      { "event": "gameover" }  ← HP 0
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    player = gs["player"]
    items  = gs["items"]
    turn   = gs["turn"]

    # HP 0 체크
    if player.hp <= 0:
        return jsonify({"ok": True, "event": "gameover"})

    # 전투 중이면 먼저 끝내야 함
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
        # is_boss=True: 중간보스도 도망 불가 (Battlesession에서 escape 차단)
        state  = _start_battle(gs, boss, is_boss=True)
        return jsonify({"ok": True, "event": "midboss",
                        "enemy": {"name": boss.name, "hp": boss.hp},
                        "battle_state": state})

    # ── 일반 이벤트 ──
    gs["turn"] += 1
    rd = randint(1, 20)

    if 1 <= rd <= 12:
        # ── 전투 이벤트 ──
        # 다대일 확률 분배 (rd 1~12 안에서):
        #   1~7  (58%): 1대1 단일 전투
        #   8~10 (25%): 2마리 다대일
        #   11~12(17%): 3마리 다대일
        # 전체 탐험 기준으로는 약 12% (2마리) + 8% (3마리) = 20% 다대일 발생
        # 몬스터 종류: BalanceHook의 레벨별 풀에서 선택
        #   Lv 1+: 고블린, 박쥐
        #   Lv 3+: + 슬라임
        #   Lv 5+: + 골렘
        #   Lv 6+: + 유령
        #   Lv 8+: + 암살자
        # → 콘솔/Flask 단일 출처(BalanceHook._ENEMY_POOL)로 통일됨
        enemy_type = gs["hook"].pick_random_enemy_type()

        if rd <= 7:
            # 1대1
            enemy_snap = gs["hook"].get_enemy(enemy_type)
            enemy      = gs["hook"].make_battle_unit(enemy_snap)
            state      = _start_battle(gs, enemy)
            return jsonify({
                "ok":          True,
                "event":       "battle",
                "enemy":       {"name": enemy.name, "hp": enemy.hp},
                "battle_state": state,
            })
        else:
            # 다대일 (Phase 2): 2마리 또는 3마리
            # 각 마리마다 풀에서 독립 선택 → 혼합 그룹 자연스럽게 발생
            n_enemies = 2 if rd <= 10 else 3
            enemies = []
            for _ in range(n_enemies):
                t = gs["hook"].pick_random_enemy_type()
                snap = gs["hook"].get_enemy(t)
                enemies.append(gs["hook"].make_battle_unit(snap))
            state = _start_battle_multi(gs, enemies, is_boss=False)
            return jsonify({
                "ok":          True,
                "event":       "battle_multi",
                "enemy_count": n_enemies,
                "enemies":     [{"name": e.name, "hp": e.hp} for e in enemies],
                "battle_state": state,
            })

    elif 13 <= rd <= 15:
        # ── 아이템 획득 ──
        # 고정 드랍 풀에서 rarity 가중치로 선택.
        # 이전엔 인벤토리에서 복제하는 버그 → 시작에 없는 종류는 영영 못 얻음.
        # 이제는 모든 포션 종류가 실제로 등장 가능.
        #
        # rarity:
        #   common (자주):  HP_S, MP_S        — 가중 4
        #   uncommon (보통): HP_M, MP_M       — 가중 2
        #   rare (희귀):    HP_L, MP_L        — 가중 1
        from random import choices
        DROP_POOL = [
            ("HP_S_potion", 4), ("MP_S_potion", 4),
            ("HP_M_potion", 2), ("MP_M_potion", 2),
            ("HP_L_potion", 1), ("MP_L_potion", 1),
        ]
        names   = [x[0] for x in DROP_POOL]
        weights = [x[1] for x in DROP_POOL]
        gained  = choices(names, weights=weights, k=1)[0]
        items.append(gained)
        return jsonify({"ok": True, "event": "item", "item": gained,
                        "message": f"[아이템 획득] {gained}을(를) 발견했다!",
                        "player": _player_dict(player, items)})  # UI 즉시 반영용

    elif 16 <= rd <= 17:
        # 휴식
        return jsonify({"ok": True, "event": "rest",
                        "message": "휴식 지점에 도착했다.",
                        "options": [
                            {"key": "heal",  "label": "체력 회복 (maxHP의 1/3)"},
                            {"key": "train", "label": "수련 (경험치 60~80%)"},
                        ]})

    else:
        return jsonify({"ok": True, "event": "nothing",
                        "message": "조용하다... 아무 일도 일어나지 않았다."})


def _start_battle(gs: dict, enemy, is_boss: bool = False) -> dict:
    p_snap = _player_to_snap(gs["player"], gs["items"])
    e_snap = EntitySnapshot.from_enemy(enemy)
    gs["battle"] = BattleSession(
        p_snap,
        enemy=e_snap,
        items=gs["items"],
        is_boss=is_boss,
        enemy_origins=[enemy],
        player_original=gs["player"],   # ★ ATB 이월용 원본 Player
    )
    return gs["battle"]._state(messages=[f"{enemy.name}이(가) 나타났다!"])


def _start_battle_multi(gs: dict, enemies: list, is_boss: bool = False) -> dict:
    p_snap   = _player_to_snap(gs["player"], gs["items"])
    e_snaps  = [EntitySnapshot.from_enemy(e) for e in enemies]
    gs["battle"] = BattleSession(
        p_snap,
        enemies=e_snaps,
        items=gs["items"],
        is_boss=is_boss,
        enemy_origins=list(enemies),
        player_original=gs["player"],   # ★ ATB 이월용 원본 Player
    )

    # 같은 종류는 묶어서 메시지 표시
    counts = {}
    for e in enemies:
        counts[e.name] = counts.get(e.name, 0) + 1
    parts = [f"{n}마리의 {name}" if n > 1 else name for name, n in counts.items()]
    msg = f"⚠ {', '.join(parts)}이(가) 나타났다!"

    return gs["battle"]._state(messages=[msg])

# ─────────────────────────────────────────────
# API: 전투 상태 조회
# ─────────────────────────────────────────────

@app.route("/api/battle/state", methods=["GET"])
def battle_state():
    gs = _get_session()
    if not gs or gs["battle"] is None:
        return jsonify({"ok": False, "error": "전투 중이 아닙니다."}), 404
    return jsonify({"ok": True, **gs["battle"]._state()})


# ─────────────────────────────────────────────
# API: 전투 행동
# ─────────────────────────────────────────────

@app.route("/api/battle/action", methods=["POST"])
def battle_action():
    """
    요청: { "action": "attack" }
          { "action": "skill:강타1" }
          { "action": "item:HP_M_potion" }
          { "action": "escape" }

    응답: BattleSession.step() 반환값 그대로
    """
    gs = _get_session()
    if not gs or gs["battle"] is None:
        return jsonify({"ok": False, "error": "전투 중이 아닙니다."}), 404

    data   = request.get_json() or {}
    action = data.get("action", "").strip()
    if not action:
        return jsonify({"ok": False, "error": "action이 필요합니다."}), 400

    battle = gs["battle"]
    result = battle.step(action)

    # 전투 종료 처리
    # 전투 종료 처리
    if result["done"]:
        player = gs["player"]
        winner = result["winner"]
        battle = gs["battle"]   # ★ DB 저장 후 None 되므로 미리 잡아둠

        # ── 플레이어 상태 동기화 ──
        if winner == "player":
            player.hp = result["player_hp"]
            player.mp = result["player_mp"]
            # 경험치 지급
            lv_obj  = LV_(player)
            exp     = randint(45, 60)
            lv_obj.Get_exp(player, reward_exp=exp)
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

        # ── 중간 보스 클리어 체크 ──
        if battle.enemy.name == "중간 보스" and winner == "player":
            gs["mid_boss_cleared"] = True
            gs["items"].append("HP_L_potion")
            result["messages"].append("보상: HP_L_potion 획득!")

        # ════════════════════════════════════════════════
        # ★ DB Battle 레코드 저장 (Phase 3)
        # ════════════════════════════════════════════════
        _save_battle_to_db(gs, battle, result, winner)

        # 전투 세션 초기화
        gs["battle"] = None
        result["player"] = _player_dict(player, gs["items"])

    return jsonify({"ok": True, **result})
    return jsonify({"ok": True, **result})


# ─────────────────────────────────────────────
# API: 필드 아이템 사용
# ─────────────────────────────────────────────

@app.route("/api/use_item", methods=["POST"])
def use_item():
    """
    요청: { "item": "HP_M_potion" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    if gs["battle"] is not None:
        return jsonify({"ok": False, "error": "전투 중에는 전투 아이템 API를 사용하세요."})

    data      = request.get_json() or {}
    item_name = data.get("item", "")
    player    = gs["player"]
    items     = gs["items"]

    if item_name not in items:
        return jsonify({"ok": False, "error": "해당 아이템이 없습니다."})

    from ai.Battle_Engine import ITEM_META
    meta = ITEM_META.get(item_name)
    if not meta:
        return jsonify({"ok": False, "error": "알 수 없는 아이템입니다."})

    # ITEM_META["amount"]는 (user) -> int 람다. Digital Twin 원칙:
    # game/Item.py의 회복 공식과 동일한 결과를 내도록 호출해서 값 얻음.
    amount = meta["amount"](player) if callable(meta["amount"]) else meta["amount"]

    if meta["stat"] == "hp":
        before     = int(player.hp)
        player.hp  = min(player.maxhp, player.hp + amount)
        items.remove(item_name)
        return jsonify({"ok": True, "message": f"{item_name} 사용 → HP {before} → {int(player.hp)}",
                        "player": _player_dict(player, items)})

    elif meta["stat"] == "mp":
        before     = int(player.mp)
        player.mp  = min(player.maxmp, player.mp + amount)
        items.remove(item_name)
        return jsonify({"ok": True, "message": f"{item_name} 사용 → MP {before} → {int(player.mp)}",
                        "player": _player_dict(player, items)})

    return jsonify({"ok": False, "error": "사용할 수 없는 아이템입니다."})


# ─────────────────────────────────────────────
# API: 휴식 선택
# ─────────────────────────────────────────────

@app.route("/api/rest", methods=["POST"])
def rest():
    """
    요청: { "choice": "heal" | "train" }
    """
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    data   = request.get_json() or {}
    choice = data.get("choice", "")
    player = gs["player"]

    if choice == "heal":
        if player.hp >= player.maxhp:
            return jsonify({"ok": True, "message": "이미 체력이 가득 찼습니다.",
                            "player": _player_dict(player, gs["items"])})
        heal      = min(int(player.maxhp / 3), int(player.maxhp - player.hp))
        player.hp = min(player.maxhp, player.hp + heal)
        return jsonify({"ok": True,
                        "message": f"체력 {heal} 회복! ({int(player.hp)}/{int(player.maxhp)})",
                        "player": _player_dict(player, gs["items"])})

    elif choice == "train":
        ratio   = 0.60 + random() * 0.20
        exp_gain = int(player.maxexp * ratio)
        lv_obj  = LV_(player)
        lv_obj.Get_exp(player, reward_exp=exp_gain)
        gs["hook"].check_level_up()
        return jsonify({"ok": True,
                        "message": f"수련으로 {exp_gain} 경험치 획득!",
                        "player": _player_dict(player, gs["items"])})

    return jsonify({"ok": False, "error": "choice는 heal 또는 train이어야 합니다."})


# ─────────────────────────────────────────────
# 정적 파일 서빙 (웹 UI)
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """
    UI 진입점.
    static_folder("static") 기준으로 'index.html' 서빙.
    파일 시스템 대소문자 구분 환경 (Linux 등)에서도 안전하게 동작하도록
    명시적으로 소문자 파일명 사용. 실제 파일도 반드시 소문자 'index.html'.

    Flask의 app.static_folder를 명시적으로 사용해 작업 디렉토리 의존성 제거.
    """
    static_dir = app.static_folder or "static"
    return send_from_directory(static_dir, "index.html")


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
