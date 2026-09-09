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
import time

_SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7일 — 진짜 durable layer는 DB, Redis는 캐시일 뿐

# ★ 예전엔 최초 연결 시도 결과와 무관하게 _client_checked=True를 먼저 박아둬서,
#   REDIS_URL은 설정돼 있는데 부팅 시점에 Redis가 아직 안 떠 있었다거나 일시적인
#   네트워크 문제로 첫 연결이 실패하면 그 워커는 프로세스가 죽을 때까지 영원히
#   재시도를 안 하고 DB 폴백만 탔다. 실패했을 때만 쿨다운을 두고 그 이후엔
#   다시 시도하도록 변경 — 연결에 성공하면(위쪽 _client is not None 체크로)
#   더 이상 재시도 비용 없이 그대로 재사용된다.
_RETRY_COOLDOWN_SECONDS = 30

_client = None
_client_checked = False
_last_attempt_at = 0.0


def _get_client():
    """지연 초기화. 연결 성공 시 그대로 재사용, 실패 시 쿨다운 후 재시도."""
    global _client, _client_checked, _last_attempt_at
    if _client is not None:
        return _client

    url = os.environ.get("REDIS_URL")
    if not url:
        return None  # 설정 자체가 없음 — 재시도 대상 아님

    now = time.monotonic()
    if _client_checked and (now - _last_attempt_at) < _RETRY_COOLDOWN_SECONDS:
        return None  # 최근에 실패함 — 쿨다운 중에는 재접속 시도 안 함

    _client_checked = True
    _last_attempt_at = now
    try:
        import redis
        client = redis.Redis.from_url(url, socket_connect_timeout=1.5, socket_timeout=1.5)
        client.ping()
        _client = client
    except Exception as e:
        print(f"[Redis] 연결 실패 — {_RETRY_COOLDOWN_SECONDS}초 후 재시도, "
              f"그동안은 DB 폴백으로만 동작: {e}")
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
