from functools import partial
from types import SimpleNamespace

import aiohttp
import aioresponses.core
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.models import Base


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


@pytest.fixture(autouse=True)
def aiohttp_mock_compatibility(monkeypatch):
    # aioresponses 0.7.9 predates aiohttp 3.14's required stream_writer argument.
    monkeypatch.setattr(
        aioresponses.core,
        "ClientResponse",
        partial(aiohttp.ClientResponse, stream_writer=SimpleNamespace(output_size=0)),
    )


@pytest.fixture(autouse=True)
def disable_live_task_parser(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-only-key")
    monkeypatch.setattr(settings, "task_parser_enabled", False)
