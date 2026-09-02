# -*- coding: utf-8 -*-
"""
test_new_game_session_cleanup.py — /api/new_game 반복 호출 시 GAME_SESSIONS 누수 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_new_game_session_cleanup.py

검증 대상 (code-review 수정 잠금용, app/Game.py의 new_game()):
  같은 브라우저(같은 쿠키)로 "새 게임 시작"을 반복 클릭하면 매번 새
  db_user_id가 발급되어 session["user_id"]가 바뀌는데, 이전 uid를
  GAME_SESSIONS에서 정리하지 않으면 워커 메모리에 죽은 세션이 계속
  쌓인다. new_game()이 old_uid를 GAME_SESSIONS에서 pop하는지 확인.

방식:
  실제 Flask test_client로 /api/new_game을 같은 세션 쿠키로 4번 연속
  호출하고, 매 호출 뒤 GAME_SESSIONS 크기가 1로 유지되는지 확인.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def test_repeated_new_game_no_leak():
    print("\n[반복 /api/new_game → GAME_SESSIONS 크기 고정]")

    from app import create_app
    from app.Shared import GAME_SESSIONS

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    base_size = len(GAME_SESSIONS)

    seen_uids = []
    for i in range(4):
        r = client.post("/api/new_game", json={"name": f"테스터{i}", "job": "전사"})
        body = r.get_json()
        check(f"{i+1}번째 new_game: 200/ok", r.status_code == 200 and body.get("ok") is True,
              f"code={r.status_code}, body={body}")

        with client.session_transaction() as sess:
            uid = sess.get("user_id")
        seen_uids.append(uid)

        cur_size = len(GAME_SESSIONS) - base_size
        check(f"{i+1}번째 new_game 후 GAME_SESSIONS 순증가 == 1 (누수 없음)",
              cur_size == 1, f"delta={cur_size}, uids_so_far={seen_uids}")

    # 매 호출마다 실제로 새 uid가 발급됐는지도 확인 (그렇지 않으면 위 체크가 무의미)
    check("매 호출마다 다른 db_user_id 발급됨", len(set(seen_uids)) == len(seen_uids),
          f"uids={seen_uids}")

    # 정리
    for uid in seen_uids:
        GAME_SESSIONS.pop(uid, None)


def main():
    print("=" * 50)
    print(" /api/new_game GAME_SESSIONS 누수 회귀 테스트")
    print("=" * 50)
    try:
        test_repeated_new_game_no_leak()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print(f"\n  ❌ 테스트 실행 중 예외: {ex}")
        sys.exit(2)
    print("\n" + "=" * 50)
    print(f" 결과: {PASS} 통과 / {FAIL} 실패")
    print("=" * 50)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
