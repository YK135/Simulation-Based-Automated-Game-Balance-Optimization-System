"""
App.py — Flask 진입점
─────────────────────────────────────────────
실제 로직은 app/ 패키지에 분리되어 있음.
  app/shared.py    — 세션/헬퍼
  app/game.py      — new_game, status, skills, items, allocate_stat
  app/battle.py    — battle_state, battle_action
  app/explore.py   — explore  ← 노드맵 전환 시 이 파일만 수정
  app/inventory.py — use_item, swap_special
  app/rest.py      — rest
  app/ranking.py   — ranking, pioneers
"""
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)