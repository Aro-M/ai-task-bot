from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select

from app.auth import consume_login_code, create_token, issue_login_code, verify_token
from app.config import settings
from app.models import LoginCode, User


def test_signed_session_roundtrip_and_tampering():
    user_id = str(uuid4())
    token = create_token(user_id)
    assert verify_token(token) == user_id
    claims = jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"], audience="dashboard"
    )
    assert claims["exp"] - claims["iat"] == 900
    with pytest.raises(jwt.InvalidTokenError):
        verify_token(token + "changed")
    forged = jwt.encode(
        claims, "attacker-controlled-key-at-least-32-characters", algorithm="HS256"
    )
    with pytest.raises(jwt.InvalidSignatureError):
        verify_token(forged)


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": str(uuid4()), "iat": 1, "exp": 2},
        {
            "sub": "wrong",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        },
        {"sub": str(uuid4()), "iat": datetime.now(UTC)},
    ],
)
def test_expired_missing_or_invalid_claims_rejected(claims):
    claims.update(iss="ai-task-bot", aud="dashboard")
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        verify_token(token)


async def test_login_code_hashed_single_use_and_reissued(session):
    user = User(first_name="Test", telegram_user_id="100")
    session.add(user)
    await session.flush()
    old = await issue_login_code(session, user.id)
    current = await issue_login_code(session, user.id)
    stored = (await session.scalars(select(LoginCode))).all()
    assert len(stored) == 1
    assert len(current) == 8 and current.isdecimal()
    assert stored[0].code_hash != current
    assert await consume_login_code(session, old) is None
    assert await consume_login_code(session, current) == user.id
    assert await consume_login_code(session, current) is None


async def test_expired_code_rejected(session):
    user = User(first_name="Test")
    session.add(user)
    await session.flush()
    code = await issue_login_code(session, user.id)
    stored = await session.scalar(select(LoginCode))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    assert await consume_login_code(session, code) is None


async def test_reissue_and_cross_account_collisions_preserve_transaction(
    session, monkeypatch
):
    from unittest.mock import Mock

    from app import auth

    first = User(first_name="First")
    second = User(first_name="Second")
    session.add_all([first, second])
    await session.flush()
    monkeypatch.setattr(auth.secrets, "randbelow", Mock(side_effect=[1, 1, 2, 2, 3]))
    old = await issue_login_code(session, first.id)
    assert old == "00000001"
    replacement = await issue_login_code(session, first.id)
    assert replacement == "00000002"
    code = await issue_login_code(session, second.id)
    assert code == "00000003"
    assert await consume_login_code(session, replacement) == first.id
    assert await consume_login_code(session, code) == second.id
