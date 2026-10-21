"""Durable effects are stored in Outbox; Redis carries only identifiers."""

import json

from redis.asyncio import Redis

from app.config import settings


def encode_event(payload: dict) -> str:
    allowed = {
        key: payload[key]
        for key in ("event", "task_id", "user_id", "job_id")
        if key in payload
    }
    if not isinstance(allowed.get("event"), str):
        raise ValueError("Missing event name")
    return json.dumps(allowed, separators=(",", ":"))


def job_id_from_payload(payload: dict) -> str:
    from uuid import UUID

    value = payload.get("job_id")
    if not isinstance(value, str):
        raise ValueError("Invalid job payload")
    return str(UUID(value))


async def publish_event(user_id: str, payload: dict) -> None:
    async with Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=2,
        socket_timeout=3,
    ) as redis:
        await redis.publish(f"user:{user_id}:events", encode_event(payload))
