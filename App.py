"""
app.py — Flask 진입점
─────────────────────────────────────────────
터미널 기반 Main.py를 REST API로 교체.
BattleSession.py가 전투 상태를 들고 있고,
브라우저 요청 하나 → API 응답 하나 구조.

엔드포인트:
  POST /api/new_game          — 게임 시작 (이름, 직업)
  GET  /api/status            — 현재 플레이어 상태 (스킬/아이템 목록 포함)
  POST /api/explore           — 탐험 (다음 이벤트 결정)
  GET  /api/battle/state      — 현재 전투 상태
  POST /api/battle/action     — 전투 행동 (공격/스킬/아이템/도망)
  POST /api/use_item          — 필드에서 아이템 사용
  POST /api/rest              — 휴식 (heal/mp/train)
  GET  /                      — 테스트용 웹 UI (static/index.html)

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
from game.Lv           import LV_
from game.Item         import Item_
from ai.Battle_Engine  import EntitySnapshot
from ai.Simulator      import MonsterFactory
from core.Balance_Hook import BalanceHook
from ai.Battlesession import BattleSession   # Flask용 전투 세션


# ── Flask 앱 ─────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

# ── 게임 세션 저장소 (메모리) ─────────────────
# { user_id: { "player": Player, "items": list, "hook": BalanceHook,
#              "turn": int, "battle": BattleSession | None,
#              "mid_boss_cleared": bool } }
GAME_SESSIONS: dict = {}


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def _get_session() -> dict | None:
    uid = session.get("user_id")
    return GAME_SESSIONS.get(uid)


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
    }


# ─────────────────────────────────────────────
# API: 게임 시작
# ─────────────────────────────────────────────

@app.route("/api/new_game", methods=["POST"])
def new_game():
    """
    요청: { "name": "용사", "job": "전사" }
    응답: { "ok": true, "player": {...} }
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
    ]

    hook = BalanceHook(player, items, show_graph=False, verbose=False)

    # 세션 저장
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
    }

    return jsonify({
        "ok":     True,
        "player": _player_dict(player, items),
        "message": f"안녕하세요, {name}님! ({job}) 모험을 시작합니다.",
    })


# ─────────────────────────────────────────────
# API: 플레이어 상태
# ─────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def status():
    gs = _get_session()
    if not gs:
        return jsonify({"ok": False, "error": "게임 세션이 없습니다."}), 404

    return jsonify({
        "ok":     True,
        "player": _player_dict(gs["player"], gs["items"]),
        "turn":   gs["turn"],
        "in_battle": gs["battle"] is not None,
    })


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
        return jsonify({"ok": True, "event": "gameover",
                        "player": _player_dict(player, gs["items"])})

    # 전투 중이면 먼저 끝내야 함
    if gs["battle"] is not None:
        return jsonify({"ok": False, "error": "전투 중입니다. 먼저 전투를 완료하세요."})

    # ── 보스 체크 ──
    if turn >= 50:
        boss  = Make_FinalBoss(player.lv)
        state = _start_battle(gs, boss, is_boss=True)
        return jsonify({"ok": True, "event": "finalboss",
                        "enemy": {"name": boss.name, "hp": boss.hp},
                        "battle_state": state,
                        "player": _player_dict(player, gs["items"])})

    if turn == 25 and not gs["mid_boss_cleared"]:
        cached = gs["hook"]._get_cached_monsters("고블린")
        base   = cached.get("normal", (None, None))[0] if cached else None
        boss   = Make_MidBoss(player.lv, base)
        state  = _start_battle(gs, boss, is_boss=True)
        return jsonify({"ok": True, "event": "midboss",
                        "enemy": {"name": boss.name, "hp": boss.hp},
                        "battle_state": state,
                        "player": _player_dict(player, gs["items"])})

    # ── 일반 이벤트 ──
    gs["turn"] += 1
    rd = randint(1, 20)

    if 1 <= rd <= 12:
        # 전투 이벤트
        enemy_type = "고블린" if random() < 0.5 else "박쥐"
        enemy_snap = gs["hook"].get_enemy(enemy_type)
        enemy      = gs["hook"].make_battle_unit(enemy_snap)
        state      = _start_battle(gs, enemy)
        return jsonify({
            "ok":          True,
            "event":       "battle",
            "enemy":       {"name": enemy.name, "hp": enemy.hp},
            "battle_state": state,
            "player":      _player_dict(player, gs["items"]),
        })

    elif 13 <= rd <= 15:
        # 아이템 획득
        gained = items[randint(0, len(items) - 1)]
        items.append(gained)
        return jsonify({"ok": True, "event": "item", "item": gained,
                        "message": f"[아이템 획득] {gained}을(를) 발견했다!",
                        "player": _player_dict(player, gs["items"])})

    elif 16 <= rd <= 17:
        # 휴식
        return jsonify({"ok": True, "event": "rest",
                        "message": "휴식 지점에 도착했다.",
                        "options": [
                            {"key": "heal",  "label": "체력 회복 (maxHP의 1/3)"},
                            {"key": "train", "label": "수련 (경험치 60~80%)"},
                        ],
                        "player": _player_dict(player, gs["items"])})

    else:
        return jsonify({"ok": True, "event": "nothing",
                        "message": "조용하다... 아무 일도 일어나지 않았다.",
                        "player": _player_dict(player, gs["items"])})


