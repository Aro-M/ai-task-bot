"""Private operational snapshot; no public endpoint or user content."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import settings
from app.db import Session
from app.models import Outbox, Task, TranscriptionJob
from app.worker import celery_app


async def database_metrics() -> dict[str, Any]:
    async with Session() as session:
        statuses = dict(
            (
                await session.execute(
                    select(TranscriptionJob.status, func.count()).group_by(
                        TranscriptionJob.status
                    )
                )
            ).all()
        )
        retries, latency, seconds, cost = (
            await session.execute(
                select(
                    func.sum(TranscriptionJob.retry_count),
                    func.avg(TranscriptionJob.latency_ms),
                    func.sum(TranscriptionJob.audio_duration_sec),
                    func.sum(TranscriptionJob.estimated_cost),
                ).where(
                    TranscriptionJob.created_at >= datetime.now(UTC) - timedelta(days=1)
                )
            )
        ).one()
        pending = await session.scalar(
            select(func.count())
            .select_from(Outbox)
            .where(Outbox.delivered_at.is_(None))
        )
        dead = await session.scalar(
            select(func.count())
            .select_from(Outbox)
            .where(Outbox.error_code.is_not(None))
        )
        failed = sum(
            statuses.get(status, 0) for status in ("FAILED", "TIMED_OUT", "DEAD_LETTER")
        )
        finished = failed + statuses.get("COMPLETED", 0)
        created = await session.scalar(select(func.count()).select_from(Task))
        return {
            "tasks_retained": created or 0,
            "job_counts_retained": statuses,
            "terminal_failure_rate_retained": failed / finished if finished else None,
            "retries_last_24h_jobs": retries or 0,
            "average_latency_ms_last_24h_jobs": latency,
            "submitted_audio_seconds_last_24h_jobs": seconds or 0,
            "estimated_usd_last_24h_jobs": cost or 0,
            "outbox_pending": pending or 0,
            "outbox_dead_letters": dead or 0,
        }


async def main() -> None:
    result = await database_metrics()
    async with Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=2,
        socket_connect_timeout=2,
        socket_timeout=3,
    ) as redis:
        result["api_today_utc"] = await redis.hgetall(
            f"api:metrics:{datetime.now(UTC):%Y-%m-%d}"
        )
        requests = int(result["api_today_utc"].get("requests", 0))
        result["api_error_rate_today"] = (
            int(result["api_today_utc"].get("errors", 0)) / requests
            if requests
            else None
        )
        result["provider_today_utc"] = await redis.hgetall(
            f"ai:metrics:{datetime.now(UTC):%Y-%m-%d}"
        )
        attempts = int(result["provider_today_utc"].get("attempts", 0))
        result["provider_http_failure_rate_today"] = (
            int(result["provider_today_utc"].get("http_failures", 0)) / attempts
            if attempts
            else None
        )
        result["broker_depth"] = {
            queue: await redis.llen(queue)
            for queue in ("transcription", "notifications", "celery", "effects")
        }
    result["worker_active_queues"] = await asyncio.to_thread(
        lambda: celery_app.control.inspect(timeout=2).active_queues() or {}
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
