"""Fixed-window rate limiting per actor and bucket. Redis-backed when Celery/Redis is in use, in-memory otherwise."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger


class _MemoryLimiter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        self.lock = threading.Lock()

    def hit(self, key: str, window: int) -> int:
        bucket = f"{key}:{int(time.time() // window)}"
        with self.lock:
            self.counts[bucket] += 1
            if len(self.counts) > 50_000:
                self.counts.clear()
            return self.counts[bucket]


class _RedisLimiter:
    def __init__(self, url: str) -> None:
        import redis

        self.client = redis.Redis.from_url(url, socket_timeout=0.5)

    def hit(self, key: str, window: int) -> int:
        bucket = f"rl:{key}:{int(time.time() // window)}"
        pipe = self.client.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, window + 5)
        return int(pipe.execute()[0])


_limiter: _MemoryLimiter | _RedisLimiter | None = None


def _get() -> _MemoryLimiter | _RedisLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = _RedisLimiter(s.redis_url) if s.job_backend == "celery" else _MemoryLimiter()
    return _limiter


def reset_rate_limits() -> None:
    global _limiter
    _limiter = None


def enforce(actor_key: str, bucket: str, limit: int | None = None, window: int = 60) -> None:
    limit = limit or get_settings().user_rate_limit
    try:
        count = _get().hit(f"{bucket}:{actor_key}", window)
    except Exception:  # noqa: BLE001 - limiter outage must not take the API down; log and allow
        get_logger("readbit.ratelimit").warning("rate limiter unavailable", extra={"bucket": bucket})
        return
    if count > limit:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "You're going a little fast. Please wait a moment and try again.",
            status_code=429,
            details={"retry_after_seconds": window},
        )
