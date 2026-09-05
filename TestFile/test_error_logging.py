# -*- coding: utf-8 -*-
"""
test_error_logging.py — core/ErrorLog.py + 전역 에러 핸들러 회귀 테스트
─────────────────────────────────────────────
프로젝트 루트에서 실행:
    python3 TestFile/test_error_logging.py

검증 대상:
  지금까지 서버 쪽 실패가 전부 print()뿐이라 아무도 몰랐던 문제 — 새로
  추가한 core/ErrorLog.py의 log_error()가 DB(ErrorLog 테이블)에 실제로
  남기는지, 그리고 app/__init__.py에 새로 등록한 전역
  @app.errorhandler(Exception)이:
    1) 라우트 안에서 아무도 못 잡은 예외를 500 JSON으로 정상 변환하고
    2) 그러면서도 흔한 404(정적 파일 없음 등)까지 500으로 둔갑시키지는
       않는지 (HTTPException 예외 처리가 핵심 회귀 포인트).
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


def test_log_error_writes_to_db():
    print("\n[log_error() → ErrorLog 테이블 저장]")
    from DB import init_db, get_session as db_session
    from DB.Models import ErrorLog
    from core.ErrorLog import log_error

    init_db()

    try:
        raise ValueError("테스트용 예외 메시지")
    except ValueError as e:
        log_error("test_context_xyz", e)

    with db_session() as db:
        row = (db.query(ErrorLog)
               .filter_by(context="test_context_xyz")
               .order_by(ErrorLog.id.desc())
               .first())
        check("ErrorLog row가 생성됨", row is not None)
        if row:
            check("error_type이 ValueError", row.error_type == "ValueError", f"got={row.error_type}")
            check("error_message에 원본 메시지 포함",
                  "테스트용 예외 메시지" in (row.error_message or ""), f"got={row.error_message}")
            check("traceback이 비어있지 않음", bool(row.traceback))
        # 정리
        if row:
            db.delete(row)


def test_log_error_never_raises():
    print("\n[log_error() 자체는 절대 예외를 던지지 않음]")
    from DB import get_session as db_session
    from DB.Models import ErrorLog
    from core.ErrorLog import log_error

    try:
        raise RuntimeError("아무 예외")
    except RuntimeError as e:
        try:
            log_error("test_never_raises", e)
            ok = True
        except Exception as ex:
            ok = False
            print(f"     log_error가 예외를 던짐: {ex}")
    check("DB가 없거나 이상해도 log_error는 조용히 넘어감", ok)

    # 정리
    with db_session() as db:
        db.query(ErrorLog).filter_by(context="test_never_raises").delete()


def test_webhook_noop_when_unset():
    print("\n[ERROR_WEBHOOK_URL 미설정 시 웹훅 조용히 스킵]")
    from core.ErrorLog import _notify_webhook

    os.environ.pop("ERROR_WEBHOOK_URL", None)
    try:
        _notify_webhook("ctx", "Type", "msg")
        ok = True
    except Exception as ex:
        ok = False
        print(f"     예외 발생: {ex}")
    check("웹훅 URL 없어도 예외 없이 통과", ok)


def test_global_error_handler():
    print("\n[전역 에러 핸들러 — 못 잡은 예외 → 500 JSON, 404는 그대로]")
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True

    # 테스트 전용 라우트 — 항상 예외를 던짐
    @app.route("/__test_boom__")
    def _boom():
        raise RuntimeError("의도된 테스트 예외")

    client = app.test_client()

    r = client.get("/__test_boom__")
    check("못 잡은 예외 → 500", r.status_code == 500, f"code={r.status_code}")
    body = r.get_json()
    check("응답이 JSON이고 ok=False", body is not None and body.get("ok") is False, f"body={body}")

    r2 = client.get("/api/this-route-does-not-exist")
    check("존재하지 않는 라우트는 여전히 404 (500으로 둔갑 안 함)",
          r2.status_code == 404, f"code={r2.status_code}")

    # 정리 — 이 테스트가 의도적으로 발생시킨 에러 로그만 정확히 골라서 삭제.
    # context="unhandled_request_exception"은 실제 운영 에러도 같은 값을
    # 쓰므로, 이 테스트가 만든 것(요청 경로/메시지로 특정) 외엔 절대 안 지운다.
    from DB import get_session as db_session
    from DB.Models import ErrorLog
    with db_session() as db:
        db.query(ErrorLog).filter_by(
            context="unhandled_request_exception",
            request_path="/__test_boom__",
            error_message="의도된 테스트 예외",
        ).delete()


def main():
    print("=" * 50)
    print(" 에러 로깅 / 전역 에러 핸들러 회귀 테스트")
    print("=" * 50)
    try:
        test_log_error_writes_to_db()
        test_log_error_never_raises()
        test_webhook_noop_when_unset()
        test_global_error_handler()
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
