"""Fixture control server for the isolated QA topology; never included in runtime images."""

import secrets

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.engine import make_url

from app import bot, worker
from app.auth import issue_login_code
from app.config import settings
from app.db import Session
from app.models import User
from app.schemas import TaskCreate
from app.services import create_task

if (
    settings.environment != "test"
    or make_url(settings.database_url).database != "taskbot_test"
    or not settings.redis_url.endswith("/15")
):
    raise RuntimeError("Browser fixture server requires isolated test infrastructure")

app = FastAPI(docs_url=None, redoc_url=None)


@app.post("/seed")
async def seed() -> dict:
    telegram_id = secrets.randbelow(900_000_000) + 100_000_000
    async with Session() as session, session.begin():
        owner = User(first_name="QA Owner", telegram_user_id=str(telegram_id))
        other = User(first_name="QA Other")
        session.add_all([owner, other])
        await session.flush()
        code = await issue_login_code(session, owner.id)
        foreign = await create_task(
            session, other.id, TaskCreate(title="Other account private task")
        )
        result = {"code": code, "telegramId": telegram_id, "foreignId": foreign.id}
    async with Redis.from_url(settings.redis_url) as redis:
        async for key in redis.scan_iter("api:rate:login:*"):
            await redis.delete(key)
    return result


async def notification_stub(*args: object) -> None:
    pass


@app.post("/dispatch")
async def dispatch() -> dict:
    # External Telegram delivery is the only stub; DB, queue and event publishing stay real.
    bot.send_message = notification_stub
    await worker.deliver_outbox(100)
    return {"ok": True}
