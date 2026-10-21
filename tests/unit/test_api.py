from collections import Counter
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest_asyncio
from redis.exceptions import ConnectionError
from sqlalchemy import select

from app import api
from app.auth import create_token, issue_login_code
from app.config import settings
from app.db import get_session
from app.models import Outbox, Task, TranscriptionJob, User
from app.services import DomainError


class FakeRedis:
    def __init__(self):
        self.counts = Counter()
        self.unavailable = False

    async def eval(self, script, numkeys, key, seconds):
        if self.unavailable:
            raise ConnectionError("offline")
        self.counts[key] += 1
        return self.counts[key]

    async def ping(self):
        if self.unavailable:
            raise ConnectionError("offline")
        return True


@pytest_asyncio.fixture
async def browser(session, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(api, "get_redis", lambda: fake)

    async def test_session():
        yield session

    api.app.dependency_overrides[get_session] = test_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app),
        base_url="http://test",
        headers={"Origin": settings.frontend_origin},
    ) as client:
        yield client, fake
    api.app.dependency_overrides.clear()


async def signed_in(session, client):
    user = User(first_name="Owner", telegram_user_id="123")
    session.add(user)
    await session.commit()
    client.cookies.set("session", create_token(user.id))
    return user


async def test_login_cookie_single_use_logout_and_me(browser, session):
    client, _ = browser
    user = User(first_name="Owner", telegram_user_id="123")
    session.add(user)
    await session.flush()
    code = await issue_login_code(session, user.id)
    await session.commit()
    response = await client.post("/api/auth/login", json={"code": code})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=900" in cookie
    )
    assert (await client.get("/api/auth/me")).json()["id"] == user.id
    assert (
        await client.post("/api/auth/login", json={"code": code})
    ).status_code == 401
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_origin_and_unauthenticated_guards(browser, session):
    client, _ = browser
    assert (await client.get("/api/tasks")).status_code == 401
    await signed_in(session, client)
    for origin in ["https://evil.test", "null", ""]:
        result = await client.post(
            "/api/tasks", json={"title": "blocked"}, headers={"Origin": origin}
        )
        assert result.status_code == 403
    assert (await session.scalars(select(Task))).all() == []


async def test_owner_scoped_crud_filter_pagination_and_validation(browser, session):
    client, _ = browser
    user = await signed_in(session, client)
    other = User(first_name="Other")
    session.add(other)
    await session.flush()
    foreign = Task(user_id=other.id, title="secret", source="DASHBOARD")
    session.add(foreign)
    await session.commit()
    created = await client.post(
        "/api/tasks", json={"title": "  Buy milk  ", "priority": "HIGH"}
    )
    assert created.status_code == 201
    task = created.json()
    assert task["title"] == "Buy milk" and task["user_id"] == user.id
    assert "source_key" not in task
    assert (await client.get(f"/api/tasks/{foreign.id}")).status_code == 403
    assert (
        await client.patch(f"/api/tasks/{foreign.id}", json={"title": "stolen"})
    ).status_code == 403
    assert (await client.delete(f"/api/tasks/{foreign.id}")).status_code == 403
    assert (await client.get(f"/api/tasks/{uuid4()}")).status_code == 404
    for body in [{}, {"title": " "}, {"status": None}, {"unexpected": 1}]:
        invalid = await client.patch(f"/api/tasks/{task['id']}", json=body)
        assert invalid.status_code == 422 and isinstance(invalid.json()["detail"], str)
    completed = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "COMPLETED"}
    )
    assert completed.json()["completed_at"]
    reopened = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "PENDING"}
    )
    assert reopened.json()["completed_at"] is None
    found = (
        await client.get(
            "/api/tasks", params={"search": "MILK", "status": "PENDING", "page_size": 1}
        )
    ).json()
    assert found["total"] == 1 and found["items"][0]["id"] == task["id"]
    assert (await client.get("/api/tasks", params={"search": "%"})).json()["total"] == 0
    assert (
        await client.get("/api/tasks", params={"page_size": 101})
    ).status_code == 422
    assert (await client.delete(f"/api/tasks/{task['id']}")).status_code == 204
    assert (await client.get("/api/tasks")).json()["total"] == 0
    kinds = [x.payload["event"] for x in (await session.scalars(select(Outbox))).all()]
    assert kinds == ["task.created", "task.updated", "task.updated", "task.deleted"]


