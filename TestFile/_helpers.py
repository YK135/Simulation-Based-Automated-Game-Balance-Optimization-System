# -*- coding: utf-8 -*-
"""
_helpers.py — TestFile/*.py가 공유하는 테스트 세션 헬퍼
─────────────────────────────────────────────
코드 리뷰에서 발견된 문제: 여러 테스트 파일이 각자 손으로 GAME_SESSIONS[uid]
딕셔너리 모양과 Flask test_client 주입 로직을 따로 구현하다 보니, 새 세션
필드(battle_node_type/battle_map_layer 등)가 일부 테스트에만 반영되고
다른 테스트는 빠진 채로 남는 drift가 실제로 발생했다. 이 파일 하나로
"세션 딕셔너리 모양"과 "test_client 주입 절차"를 통일한다.

사용:
    from _helpers import make_session_dict, inject_test_session

    gs = make_session_dict(gold=50)                 # 기본 전사 + 빈 인벤토리
    client, uid, store = inject_test_session(gs)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_session_dict(player=None, inventory=None, **overrides) -> dict:
    """app/Game.py의 new_game()이 실제로 만드는 GAME_SESSIONS[uid] 딕셔너리와
    동일한 필드 전체를 기본값으로 채워서 반환한다. 테스트마다 필드를 손으로
    나열하면 실제 세션 모양과 어긋나기 쉬운데(코드 리뷰에서 실제로 발견된
    drift), 이 함수 하나만 거치면 새 필드가 추가돼도 모든 테스트가 자동으로
    최신 모양을 갖는다. player/inventory를 안 주면 기본 전사 + 빈
    인벤토리로 채운다. **overrides로 개별 필드(gold, turn 등)만 덮어쓴다.
    """
    if player is None:
        from game.Player_Class import create_player_by_job
        player = create_player_by_job("테스터", "전사")
    if inventory is None:
        from game.Inventory import Inventory
        inventory = Inventory.new()

    gs = {
        "player":           player,
        "inventory":        inventory,
        "items":            inventory.to_flat_list(),
        "battle":           None,
        "turn":             0,
        "mid_boss_cleared": False,
        "last_event":       None,
        "hook":             None,
        "db_user_id":       None,
        "nickname":         getattr(player, "name", "테스터"),
        "map":              None,
        "chapter":          None,
        "map_turn":         0,
        "pending_node_id":  None,
        "run_id":           None,
        "gold":             100,
        "battle_node_type": None,
        "battle_map_layer": None,
    }
    gs.update(overrides)
    return gs


def inject_test_session(gs: dict, uid: str = "test-uid") -> tuple:
    """create_app() → test_client() → GAME_SESSIONS[uid]=gs 주입 → session
    쿠키 연결까지 마친 (client, uid, GAME_SESSIONS) 반환. "실제 세션이 뭘
    담고 있어야 하는가"(make_session_dict 또는 호출부가 직접 만든 gs)와
    "Flask test_client에 그걸 어떻게 붙이는가"(이 함수)를 분리해서, 세션
    내용이 특이한 테스트(예: 가벼운 StubPlayer를 쓰는 가드 테스트)도 주입
    절차는 동일하게 재사용할 수 있다.
    """
    from app import create_app
    from app.Shared import GAME_SESSIONS

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    GAME_SESSIONS[uid] = gs
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid, GAME_SESSIONS
