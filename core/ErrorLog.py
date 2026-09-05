"""
core/ErrorLog.py — 서버 쪽 실패를 실제로 남기는 곳
─────────────────────────────────────────────
지금까지 모든 except 블록이 print()로만 남기고 넘어가서, Render 콘솔을
직접 열어보지 않는 한 어떤 실패도 눈에 띄지 않았다. log_error() 하나만
거치면: (1) 기존처럼 콘솔에도 남고, (2) DB의 ErrorLog 테이블에 영구히
쌓이고(scripts/view_errors.py로 조회), (3) ERROR_WEBHOOK_URL 환경변수가
설정돼 있으면 Discord/Slack 호환 웹훅으로 즉시 알림까지 간다.

REDIS_URL/SECRET_KEY와 같은 패턴 — 뭘 설정 안 해도 앱은 그대로 동작하고,
설정하면 그만큼 더 눈에 띄게 알려준다.

사용:
    from core.ErrorLog import log_error

    try:
        위험한_작업()
    except Exception as e:
        log_error("feedback_generation", e)
"""
from __future__ import annotations

import os
import traceback as _traceback
import urllib.request
import json


def _get_request_context() -> tuple:
    """Flask 요청 컨텍스트 안이면 (path, method, user_id) 반환, 아니면 (None, None, None).
    요청 컨텍스트 밖(백그라운드 스레드 등)에서 호출돼도 죽지 않아야 함."""
    try:
        from flask import request, session, has_request_context
        if not has_request_context():
            return None, None, None
        uid = session.get("user_id")
        return request.path, request.method, (int(uid) if uid and str(uid).isdigit() else None)
    except Exception:
        return None, None, None


def _notify_webhook(context: str, error_type: str, error_message: str) -> None:
    """ERROR_WEBHOOK_URL이 설정돼 있으면 Discord/Slack 호환 웹훅으로 알림.
    미설정이거나 전송 실패해도 조용히 넘어간다 — 알림이 안 가는 것 때문에
    실제 에러 로깅(DB 저장)까지 막혀선 안 됨."""
    url = os.environ.get("ERROR_WEBHOOK_URL")
    if not url:
        return
    try:
        payload = json.dumps({
            "content": f"🚨 [{context}] {error_type}: {error_message[:300]}"
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        print(f"[ErrorLog] 웹훅 전송 실패: {e}")


def log_error(context: str, exc: Exception) -> None:
    """서버 쪽 실패를 콘솔+DB(+웹훅)에 남긴다. 이 함수 자체는 절대 예외를
    다시 던지지 않는다 — 에러 로깅 코드가 원래 하려던 작업을 망가뜨리면
    본말전도이므로, 로깅 실패는 항상 조용히 삼킨다."""
    error_type = type(exc).__name__
    error_message = str(exc)
    tb = _traceback.format_exc()

    print(f"[Error:{context}] {error_type}: {error_message}\n{tb}")

    try:
        path, method, user_id = _get_request_context()
        from DB import get_session as db_session
        from DB.Models import ErrorLog

        with db_session() as db:
            db.add(ErrorLog(
                context=context[:64],
                error_type=error_type[:128],
                error_message=error_message,
                traceback=tb,
                request_path=path,
                request_method=method,
                user_id=user_id,
            ))
    except Exception as e:
        print(f"[ErrorLog] DB 저장 실패: {e}")

    _notify_webhook(context, error_type, error_message)