async def test_rate_limits_and_redis_fail_closed(browser, session):
    client, fake = browser
    for _ in range(5):
        assert (
            await client.post("/api/auth/login", json={"code": "12345678"})
        ).status_code == 401
    assert (
        await client.post("/api/auth/login", json={"code": "12345678"})
    ).status_code == 429
    user = await signed_in(session, client)
    fake.counts[f"api:rate:user:{user.id}"] = 120
    assert (await client.get("/api/tasks")).status_code == 429
    fake.unavailable = True
    assert (await client.get("/api/tasks")).status_code == 503
    assert (await client.get("/api/health")).status_code == 503
    fake.unavailable = False
    assert (await client.get("/api/health")).status_code == 200


async def test_job_ownership_retry_and_success_not_retried(
    browser, session, monkeypatch
):
    client, _ = browser
    user = await signed_in(session, client)
    job = TranscriptionJob(
        user_id=user.id,
        telegram_file_id="private",
        chat_id="private",
        audio_duration_sec=2,
        audio_file_size_bytes=100,
        mime_type="audio/ogg",
        status="FAILED",
        error_code="TEMPORARY",
        model_name="whisper-1",
    )
    session.add(job)
    await session.commit()
    import app.worker

    admission = AsyncMock()
    monkeypatch.setattr(app.worker, "enforce_admission", admission)
    listed = (await client.get("/api/jobs")).json()
    assert listed[0]["id"] == job.id
    assert "telegram_file_id" not in listed[0] and "chat_id" not in listed[0]
    retry = await client.post(f"/api/jobs/{job.id}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "QUEUED" and retry.json()["retry_count"] == 1
    assert retry.json()["error_code"] is None
    admission.assert_awaited_once()
    outbox = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
    assert outbox.payload == {"job_id": job.id}
    assert (await client.post(f"/api/jobs/{job.id}/retry")).status_code == 409
    assert (await client.post(f"/api/jobs/{uuid4()}/retry")).status_code == 404
    job.status = "COMPLETED"
    await session.commit()
    assert (await client.post(f"/api/jobs/{job.id}/retry")).status_code == 409
    job.status, job.retry_count = "FAILED", 3
    await session.commit()
    assert (await client.post(f"/api/jobs/{job.id}/retry")).status_code == 409
    from datetime import UTC, datetime, timedelta

    job.retry_count = 0
    job.created_at = datetime.now(UTC) - timedelta(days=2)
    await session.commit()
    assert (await client.post(f"/api/jobs/{job.id}/retry")).status_code == 409


async def test_deleted_account_invalidates_session(browser, session):
    client, _ = browser
    user = await signed_in(session, client)
    user_id = user.id
    session.add(Task(user_id=user_id, title="erase", source="DASHBOARD"))
    await issue_login_code(session, user_id)
    await session.commit()
    assert (await client.delete("/api/auth/me")).status_code == 204
    assert (await session.scalars(select(Task))).all() == []
    session.expunge_all()
    client.cookies.set("session", create_token(user_id))
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_safe_error_responses_security_headers_and_logs(
    browser, session, monkeypatch, caplog
):
    from sqlalchemy.exc import SQLAlchemyError

    client, _ = browser
    await signed_in(session, client)
    caplog.set_level("INFO", logger="app.api")
    monkeypatch.setattr(
        api, "create_task", AsyncMock(side_effect=RuntimeError("private task text"))
    )
    broken = await client.post(
        "/api/tasks?private=query", json={"title": "private task text"}
    )
    assert broken.status_code == 500
    assert broken.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Unexpected server error",
        "details": {},
        "request_id": broken.headers["x-request-id"],
    }
    assert broken.headers["x-content-type-options"] == "nosniff"
    assert broken.headers["x-frame-options"] == "DENY"
    assert broken.headers["referrer-policy"] == "no-referrer"
    assert broken.headers["cache-control"] == "no-store"
    assert len(broken.headers["x-request-id"]) == 36
    records = [record for record in caplog.records if record.name == "app.api"]
    assert records[-1].request_id == broken.headers["x-request-id"]
    assert records[-1].status == 500
    assert "private" not in str([record.__dict__ for record in records])
    monkeypatch.setattr(
        api, "create_task", AsyncMock(side_effect=SQLAlchemyError("private SQL params"))
    )
    unavailable = await client.post("/api/tasks", json={"title": "x"})
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert unavailable.json()["error"]["message"] == "Database temporarily unavailable"
    monkeypatch.setattr(api, "create_task", AsyncMock(side_effect=TimeoutError()))
    timed_out = await client.post("/api/tasks", json={"title": "x"})
    assert timed_out.status_code == 503
    assert timed_out.json()["error"]["message"] == "Database temporarily unavailable"


