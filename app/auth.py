"""Telegram-issued one-time login codes and short-lived dashboard sessions."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import LoginCode, User

SESSION_SECONDS = 15 * 60
COOKIE_NAME = "session"


def create_token(user_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(seconds=SESSION_SECONDS),
            "iss": "ai-task-bot",
            "aud": "dashboard",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def verify_token(token: str) -> str:
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer="ai-task-bot",
        audience="dashboard",
        options={"require": ["sub", "iat", "exp"]},
    )
    try:
        return str(UUID(claims["sub"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Invalid subject") from exc


async def issue_login_code(session: AsyncSession, user_id: str) -> str:
    # Issuing another code revokes every earlier code for this account.
    await session.execute(
        select(User.id).where(User.id == user_id).with_for_update(key_share=True)
    )
    previous = set(
        await session.scalars(
            select(LoginCode.code_hash).where(LoginCode.user_id == user_id)
        )
    )
    await session.execute(delete(LoginCode).where(LoginCode.user_id == user_id))
    for _ in range(10):
        code = f"{secrets.randbelow(100_000_000):08d}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        if code_hash in previous:
            continue
        try:
            async with session.begin_nested():
                session.add(
                    LoginCode(
                        code_hash=code_hash,
                        user_id=user_id,
                        expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    )
                )
                await session.flush()
        except IntegrityError:
            # A code collision must not roll back the bot's containing transaction.
            continue
        return code
    raise RuntimeError("Unable to allocate login code")


async def consume_login_code(session: AsyncSession, code: str) -> str | None:
    # DELETE RETURNING makes the code single-use across concurrent API replicas.
    result = await session.execute(
        delete(LoginCode)
        .where(
            LoginCode.code_hash == hashlib.sha256(code.encode()).hexdigest(),
            LoginCode.expires_at > datetime.now(UTC),
        )
        .returning(LoginCode.user_id)
    )
    return result.scalar_one_or_none()
