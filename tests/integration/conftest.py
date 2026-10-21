"""Destructive fixtures are gated to the dedicated Compose test database only."""

import asyncio
import os
import socket
import subprocess

import httpx
import pytest
import pytest_asyncio
import uvicorn
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import api, bot, worker
from app.auth import create_token
from app.config import settings
from app.db import get_session
from app.models import User

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("Run make test-integration for isolated PostgreSQL and Redis")
    assert make_url(settings.database_url).database == "taskbot_test"
    assert settings.redis_url.endswith("/15")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["alembic", "check"], check=True)


@pytest_asyncio.fixture
async def stack(monkeypatch):
    engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=10)
    worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    worker_factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, processed_updates CASCADE"))
    await redis.flushdb()

    async def sessions():
        async with factory() as session:
            yield session

    api.app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(api, "get_redis", lambda: redis)
    monkeypatch.setattr(api, "Session", factory)
    monkeypatch.setattr(bot, "Session", factory)
    monkeypatch.setattr(worker, "WorkerSession", worker_factory)
    async with factory() as session:
        owner = User(telegram_user_id="1001", first_name="Owner")
        other = User(telegram_user_id="1002", first_name="Other")
        session.add_all([owner, other])
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False),
        base_url=settings.frontend_origin,
        headers={"Origin": settings.frontend_origin},
        cookies={"session": create_token(owner.id)},
    ) as client:
        yield factory, redis, client, owner, other
    api.app.dependency_overrides.clear()
    await redis.aclose()
    await engine.dispose()
    await worker_engine.dispose()


@pytest_asyncio.fixture
async def live_api(stack):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, 5)


def telegram_update(update_id, *, text=None, audio=None):
    message = {
        "message_id": update_id,
        "from": {"id": 1001, "first_name": "Owner"},
        "chat": {"id": 1001, "type": "private"},
    }
    if text is not None:
        message["text"] = text
    if audio is not None:
        message["voice"] = audio
    return {"update_id": update_id, "message": message}


async def next_event(lines, expected=None):
    async with asyncio.timeout(5):
        async for line in lines:
            if line.startswith("event:") and (
                expected is None or line == f"event: {expected}"
            ):
                return line
    raise AssertionError("SSE ended before an event arrived")