async def test_production_cookie_and_hsts(browser, session, monkeypatch):
    client, _ = browser
    user = User(first_name="Owner")
    session.add(user)
    await session.flush()
    code = await issue_login_code(session, user.id)
    await session.commit()
    monkeypatch.setattr(settings, "environment", "production")
    result = await client.post("/api/auth/login", json={"code": code})
    assert result.status_code == 200
    assert "Secure" in result.headers["set-cookie"]
    assert result.headers["strict-transport-security"].startswith("max-age=")


async def test_retry_wrong_owner_and_quota_do_not_schedule(
    browser, session, monkeypatch
):
    import app.worker

    client, _ = browser
    user = await signed_in(session, client)
    other = User(first_name="Other")
    session.add(other)
    await session.flush()
    job = TranscriptionJob(
        user_id=other.id,
        telegram_file_id="private",
        chat_id="private",
        audio_duration_sec=2,
        audio_file_size_bytes=100,
        mime_type="audio/ogg",
        status="FAILED",
        model_name="whisper-1",
    )
    session.add(job)
    await session.commit()
    assert (await client.post(f"/api/jobs/{job.id}/retry")).status_code == 403
    assert (await client.get("/api/jobs")).json() == []
    job.user_id = user.id
    await session.commit()
    monkeypatch.setattr(
        app.worker,
        "enforce_admission",
        AsyncMock(side_effect=DomainError("quota", 429)),
    )
    limited = await client.post(f"/api/jobs/{job.id}/retry")
    assert limited.status_code == 429
    assert job.status == "FAILED" and job.retry_count == 0
    assert (await session.scalars(select(Outbox))).all() == []


def stream_request(user_id):
    request = AsyncMock()
    request.cookies = {"session": create_token(user_id)}
    request.is_disconnected.return_value = False
    return request


async def test_events_ready_keepalive_safe_payload_and_cleanup(session, monkeypatch):
    from unittest.mock import Mock

    user = User(first_name="Owner")
    session.add(user)
    await session.commit()
    pubsub = AsyncMock()
    pubsub.get_message.side_effect = [
        None,
        {"data": "broken JSON"},
        {"data": '{"event":"unknown"}'},
        {"data": '{"event":"task.created","task_id":"t1","transcript":"private"}'},
        ConnectionError("lost"),
    ]
    monkeypatch.setattr(api, "get_redis", lambda: Mock(pubsub=lambda: pubsub))
    event_session = AsyncMock()
    event_session.__aenter__.return_value = event_session
    event_session.scalar.return_value = user.id
    monkeypatch.setattr(api, "Session", lambda: event_session)
    response = await api.events(stream_request(user.id), user)
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks == [
        "event: ready\ndata: {}\n\n",
        ": keepalive\n\n",
        'event: task.created\ndata: {"event": "task.created", "task_id": "t1"}\n\n',
    ]
    pubsub.subscribe.assert_awaited_once_with(f"user:{user.id}:events")
    pubsub.aclose.assert_awaited_once()
    assert response.headers["x-accel-buffering"] == "no"


