import asyncio
import json
import statistics
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from app import api, bot, worker
from app.auth import create_token
from app.models import Outbox, ProcessedUpdate, Task, TranscriptionJob, User
from app.schemas import TaskCreate
from app.services import create_task

from .conftest import next_event, telegram_update

pytestmark = pytest.mark.integration


async def test_postgres_crud_and_owner_boundaries(stack):
    factory, redis, client, owner, other = stack
    response = await client.post("/api/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    task_id = response.json()["id"]
    async with factory() as session:
        saved = await session.get(Task, task_id)
        assert saved.title == "Buy milk" and saved.user_id == owner.id
    response = await client.patch(
        f"/api/tasks/{task_id}", json={"status": "IN_PROGRESS"}
    )
    assert response.status_code == 200
    async with factory() as session:
        assert (await session.get(Task, task_id)).status == "IN_PROGRESS"
    client.cookies.set("session", create_token(other.id))
    for method in ("GET", "PATCH", "DELETE"):
        kwargs = {"json": {"title": "stolen"}} if method == "PATCH" else {}
        assert (
            await client.request(method, f"/api/tasks/{task_id}", **kwargs)
        ).status_code == 403
    client.cookies.set("session", create_token(owner.id))
    assert (await client.delete(f"/api/tasks/{task_id}")).status_code == 204
    async with factory() as session:
        assert await session.get(Task, task_id) is None


async def test_concurrent_telegram_redelivery_creates_one_task(stack, monkeypatch):
    factory, *_ = stack
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    update = telegram_update(500, text="Only create me once")
    results = await asyncio.gather(*(bot.handle_update(update) for _ in range(12)))
    assert sum(results) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 1
        assert await session.scalar(select(func.count()).select_from(Outbox)) == 2


async def test_two_worker_deliveries_lock_one_transcription(stack, monkeypatch):
    factory, _, _, owner, _ = stack
    async with factory() as session:
        job = TranscriptionJob(
            user_id=owner.id,
            telegram_file_id="file",
            chat_id="1001",
            audio_duration_sec=2,
            audio_file_size_bytes=1000,
            mime_type="audio/ogg",
            model_name="whisper-1",
        )
        session.add(job)
        await session.commit()
    monkeypatch.setattr(worker, "download_audio", AsyncMock())
    monkeypatch.setattr(worker, "inspect_audio", AsyncMock(return_value=2.0))
    monkeypatch.setattr(worker, "convert_audio", AsyncMock())
    transcribe = AsyncMock(return_value=("Call Anna tomorrow", "en"))
    monkeypatch.setattr(worker, "transcribe_audio", transcribe)
    await asyncio.gather(*(worker.process_job(job.id) for _ in range(5)))
    await worker.process_job(job.id)
    transcribe.assert_awaited_once()
    async with factory() as session:
        assert (await session.get(TranscriptionJob, job.id)).status == "COMPLETED"
        assert await session.scalar(select(func.count()).select_from(Task)) == 1


@pytest.mark.parametrize("operation", ["retry", "delete_account"])
async def test_worker_completion_does_not_deadlock_account_operations(
    stack, monkeypatch, operation
):
    factory, _, client, owner, _ = stack
    async with factory() as session:
        job = TranscriptionJob(
            user_id=owner.id,
            telegram_file_id="file",
            chat_id="1001",
            audio_duration_sec=2,
            audio_file_size_bytes=1000,
            mime_type="audio/ogg",
            model_name="whisper-1",
        )
        session.add(job)
        await session.commit()
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(_path):
        entered.set()
        await release.wait()
        return "Call Anna", "en"

    monkeypatch.setattr(worker, "download_audio", AsyncMock())
    monkeypatch.setattr(worker, "inspect_audio", AsyncMock(return_value=2.0))
    monkeypatch.setattr(worker, "convert_audio", AsyncMock())
    monkeypatch.setattr(worker, "transcribe_audio", provider)
    processing = asyncio.create_task(worker.process_job(job.id))
    await asyncio.wait_for(entered.wait(), 2)
    async with factory() as session:
        assert (await session.get(TranscriptionJob, job.id)).status == "PROCESSING"
        assert (
            await session.scalar(
                select(Outbox.id).where(
                    Outbox.payload["event"].as_string() == "transcription.started"
                )
            )
            is not None
        )
    request = asyncio.create_task(
        client.post(f"/api/jobs/{job.id}/retry")
        if operation == "retry"
        else client.delete("/api/auth/me")
    )
    await asyncio.sleep(0.1)
    assert not request.done()
    release.set()
    _, response = await asyncio.wait_for(asyncio.gather(processing, request), 4)
    assert response.status_code == (409 if operation == "retry" else 204)
    async with factory() as session:
        if operation == "retry":
            assert (await session.get(TranscriptionJob, job.id)).status == "COMPLETED"
            assert await session.scalar(select(func.count()).select_from(Task)) == 1
        else:
            assert await session.get(User, owner.id) is None
            assert not (await session.scalars(select(Task))).all()


async def test_stale_queue_recovery_does_not_deadlock_account_deletion(
    stack, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory, _, client, owner, _ = stack
    async with factory() as session:
        session.add(
            TranscriptionJob(
                user_id=owner.id,
                telegram_file_id="file",
                chat_id="1001",
                audio_duration_sec=2,
                audio_file_size_bytes=1000,
                mime_type="audio/ogg",
                model_name="whisper-1",
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await session.commit()
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedRecoverySession(AsyncSession):
        async def scalar(self, statement, *args, **kwargs):
            result = await super().scalar(statement, *args, **kwargs)
            if statement.column_descriptions[0].get("entity") is Outbox:
                entered.set()
                await release.wait()
            return result

    monkeypatch.setattr(
        worker,
        "WorkerSession",
        async_sessionmaker(
            factory.kw["bind"],
            class_=PausedRecoverySession,
            expire_on_commit=False,
        ),
    )
    recovery = asyncio.create_task(worker.recover_queued_jobs())
    await asyncio.wait_for(entered.wait(), 2)
    deletion = asyncio.create_task(client.delete("/api/auth/me"))
    await asyncio.sleep(0.1)
    assert not deletion.done()
    release.set()
    _, response = await asyncio.wait_for(asyncio.gather(recovery, deletion), 4)
    assert response.status_code == 204
    async with factory() as session:
        assert await session.get(User, owner.id) is None
        assert not (await session.scalars(select(Outbox))).all()


async def test_redis_down_is_controlled_and_outbox_is_retained(stack, monkeypatch):
    factory, _, client, owner, _ = stack
    broken = AsyncMock()
    broken.eval.side_effect = ConnectionError("test outage")
    broken.ping.side_effect = ConnectionError("test outage")
    monkeypatch.setattr(api, "get_redis", lambda: broken)
    assert (await client.get("/api/tasks")).status_code == 503
    assert (await client.get("/api/health")).status_code == 503
    async with factory() as session:
        await create_task(
            session, owner.id, TaskCreate(title="Committed despite bus outage")
        )
        await session.commit()
    monkeypatch.setattr(
        worker, "publish_event", AsyncMock(side_effect=ConnectionError())
    )
    await worker.deliver_outbox()
    async with factory() as session:
        row = await session.scalar(select(Outbox))
        assert row.delivered_at is None and row.attempts > 0
        assert await session.scalar(select(func.count()).select_from(Task)) == 1


async def test_database_failure_is_controlled(stack):
    from app.db import get_session

    async def broken_session():
        from sqlalchemy.exc import OperationalError

        raise OperationalError("not logged", {}, Exception("private connection"))
        yield

    api.app.dependency_overrides[get_session] = broken_session
    response = await stack[2].get("/api/tasks")
    assert response.status_code == 503
    assert "private" not in response.text


async def test_account_deletion_cascades_private_data(stack):
    factory, _, client, owner, _ = stack
    assert (
        await client.post("/api/tasks", json={"title": "private"})
    ).status_code == 201
    assert (await client.delete("/api/auth/me")).status_code == 204
    async with factory() as session:
        assert await session.get(User, owner.id) is None
        assert not (await session.scalars(select(Task))).all()
        assert not (await session.scalars(select(Outbox))).all()


async def test_live_sse_owner_isolation_and_delivery_latency(
    stack, live_api, monkeypatch
):
    factory, redis, _, owner, other = stack
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    async with httpx.AsyncClient(
        cookies={"session": create_token(owner.id)},
        timeout=5,
    ) as browser:
        async with browser.stream("GET", f"{live_api}/api/events") as response:
            assert response.status_code == 200
            lines = response.aiter_lines()
            assert await anext(lines) == "event: ready"
            assert await anext(lines) == "data: {}"
            assert await anext(lines) == ""
            await asyncio.sleep(0.05)
            # An idle SSE connection must not pin an API database connection.
            assert factory.kw["bind"].pool.checkedout() == 0
            await redis.publish(
                f"user:{other.id}:events",
                json.dumps({"event": "task.deleted", "task_id": "foreign"}),
            )
            await bot.handle_update(telegram_update(600, text="Live task"))
            started = time.perf_counter()
            await worker.deliver_outbox()
            assert await next_event(lines) == "event: task.created"
            data = json.loads((await anext(lines)).removeprefix("data: "))
            latency = (time.perf_counter() - started) * 1000
            async with factory() as session:
                task = await session.get(Task, data["task_id"])
                assert task.title == "Live task" and task.user_id == owner.id
            assert "title" not in data and "user_id" not in data
            print(f"SSE delivery including outbox dispatch: {latency:.2f} ms")


async def test_benchmark_100_concurrent_creations(stack):
    factory, _, client, *_ = stack
    latencies = []

    async def request(index):
        started = time.perf_counter()
        result = await client.post("/api/tasks", json={"title": f"Load {index}"})
        latencies.append((time.perf_counter() - started) * 1000)
        assert result.status_code == 201

    load_started = time.perf_counter()
    await asyncio.gather(*(request(index) for index in range(100)))
    load_elapsed = time.perf_counter() - load_started
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 100
    query_latencies = []
    async with factory() as session:
        owner = (await session.scalar(select(Task))).user_id
        for _ in range(20):
            started = time.perf_counter()
            rows = (
                await session.scalars(
                    select(Task)
                    .where(Task.user_id == owner)
                    .order_by(Task.created_at.desc())
                    .limit(20)
                )
            ).all()
            query_latencies.append((time.perf_counter() - started) * 1000)
            assert len(rows) == 20
    print(
        json.dumps(
            {
                "scenario": "20 tenant task-list queries, 100-row table, warm local PostgreSQL",
                "average_ms": round(statistics.mean(query_latencies), 2),
                "p95_ms": round(sorted(query_latencies)[18], 2),
            }
        )
    )
    print(
        json.dumps(
            {
                "scenario": "100 concurrent creations, in-process HTTP transport + real PostgreSQL/Redis",
                "created": 100,
                "errors": 0,
                "creations_per_second": round(100 / load_elapsed, 2),
                "average_ms": round(statistics.mean(latencies), 2),
                "p95_ms": round(sorted(latencies)[94], 2),
            }
        )
    )


async def test_live_events_are_not_blocked_by_saturated_transcription_workers(
    stack, tmp_path
):
    import subprocess
    import sys
    from uuid import uuid4

    _, redis, client, owner, _ = stack
    assert (
        worker.celery_app.conf.task_routes["app.worker.dispatch_outbox"]["queue"]
        == "notifications"
    )
    suffix = uuid4().hex
    voice_queue, effects_queue = f"voice-{suffix}", f"effects-{suffix}"
    started_key, release_key = f"started:{suffix}", f"release:{suffix}"
    processes, logs = [], []
    try:
        for role, queue, pool, concurrency in (
            ("voice", voice_queue, "prefork", "2"),
            ("effects", effects_queue, "solo", "1"),
        ):
            log = (tmp_path / f"{role}.log").open("w+")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "app.worker.celery_app",
                        "worker",
                        "--include=tests.queue_tasks",
                        f"--queues={queue}",
                        f"--pool={pool}",
                        f"--concurrency={concurrency}",
                        f"--hostname={role}-{suffix}@localhost",
                        "--loglevel=WARNING",
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        names = [f"voice-{suffix}@localhost", f"effects-{suffix}@localhost"]
        ready = set()
        async with asyncio.timeout(30):
            while True:
                pong = await asyncio.to_thread(
                    worker.celery_app.control.ping, destination=names, timeout=1
                )
                ready.update(name for response in pong for name in response)
                if ready.issuperset(names):
                    break
                assert all(process.poll() is None for process in processes)
        for _ in range(2):
            worker.celery_app.send_task(
                "tests.blocking_transcription",
                args=[started_key, release_key],
                queue=voice_queue,
            )
        async with asyncio.timeout(4):
            while await redis.llen(started_key) != 2:
                await asyncio.sleep(0.05)
        async with redis.pubsub() as events:
            assert await redis.llen(f"{started_key}:completed") == 0
            await events.subscribe(f"user:{owner.id}:events")
            response = await client.post(
                "/api/tasks", json={"title": "Text must stay live"}
            )
            assert response.status_code == 201
            worker.celery_app.send_task(
                "app.worker.dispatch_outbox", queue=effects_queue
            )
            async with asyncio.timeout(4):
                while True:
                    message = await events.get_message(
                        ignore_subscribe_messages=True, timeout=1
                    )
                    if message:
                        assert (
                            json.loads(message["data"])["task_id"]
                            == response.json()["id"]
                        )
                        break
            assert await redis.llen(release_key) == 0
            assert await redis.llen(f"{started_key}:completed") == 0
        await redis.rpush(release_key, "release", "release")
        async with asyncio.timeout(5):
            while await redis.llen(f"{started_key}:completed") != 2:
                await asyncio.sleep(0.02)
        metrics_key = f"benchmark:{suffix}"
        bench_started = time.perf_counter()
        for index in range(20):
            worker.celery_app.send_task(
                "tests.synthetic_transcription",
                args=[metrics_key, index, time.time()],
                queue=voice_queue,
            )
        async with asyncio.timeout(10):
            while await redis.llen(metrics_key) != 20:
                await asyncio.sleep(0.02)
        elapsed = time.perf_counter() - bench_started
        samples = [json.loads(item) for item in await redis.lrange(metrics_key, 0, -1)]
        assert sum(item["success"] for item in samples) == 16
        assert int(await redis.get(f"{metrics_key}:peak")) == 2
        print(
            json.dumps(
                {
                    "scenario": "real Celery prefork, 20 synthetic 50ms provider calls, concurrency 2",
                    "jobs_per_second": round(20 / elapsed, 2),
                    "simulated_success_rate": 0.8,
                    "simulated_failure_rate": 0.2,
                    "observed_concurrency": 2,
                    "average_service_ms": round(
                        statistics.mean(item["service_ms"] for item in samples), 2
                    ),
                    "p95_queue_to_finish_ms": round(
                        sorted(item["queue_to_finish_ms"] for item in samples)[18], 2
                    ),
                }
            )
        )
    finally:
        await redis.rpush(release_key, "release", "release")
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                await asyncio.to_thread(process.wait, timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=2)
        for log in logs:
            log.close()


@pytest.mark.parametrize("recover", [True, False])
async def test_durable_infrastructure_retry_lifecycle(stack, monkeypatch, recover):
    factory, _, _, owner, _ = stack
    async with factory() as session, session.begin():
        job = TranscriptionJob(
            user_id=owner.id,
            telegram_file_id="fixture",
            chat_id="1001",
            audio_duration_sec=2,
            audio_file_size_bytes=1000,
            mime_type="audio/ogg",
            model_name="whisper-1",
        )
        session.add(job)
    monkeypatch.setattr(
        worker, "download_audio", AsyncMock(side_effect=RuntimeError("infra"))
    )
    with pytest.raises(RuntimeError):
        await worker.process_job(job.id)
    if recover:
        monkeypatch.setattr(worker, "download_audio", AsyncMock())
        monkeypatch.setattr(worker, "inspect_audio", AsyncMock(return_value=2.0))
        monkeypatch.setattr(worker, "convert_audio", AsyncMock())
        monkeypatch.setattr(
            worker, "transcribe_audio", AsyncMock(return_value=("Call Anna", "en"))
        )
        await worker.process_job(job.id)
        await worker.process_job(job.id)
    else:
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await worker.process_job(job.id)
        await worker.process_job(job.id)
    async with factory() as session:
        saved = await session.get(TranscriptionJob, job.id)
        assert saved.status == ("COMPLETED" if recover else "DEAD_LETTER")
        assert saved.retry_count == (1 if recover else 3)
        assert saved.error_code == (None if recover else "dead_letter")
        assert await session.scalar(select(func.count()).select_from(Task)) == int(
            recover
        )


async def test_global_voice_admission_is_atomic_across_users(stack, monkeypatch):
    from app.services import DomainError

    factory, _, _, owner, other = stack
    monkeypatch.setattr(worker.settings, "global_queued_jobs_limit", 1)

    async def admit(user_id):
        try:
            async with factory() as session, session.begin():
                user = await session.get(User, user_id)
                await worker.enforce_admission(session, user)
                session.add(
                    TranscriptionJob(
                        user_id=user.id,
                        telegram_file_id="fixture",
                        chat_id="fixture",
                        audio_duration_sec=2,
                        audio_file_size_bytes=1000,
                        mime_type="audio/ogg",
                        model_name="whisper-1",
                    )
                )
            return True
        except DomainError as exc:
            assert exc.status_code == 429
            return False

    assert sorted(await asyncio.gather(admit(owner.id), admit(other.id))) == [
        False,
        True,
    ]
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(TranscriptionJob))
            == 1
        )


async def test_outbox_migration_roundtrip_preserves_existing_data(stack):
    import subprocess

    factory, _, client, *_ = stack
    assert (
        await client.post("/api/tasks", json={"title": "Retain across migration"})
    ).status_code == 201
    await bot.handle_update(telegram_update(990, text="/help"))
    for revision in ("0001", "head"):
        direction = "downgrade" if revision == "0001" else "upgrade"
        await asyncio.to_thread(
            subprocess.run, ["alembic", direction, revision], check=True
        )
    async with factory() as session:
        assert (await session.scalar(select(Task))).title == "Retain across migration"
        row = await session.scalar(select(Outbox))
        assert row.payload["event"] == "task.created" and row.available_at is not None
        receipt = await session.get(ProcessedUpdate, 990)
        assert receipt is not None and receipt.created_at is not None
        assert (
            receipt.user_id is None
        )  # Downgrade intentionally drops admission history.
    assert not await bot.handle_update(telegram_update(990, text="Must not replay"))


async def test_bot_admission_is_atomic_and_account_erasure_keeps_replay_guard(
    stack, monkeypatch
):
    factory, _, client, *_ = stack
    monkeypatch.setattr(bot, "BOT_MESSAGES_PER_MINUTE", 3)
    updates = [telegram_update(i, text=f"Burst task {i}") for i in range(100, 112)]
    assert all(
        await asyncio.wait_for(
            asyncio.gather(*(bot.handle_update(value) for value in updates)), 10
        )
    )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 3
        assert (
            await session.scalar(select(func.count()).select_from(ProcessedUpdate))
            == 12
        )
        notices = list(
            await session.scalars(
                select(Outbox.payload).where(Outbox.kind == "notification")
            )
        )
        assert sum("Too many messages" in row["text"] for row in notices) == 1
    assert (await client.delete("/api/auth/me")).status_code == 204
    async with factory() as session:
        receipts = list(await session.scalars(select(ProcessedUpdate)))
        assert len(receipts) == 12 and all(row.user_id is None for row in receipts)
    assert not await bot.handle_update(updates[0])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
