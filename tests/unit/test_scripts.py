from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models import LoginCode, Outbox, User
from scripts import cleanup, evaluate_ai, register_webhook


def test_evaluation_dataset_passes_without_provider():
    assert evaluate_ai.evaluate()["accuracy"] == 1


def test_evaluation_detects_lost_description(monkeypatch):
    extract = evaluate_ai.extract_fields

    def lose_description(text, now):
        fields = extract(text, now)
        fields.pop("description", None)
        return fields

    monkeypatch.setattr(evaluate_ai, "extract_fields", lose_description)
    with pytest.raises(AssertionError):
        evaluate_ai.evaluate()


async def test_cleanup_preserves_pending_and_recent_effects(session, monkeypatch):
    from contextlib import asynccontextmanager

    user = User(first_name="Owner")
    session.add(user)
    await session.flush()
    now = datetime.now(UTC)
    session.add_all(
        [
            LoginCode(
                code_hash="expired",
                user_id=user.id,
                expires_at=now - timedelta(minutes=1),
            ),
            LoginCode(
                code_hash="valid",
                user_id=user.id,
                expires_at=now + timedelta(minutes=5),
            ),
            Outbox(
                user_id=user.id,
                kind="event",
                payload={},
                delivered_at=now - timedelta(days=31),
            ),
            Outbox(user_id=user.id, kind="transcribe", payload={}),
            Outbox(user_id=user.id, kind="event", payload={}, delivered_at=now),
        ]
    )
    await session.commit()

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(cleanup, "Session", factory)
    assert await cleanup.cleanup(False) == {"login_codes": 1, "outbox": 1}
    assert len((await session.scalars(select(Outbox))).all()) == 3
    await session.rollback()
    assert await cleanup.cleanup(True) == {"login_codes": 1, "outbox": 1}
    assert len((await session.scalars(select(Outbox))).all()) == 2
    assert await session.get(LoginCode, "expired") is None


async def test_registration_validates_before_external_action(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(register_webhook, "Bot", mock)
    for url in ["http://example.org/telegram/webhook", "https://example.org/wrong"]:
        with pytest.raises(SystemExit):
            await register_webhook.register(url)
    mock.assert_not_called()


@pytest.mark.parametrize("failed_cleanup", [False, True])
async def test_benchmark_settles_requests_and_checks_rate_limited_cleanup(
    monkeypatch, failed_cleanup
):
    import httpx

    from scripts import benchmark

    pending = 2
    deletes = 0

    async def handle(request):
        nonlocal pending, deletes
        if request.method == "POST":
            pending -= 1
            if pending == 1:
                if failed_cleanup:
                    return httpx.Response(201, json=[])
                raise httpx.ConnectError("fixture")
            return httpx.Response(201, json={"id": "owned-fixture"})
        assert pending == 0
        deletes += 1
        if deletes == 1 or failed_cleanup:
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(204)

    sleep = AsyncMock()
    monkeypatch.setattr(benchmark.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        result = await benchmark.benchmark(client, count=2)
    assert result["created"] == 1 and result["errors"] == ["transport_or_response"]
    assert result["cleanup_failures"] == int(failed_cleanup)
    assert deletes == (3 if failed_cleanup else 2)
    sleep.assert_awaited_with(60)


async def test_database_metrics_are_aggregate_and_content_free(session, monkeypatch):
    from contextlib import asynccontextmanager

    from app.models import TranscriptionJob
    from scripts import metrics

    user = User(first_name="private-name")
    session.add(user)
    await session.flush()
    session.add(
        TranscriptionJob(
            user_id=user.id,
            telegram_file_id="private-file",
            chat_id="private-chat",
            audio_duration_sec=60,
            audio_file_size_bytes=100,
            mime_type="audio/ogg",
            model_name="whisper-1",
            status="COMPLETED",
            retry_count=2,
            estimated_cost=0.006,
            latency_ms=100,
        )
    )
    await session.commit()

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(metrics, "Session", factory)
    result = await metrics.database_metrics()
    assert result["job_counts_retained"] == {"COMPLETED": 1}
    assert result["retries_last_24h_jobs"] == 2
    assert result["estimated_usd_last_24h_jobs"] == 0.006
    assert result["average_latency_ms_last_24h_jobs"] == 100
    assert "private" not in str(result)


def test_deployment_plan_validates_scope_and_orders_migration_before_restart(tmp_path):
    from scripts.deploy import deployment_plan

    (tmp_path / ".env").write_text("# operator fixture, no credentials\n")
    plan = deployment_plan("staging", "a" * 40, tmp_path, "ghcr.io/example/taskbot")
    assert all(
        "taskbot-staging" in command and str(tmp_path / ".env") in command
        for command in plan
    )
    assert plan[2][-6:] == ["stop", "api", "bot", "worker", "dispatcher", "scheduler"]
    assert plan[3][-4:] == ["run", "--rm", "--no-deps", "migrate"]
    assert "--no-build" in plan[4] and "--wait" in plan[4]
    for environment, tag, prefix in [
        ("invalid", "a" * 40, "ghcr.io/example/taskbot"),
        ("production", "main; command", "ghcr.io/example/taskbot"),
        ("staging", "a" * 40, "evil.example/image"),
    ]:
        with pytest.raises(ValueError):
            deployment_plan(environment, tag, tmp_path, prefix)


@pytest.mark.parametrize("ready", [True, False])
def test_deployment_dry_run_and_apply_use_scoped_commands_only(
    tmp_path, monkeypatch, capsys, ready
):
    import contextlib
    import io
    import sys
    from unittest.mock import Mock

    from scripts import deploy

    (tmp_path / ".env").write_text("# fixture\n")
    argv = [
        "deploy",
        "--environment",
        "staging",
        "--tag",
        "b" * 40,
        "--directory",
        str(tmp_path),
        "--image-prefix",
        "ghcr.io/example/taskbot",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    run = Mock()
    monkeypatch.setattr(deploy.subprocess, "run", run)
    deploy.main()
    run.assert_not_called()
    assert (
        not (tmp_path / ".release-sha").exists()
        and '"apply": false' in capsys.readouterr().out
    )
    response = io.StringIO(
        '{"status": "ready"}' if ready else '{"status": "unavailable"}'
    )
    response.status = 200
    monkeypatch.setattr(
        deploy, "urlopen", lambda *args, **kwargs: contextlib.nullcontext(response)
    )
    monkeypatch.setattr(sys, "argv", argv + ["--apply"])
    if ready:
        deploy.main()
        assert (tmp_path / ".release-sha").read_text().strip() == "b" * 40
    else:
        with pytest.raises(RuntimeError, match="readiness"):
            deploy.main()
        assert not (tmp_path / ".release-sha").exists()
    assert run.call_count == 5
    assert run.call_args.kwargs["env"]["TASKBOT_IMAGE_TAG"] == "b" * 40
