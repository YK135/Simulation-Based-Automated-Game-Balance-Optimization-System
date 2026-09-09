"""
app/__init__.py — Flask 앱 팩토리
"""
from __future__ import annotations

import os
import sys

# ── 경로 설정 (모듈 로드 시점) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
for _sub in ["game", "ai", "core", "interface"]:
    _p = os.path.join(_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, send_from_directory, session, request, jsonify, g
from DB import init_db
from core.ErrorLog import log_error

# Blueprint import — 파일명 대문자 기준 (깃허브 파일명)
from .Game      import game_bp
from .Battle    import battle_bp
from .Inventory import inventory_bp
from .Rest      import rest_bp
from .Ranking   import ranking_bp
from .Map       import map_bp
from .Shared    import GAME_SESSIONS, _persist_session, _get_user_lock, USER_LOCK_TIMEOUT_SECONDS

# ── 마스터 모드(로컬 전용 디버그) ──
# RENDER 환경변수가 있으면(Render 자동 주입 — 배포 환경 감지) MASTER_MODE를
# 실수로 켜도 무조건 꺼진다. 꺼져 있으면 아래에서 블루프린트 자체를
# 등록하지 않으므로 /api/master/* 라우트가 존재하지 않는다(403이 아니라 404).
_MASTER_MODE = (
    os.environ.get("MASTER_MODE", "0") == "1"
    and not os.environ.get("RENDER")
)


def create_app() -> Flask:
    static_dir = os.path.join(_ROOT, "static")

    app = Flask(
        __name__,
        static_folder=static_dir,
        static_url_path=""   # ← index.html이 "css/Base.css", "js/Api.js" 상대경로 사용
    )
    _secret_key = os.environ.get("SECRET_KEY")
    if not _secret_key:
        # ★ 세션 쿠키 서명 키가 없으면 이 값으로 조용히 폴백했었는데, 이 문자열은
        #   소스에 커밋돼 있어 공개된 값 — 이 상태로 배포되면 누구나 SECRET_KEY를
        #   알고 있으니 session["user_id"]를 위조해서 다른 플레이어 세션을 가로챌
        #   수 있음. Render 배포(render.yaml의 generateValue: true)는 안전하지만,
        #   그 외 환경(로컬을 "프로덕션"처럼 돌리거나 다른 호스팅)에서 SECRET_KEY를
        #   깜빡하면 아무 경고 없이 이 취약한 상태로 떠버렸음 — 최소한 로그에는
        #   눈에 띄게 남긴다(로컬 개발 편의를 위해 부팅을 막지는 않음).
        _secret_key = "dev-secret-change-in-prod"
        print(
            "[SECURITY WARNING] SECRET_KEY 환경변수가 설정되지 않아 "
            "하드코드된 기본값을 사용합니다. 이 값은 소스에 공개돼 있어 "
            "세션 위조가 가능합니다 — 실제 배포 전 반드시 SECRET_KEY를 "
            "설정하세요 (.env.example 참고)."
        )
    app.secret_key = _secret_key

    # 세션 쿠키 보안 옵션 — HTTPONLY는 Flask 기본값이 True라 원래도 안전했지만
    # 명시해서 향후 Flask 버전이 기본값을 바꿔도 흔들리지 않게 고정.
    # SECURE(HTTPS에서만 쿠키 전송)는 로컬 http 개발환경에서 켜면 쿠키가 아예
    # 안 붙어서 로그인이 깨지므로, Render가 서비스에 자동 주입하는 RENDER
    # 환경변수로 "HTTPS 뒤에 있다"를 감지해 그때만 기본으로 켠다.
    # 다른 호스팅(HTTPS 종단이지만 RENDER 변수가 없는 경우)은
    # SESSION_COOKIE_SECURE=1을 직접 설정해 덮어쓸 수 있다.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    _secure_default = "1" if os.environ.get("RENDER") else "0"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", _secure_default) == "1"
    if not app.config["SESSION_COOKIE_SECURE"]:
        # ★ SECRET_KEY 폴백은 경고를 찍는데 이쪽은 조용히 꺼진 채로 넘어갔음 —
        #   로컬 http 개발이면 정상이지만, Render가 아닌 다른 HTTPS 호스팅에
        #   올렸는데 SESSION_COOKIE_SECURE=1을 깜빡한 경우도 똑같이 조용히
        #   넘어가 버려서 최소한 부팅 로그에는 남긴다(부팅은 막지 않음 —
        #   로컬 개발에서 매번 뜨는 게 더 시끄러움).
        print(
            "[Session] SESSION_COOKIE_SECURE=off로 부팅 — 로컬 http 개발이면 "
            "정상입니다. HTTPS로 배포한 환경(Render 제외)이라면 "
            "SESSION_COOKIE_SECURE=1을 설정하세요 (.env.example 참고)."
        )

    init_db()

    for bp in (game_bp, battle_bp, inventory_bp, rest_bp, ranking_bp, map_bp):
        app.register_blueprint(bp)

    app.config["MASTER_MODE"] = _MASTER_MODE
    if _MASTER_MODE:
        from .Master import master_bp
        app.register_blueprint(master_bp)
        print("[Master] 마스터 모드 활성화 — 로컬 디버그 전용 API가 열렸습니다 (/api/master/*).")

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    # ── 사용자별 요청 직렬화 ──────────────────────────────────
    # GAME_SESSIONS[uid] 안의 player/battle/inventory/map은 여러 스레드
    # (--threads 8)가 같은 유저의 요청을 동시에 처리하면 경쟁 상태가 생기는
    # 가변 객체다(예: 전투 행동 중복 실행, 수련 경험치 중복 지급, 동시 구매).
    # 프론트의 중복 클릭 방지(state.battleProcessing 등)는 같은 브라우저의
    # "정상적인 빠른 클릭"만 막을 뿐 API 직접 호출이나 여러 탭까지는 못 막으
    # 므로, 같은 uid의 요청은 서버에서 한 번에 하나씩만 처리되도록 직렬화한다.
    # GET(상태 조회 전용, 아무것도 안 바꿈)은 잠글 필요가 없어 제외.
    @app.before_request
    def _acquire_user_lock():
        g._user_lock = None
        if request.method == "GET":
            return None
        uid = session.get("user_id")
        if not uid:
            return None
        lock = _get_user_lock(uid)
        if not lock.acquire(timeout=USER_LOCK_TIMEOUT_SECONDS):
            # 극단적으로만 발생(직전 요청이 예외 없이 응답을 영영 안 끝내는 경우) —
            # 그래도 무한 대기 대신 명확한 오류로 응답한다.
            return jsonify({"ok": False, "error": "요청 처리 중입니다. 잠시 후 다시 시도하세요.",
                            "reason": "locked"}), 423
        g._user_lock = lock
        return None

    @app.teardown_request
    def _release_user_lock(exc=None):
        lock = getattr(g, "_user_lock", None)
        if lock is not None:
            lock.release()

    # 세션 영속화 — 요청마다 현재 워커 메모리에 있는 세션을 Redis+DB에
    # write-through. 라우트마다 저장 호출을 흩뿌리지 않기 위한 전역 훅.
    @app.after_request
    def _persist_game_session(resp):
        # ★ 상태를 바꾸는 라우트는 전부 POST — GET(상태 조회 전용)은 아무것도
        #   안 바뀌므로 매 요청마다 Redis+DB에 다시 쓰는 걸 건너뛴다.
        if request.method == "GET":
            return resp
        uid = session.get("user_id")
        if uid and uid in GAME_SESSIONS:
            try:
                _persist_session(uid, GAME_SESSIONS[uid])
            except Exception as e:
                log_error("session_persist_hook", e)
        return resp

    # ★ 지금까지 서버 쪽 실패는 전부 개별 print()뿐이라 Render 콘솔을 직접
    #   열어보지 않으면 아무도 몰랐음(코드 리뷰에서 지적된 부분) — 여기서
    #   못 잡고 올라온 예외는 최소한 이 핸들러가 log_error()로 남긴다.
    #   route 안에서 이미 try/except로 잡아 처리하는 예외는 각자 그 자리에서
    #   log_error()를 호출해야 함 — 이 핸들러는 "아무도 안 잡은" 마지막 방어선.
    @app.errorhandler(Exception)
    def _handle_uncaught_exception(exc):
        # ★ HTTPException(404/400 등, werkzeug가 정적 파일 404·라우트 없음
        #   같은 정상적인 경우에도 내부적으로 이 클래스를 씀)까지 Exception으로
        #   같이 잡히므로, 그건 그대로 흘려보내야 함 — 안 그러면 흔한 404가
        #   전부 500으로 둔갑하고, 진짜 문제가 아닌 것까지 에러 로그에 쌓인다.
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        log_error("unhandled_request_exception", exc)
        return jsonify({"ok": False, "error": "서버 오류가 발생했습니다."}), 500

    return app