async def test_events_fail_before_headers_if_redis_unavailable(session, monkeypatch):
    from unittest.mock import Mock

    import pytest
    from fastapi import HTTPException

    user = User(first_name="Owner")
    session.add(user)
    await session.commit()
    pubsub = AsyncMock()
    pubsub.subscribe.side_effect = ConnectionError("offline")
    monkeypatch.setattr(api, "get_redis", lambda: Mock(pubsub=lambda: pubsub))
    with pytest.raises(HTTPException) as error:
        await api.events(stream_request(user.id), user)
    assert error.value.status_code == 503
    pubsub.aclose.assert_awaited_once()


async def test_deleted_account_closes_event_stream(session, monkeypatch):
    from unittest.mock import Mock

    user = User(first_name="Owner")
    session.add(user)
    await session.commit()
    pubsub = AsyncMock()
    monkeypatch.setattr(api, "get_redis", lambda: Mock(pubsub=lambda: pubsub))
    event_session = AsyncMock()
    event_session.__aenter__.return_value = event_session
    event_session.scalar.return_value = None
    monkeypatch.setattr(api, "Session", lambda: event_session)
    response = await api.events(stream_request(user.id), user)
    assert [chunk async for chunk in response.body_iterator] == [
        "event: ready\ndata: {}\n\n"
    ]
    pubsub.get_message.assert_not_awaited()
    pubsub.aclose.assert_awaited_once()


async def test_build_contract_filters_sort_stats_and_error_envelope(browser, session):
    from datetime import UTC, datetime, timedelta

    client, _ = browser
    user = await signed_in(session, client)
    other = User(first_name="Other")
    session.add(other)
    await session.flush()
    now = datetime.now(UTC)
    for index, (source, status, owner) in enumerate(
        [
            ("TELEGRAM_VOICE", "PENDING", user.id),
            ("TELEGRAM_TEXT", "COMPLETED", user.id),
            ("TELEGRAM_VOICE", "IN_PROGRESS", user.id),
            ("TELEGRAM_VOICE", "PENDING", other.id),
        ]
    ):
        session.add(
            Task(
                user_id=owner,
                title=f"Task {index}",
                source=source,
                status=status,
                created_at=now + timedelta(seconds=index),
            )
        )
    await session.commit()
    response = await client.get(
        "/api/tasks?source=telegram_voice&sort=created_at_asc&page_size=1&page=2"
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2 and response.json()["total_pages"] == 2
    assert response.json()["items"][0]["title"] == "Task 2"
    stats = (await client.get("/api/tasks/stats")).json()
    assert stats == {
        "total": 3,
        "by_status": {"PENDING": 1, "IN_PROGRESS": 1, "COMPLETED": 1},
    }
    for path in ["/api/tasks?source=bad", "/api/tasks?sort=bad", "/api/jobs?page=0"]:
        invalid = await client.get(path)
        assert (
            invalid.status_code == 422
            and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        )
        assert invalid.json()["error"]["request_id"] == invalid.headers["x-request-id"]
    missing = await client.get(f"/api/tasks/{uuid4()}")
    assert (
        missing.status_code == 404
        and missing.json()["error"]["code"] == "TASK_NOT_FOUND"
    )


async def test_liveness_ignores_dependencies_and_readiness_checks_workers(browser):
    client, redis = browser
    redis.unavailable = True
    assert (await client.get("/api/health/live")).status_code == 200
    assert (await client.get("/api/health/ready")).status_code == 503
    redis.unavailable = False
    redis.exists = AsyncMock(return_value=0)
    assert (await client.get("/api/health/ready")).status_code == 503
    redis.exists.return_value = 1
    ready = await client.get("/api/health/ready")
    assert ready.status_code == 200 and ready.json()["workers"] == "ok"
    assert redis.exists.await_args.args[0] == "worker:alive:notifications"
