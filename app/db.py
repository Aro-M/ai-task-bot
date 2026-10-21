from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

CONNECT_ARGS = (
    {"timeout": 3, "command_timeout": 5}
    if settings.database_url.startswith("postgresql+asyncpg://")
    else {}
)
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args=CONNECT_ARGS,
    **({"pool_timeout": 3, "pool_size": 5, "max_overflow": 10} if CONNECT_ARGS else {}),
)
Session = async_sessionmaker(engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection: object, record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with Session() as session:
        yield session
