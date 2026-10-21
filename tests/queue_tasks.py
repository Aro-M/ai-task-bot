"""Blocking fixture task loaded only by disposable integration worker processes."""

from redis import Redis

from app.config import settings
from app.worker import celery_app


@celery_app.task(name="tests.blocking_transcription")
def blocking(started_key: str, release_key: str) -> None:
    with Redis.from_url(settings.redis_url, socket_timeout=20) as redis:
        redis.rpush(started_key, "started")
        redis.blpop(release_key, timeout=15)
        redis.rpush(f"{started_key}:completed", "done")


@celery_app.task(name="tests.synthetic_transcription")
def synthetic_transcription(metrics_key: str, index: int, queued_at: float) -> None:
    import json
    import time

    started = time.perf_counter()
    with Redis.from_url(settings.redis_url, socket_timeout=3) as redis:
        active = redis.incr(f"{metrics_key}:active")
        redis.eval(
            "local n=tonumber(redis.call('GET',KEYS[1]) or '0'); if tonumber(ARGV[1])>n then redis.call('SET',KEYS[1],ARGV[1]) end",
            1,
            f"{metrics_key}:peak",
            active,
        )
        try:
            time.sleep(0.05)  # Fixture provider latency; no paid network call.
        finally:
            redis.decr(f"{metrics_key}:active")
        redis.rpush(
            metrics_key,
            json.dumps(
                {
                    "success": index % 5 != 0,
                    "service_ms": (time.perf_counter() - started) * 1000,
                    "queue_to_finish_ms": (time.time() - queued_at) * 1000,
                }
            ),
        )
