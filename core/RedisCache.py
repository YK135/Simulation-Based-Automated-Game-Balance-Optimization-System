"""
core/RedisCache.py — 세션 백업용 얇은 Redis 래퍼
─────────────────────────────────────────────
REDIS_URL 환경변수가 없거나 접속에 실패하면 조용히 no-op으로 동작한다.
(Redis는 "있으면 빠른 2차 캐시" 역할 — 없어도 게임은 DB만으로 계속 진행됨)

사용:
    from core.RedisCache import redis_get, redis_set

    redis_set(f"session:{uid}", payload_dict)
    data = redis_get(f"session:{uid}")   # 없으면 None
"""
from __future__ import annotations

import json
import os

_SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7일 — 진짜 durable layer는 DB, Redis는 캐시일 뿐

_client = None
_client_checked = False


def _get_client():
    """지연 초기화 — 최초 호출 시 1회만 연결 시도. 실패하면 이후 항상 None."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        client = redis.Redis.from_url(url, socket_connect_timeout=1.5, socket_timeout=1.5)
        client.ping()
        _client = client
    except Exception as e:
        print(f"[Redis] 연결 실패 — DB 폴백으로만 동작: {e}")
        _client = None
    return _client


def redis_get(key: str) -> dict | None:
    client = _get_client()
    if not client:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        print(f"[Redis] get 실패({key}): {e}")
        return None


def redis_set(key: str, value: dict) -> None:
    client = _get_client()
    if not client:
        return
    try:
        client.set(key, json.dumps(value, ensure_ascii=False), ex=_SESSION_TTL_SECONDS)
    except Exception as e:
        print(f"[Redis] set 실패({key}): {e}")


def redis_delete(key: str) -> None:
    client = _get_client()
    if not client:
        return
    try:
        client.delete(key)
    except Exception as e:
        print(f"[Redis] delete 실패({key}): {e}")