def _start_battle(gs: dict, enemy, is_boss: bool = False) -> dict:
    """전투 세션 생성 후 초기 상태 반환"""
    p_snap = _player_to_snap(gs["player"], gs["items"])
    e_snap = EntitySnapshot.from_enemy(enemy)
    gs["battle"] = BattleSession(p_snap, e_snap, gs["items"], is_boss=is_boss)
    return gs["battle"]._state(messages=[f"{enemy.name}이(가) 나타났다!"])


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

    # ── [요청 1] 세션 재고 동기화 ─────────────────────
    # BattleSession.__init__에서 self.items = list(items)로 별개 리스트를
    # 만들기 때문에, 전투 중 아이템 사용 결과를 매 step마다 세션에 반영해야
    # 전투 종료 후에도 인벤토리 수량이 맞게 유지됨.
    gs["items"] = list(battle.items)

    # 전투 종료 처리
    if result["done"]:
        player = gs["player"]
        winner = result["winner"]

        if winner == "player":
            # HP/MP 동기화
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

        elif winner == "escaped":
            player.hp = result["player_hp"]
            player.mp = result["player_mp"]

        # 중간 보스 클리어 체크
        if gs["battle"].enemy.name == "중간 보스" and winner == "player":
            gs["mid_boss_cleared"] = True
            gs["items"].append("HP_L_potion")
            result["messages"].append("보상: HP_L_potion 획득!")

        # ── [요청 2] 전투 로그 저장 — 분석 파이프라인 연결 ──
        # BalanceHook.after_battle()을 호출하면:
        #   1) LOG_Manager.save_player_log() — data/Player_LOG/에 JSON 저장
        #   2) 패배 시 FeedbackEngine 실행 (AI 복기 분석)
        # 이로써 2학기 BehaviorAnalyzer/FeedbackEngine이
        # Flask 경로로 플레이한 데이터도 분석할 수 있게 됨.
        try:
            battle_result = battle.to_battle_result()
            gs["hook"].after_battle(battle_result)
        except Exception as e:
            print(f"[WARN] after_battle 호출 실패: {e}")

        gs["battle"] = None  # 전투 세션 초기화
        result["player"] = _player_dict(player, gs["items"])

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

    if meta["stat"] == "hp":
        before     = int(player.hp)
        amount     = meta["amount"](player)  # 동적 계산
        player.hp  = min(player.maxhp, player.hp + amount)
        items.remove(item_name)
        return jsonify({"ok": True,
                        "message": f"{item_name} 사용 → HP {before} → {int(player.hp)} (+{amount})",
                        "player": _player_dict(player, items)})

    elif meta["stat"] == "mp":
        before     = int(player.mp)
        amount     = meta["amount"](player)  # 동적 계산
        player.mp  = min(player.maxmp, player.mp + amount)
        items.remove(item_name)
        return jsonify({"ok": True,
                        "message": f"{item_name} 사용 → MP {before} → {int(player.mp)} (+{amount})",
                        "player": _player_dict(player, items)})

    return jsonify({"ok": False, "error": "사용할 수 없는 아이템입니다."})


# ─────────────────────────────────────────────
# API: 휴식 선택
# ─────────────────────────────────────────────

@app.route("/api/rest", methods=["POST"])
def rest():
    """
    요청: { "choice": "heal" | "mp" | "train" }

    heal:  HP 최대치의 1/3 회복
    mp:    MP 최대치의 1/3 회복 (테스트용 — 본게임에선 탐험 이벤트로만)
    train: 랜덤 경험치 획득 (maxexp의 60~80%)
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

    elif choice == "mp":
        if player.mp >= player.maxmp:
            return jsonify({"ok": True, "message": "이미 마나가 가득 찼습니다.",
                            "player": _player_dict(player, gs["items"])})
        mp_gain   = min(int(player.maxmp / 3), int(player.maxmp - player.mp))
        player.mp = min(player.maxmp, player.mp + mp_gain)
        return jsonify({"ok": True,
                        "message": f"마나 {mp_gain} 회복! ({int(player.mp)}/{int(player.maxmp)})",
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

    return jsonify({"ok": False, "error": "choice는 heal, mp, train 중 하나여야 합니다."})


# ─────────────────────────────────────────────
# 정적 파일 서빙 (웹 UI)
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)