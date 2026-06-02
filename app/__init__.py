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

from flask import Flask, send_from_directory
from DB import init_db

# Blueprint import — 파일명 대문자 기준 (깃허브 파일명)
from .Game      import game_bp
from .Battle    import battle_bp
from .Inventory import inventory_bp
from .Rest      import rest_bp
from .Ranking   import ranking_bp
from .Map       import map_bp


def create_app() -> Flask:
    static_dir = os.path.join(_ROOT, "static")

    app = Flask(
        __name__,
        static_folder=static_dir,
        static_url_path=""   # ← index.html이 "css/Base.css", "js/Api.js" 상대경로 사용
    )
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    init_db()

    for bp in (game_bp, battle_bp, inventory_bp, rest_bp, ranking_bp, map_bp):
        app.register_blueprint(bp)

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    return app