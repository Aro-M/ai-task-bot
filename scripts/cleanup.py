"""Purge expired codes and old delivered outbox metadata; dry-run by default."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.db import Session
from app.models import LoginCode, Outbox


async def cleanup(apply: bool = False) -> dict[str, int]:
    now = datetime.now(UTC)
    counts = {}
    async with Session() as session, session.begin():
        for model, condition in (
            (LoginCode, LoginCode.expires_at < now),
            (Outbox, Outbox.delivered_at < now - timedelta(days=30)),
        ):
            counts[model.__tablename__] = (
                await session.scalar(
                    select(func.count()).select_from(model).where(condition)
                )
                or 0
            )
            if apply:
                await session.execute(delete(model).where(condition))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    print(
        {"applied": arguments.apply, "eligible": asyncio.run(cleanup(arguments.apply))}
    )
