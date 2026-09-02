# -*- coding: utf-8 -*-
"""
test_persist_race.py — _persist_session 동시성 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_persist_race.py

검증 대상 (code-review 수정 잠금용, app/Shared.py의 _persist_session):
  gunicorn --threads N 환경에서 같은 user_id로 여러 요청이 동시에 첫
  _persist_session 호출을 하면(PlayerState row가 아직 없는 상태), 두 스레드
  모두 row=None을 보고 INSERT를 시도할 수 있다 — PK(user_id) 충돌 시
  IntegrityError를 조용히 삼키지 않고 UPDATE로 재시도해서, 최종적으로
  정확히 1개의 row만 남고 어떤 스레드의 쓰기도 유실되지 않아야 한다.

방식:
  실제 DB(get_session/PlayerState)를 대상으로 동일 user_id에 대해
  N개 스레드가 서로 다른 turn 값으로 동시에 _persist_session을 호출하고,
  최종 row 개수 == 1, 예외 없음, turn 값이 그 중 하나로 정상 반영됐는지 확인.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import threading

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


def _make_gs(turn):
    from game.Player_Class import create_player_by_job
    from game.Inventory import Inventory

    player = create_player_by_job("동시성테스터", "전사")
    inv = Inventory.new()
    return {
        "player": player,
        "inventory": inv,
        "map": None,
        "chapter": None,
        "turn": turn,
        "map_turn": 0,
        "mid_boss_cleared": False,
        "gold": 100,
        "run_id": None,
        "pending_node_id": None,
        "battle_node_type": None,
        "battle_map_layer": None,
    }


def test_concurrent_first_persist():
    print("\n[_persist_session 동시 최초 INSERT 경쟁 (PK 충돌 → UPDATE 재시도)]")

    from DB import init_db, get_session as db_session
    from DB.Models import User, PlayerState
    from app.Shared import _persist_session

    init_db()

    # 실제 FK를 만족하는 User row 생성 (테스트 전용)
    with db_session() as db:
        user = User(auth_type="guest", nickname="동시성테스터", email=None, is_active=True)
        db.add(user)
        db.flush()
        user_id = user.id

    uid = str(user_id)
    N = 15
    errors = []

    def worker(i):
        try:
            _persist_session(uid, _make_gs(turn=i))
        except Exception as ex:
            errors.append(ex)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check(f"{N}개 스레드 동시 persist: 예외 0건", len(errors) == 0, f"errors={errors}")

    with db_session() as db:
        rows = db.query(PlayerState).filter_by(user_id=user_id).all()
        check("최종 row 개수 == 1 (중복 INSERT 없음)", len(rows) == 1,
              f"count={len(rows)}")
        if rows:
            check("row.turn이 0~N-1 중 하나로 정상 반영됨",
                  0 <= rows[0].turn < N, f"turn={rows[0].turn}")

    # 정리
    with db_session() as db:
        db.query(PlayerState).filter_by(user_id=user_id).delete()
        db.query(User).filter_by(id=user_id).delete()


def main():
    print("=" * 50)
    print(" _persist_session 동시성 회귀 테스트")
    print("=" * 50)
    try:
        test_concurrent_first_persist()
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
