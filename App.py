"""
App.py — Flask 진입점
─────────────────────────────────────────────
실제 로직은 app/ 패키지에 분리되어 있음.
  app/Shared.py    — 세션/헬퍼 (GAME_SESSIONS, 3단계 세션 복구, pending_swaps 등)
  app/Game.py      — new_game, status, skills, items, allocate_stat
  app/Battle.py    — battle_state, battle_action
  app/Map.py       — 노드맵 생성/선택/상점  ← 노드맵 전환 시 이 파일을 수정
  app/Inventory.py — use_item, swap
  app/Rest.py      — rest
  app/Ranking.py   — ranking, pioneers
  app/Master.py    — 로컬 전용 디버그 단축 라우트 (MASTER_MODE=1일 때만 등록)
"""
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)