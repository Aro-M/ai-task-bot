import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import audio, bot, worker
from app.events import encode_event, job_id_from_payload
from app.models import Outbox, Task, TranscriptionJob, User
from app.schemas import TaskCreate
from app.services import DomainError


@pytest_asyncio.fixture
async def pipeline(session, monkeypatch):
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(bot, "Session", factory)
    monkeypatch.setattr(worker, "WorkerSession", factory)
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    return factory


def update(number=1, **message):
    return {
        "update_id": number,
        "message": {
            "from": {"id": 123, "first_name": "Test"},
            "chat": {"id": 123, "type": "private"},
            **message,
        },
    }


def voice():
    return {
        "file_id": "telegram-file",
        "duration": 3,
        "file_size": 1024,
        "mime_type": "audio/ogg",
    }


@pytest.mark.parametrize(
    "duration,size,mime",
    [
        (0, 1, "audio/ogg"),
        (121, 1, "audio/ogg"),
        (float("nan"), 1, "audio/ogg"),
        (True, 1, "audio/ogg"),
        (2, 0, "audio/ogg"),
        (2, 21 * 1024**2, "audio/ogg"),
        (2, 1, "text/plain"),
        (2, 1, []),
        (2, None, "audio/ogg"),
    ],
)
def test_metadata_rejects_invalid_audio(duration, size, mime):
    with pytest.raises(audio.AudioError):
        audio.validate_metadata(duration, size, mime)


@pytest.mark.parametrize("mime", sorted(audio.MIME_TYPES))
def test_metadata_accepts_supported_audio(mime):
    audio.validate_metadata(1, 1, mime)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.ogg",
        "/voice.ogg",
        "voice/../secret.ogg",
        "https://evil.test/a.ogg",
        "file.ogg?token=x",
        "voice\\a.ogg",
        None,
    ],
)
def test_telegram_path_rejects_traversal_and_external_urls(path):
    with pytest.raises(audio.AudioError):
        audio.telegram_file_path(path)


def test_job_payload_and_events_never_publish_text():
    value = str(uuid4())
    assert job_id_from_payload({"job_id": value}) == value
    for invalid in ({}, {"job_id": "broken"}, {"job_id": 4}):
        with pytest.raises(ValueError):
            job_id_from_payload(invalid)
    event = json.loads(
        encode_event({"event": "task.created", "task_id": value, "text": "private"})
    )
    assert event == {"event": "task.created", "task_id": value}
    with pytest.raises(ValueError):
        encode_event({})


async def test_text_ingestion_is_idempotent_and_durable(pipeline):
    assert await bot.handle_update(update(text="Call Anna tomorrow"))
    assert not await bot.handle_update(update(text="Call Anna tomorrow"))
    async with pipeline() as session:
        tasks = (await session.scalars(select(Task))).all()
        assert len(tasks) == 1 and tasks[0].source == "TELEGRAM_TEXT"
        rows = (await session.scalars(select(Outbox))).all()
        assert {row.kind for row in rows} == {"event", "notification"}
        assert (
            next(row for row in rows if row.kind == "notification")
            .payload["text"]
            .startswith("✅")
        )


async def test_distinct_telegram_updates_are_not_dropped(pipeline):
    assert await bot.handle_update(update(100, text="First task"))
    assert await bot.handle_update(update(101, text="Second task"))
    async with pipeline() as session:
        assert set(await session.scalars(select(Task.title))) == {
            "First task",
            "Second task",
        }


async def test_long_telegram_text_preserves_message_in_description(pipeline):
    text = "Review the report and call Anna with the final details. " * 20
    await bot.handle_update(update(text=text))
    async with pipeline() as session:
        task = await session.scalar(select(Task))
        assert task.description == text.strip()
        assert 1 <= len(task.title) <= 300


async def test_text_route_uses_shared_parser_fields(pipeline, monkeypatch):
    parsed = TaskCreate(
        title="Call Anna",
        description="Discuss the report",
        due_date=datetime(2026, 10, 22, 14, tzinfo=UTC),
        priority="HIGH",
    )
    monkeypatch.setattr(bot, "parse_task", AsyncMock(return_value=parsed))

    await bot.handle_update(update(text="Please call Anna tomorrow at 14:00."))

    bot.parse_task.assert_awaited_once_with("Please call Anna tomorrow at 14:00.")
    async with pipeline() as session:
        task = await session.scalar(select(Task))
        assert (task.title, task.description, task.due_date, task.priority) == (
            "Call Anna",
            "Discuss the report",
            datetime(2026, 10, 22, 14, tzinfo=UTC),
            "HIGH",
        )


async def test_text_route_does_not_create_task_for_conversation(pipeline, monkeypatch):
    monkeypatch.setattr(bot, "parse_task", AsyncMock(return_value=None))

    await bot.handle_update(update(text="How are you today?"))

    bot.parse_task.assert_awaited_once_with("How are you today?")
    async with pipeline() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        row = await session.scalar(select(Outbox).where(Outbox.kind == "notification"))
        assert "I didn't create a task" in row.payload["text"]


@pytest.mark.parametrize(
    "message,expected",
    [
        ({"text": "/start"}, "Send a text"),
        ({"text": "/help"}, "Send a text"),
        ({"text": "/tasks"}, "No tasks"),
        ({"text": "/unknown"}, "Send a text"),
        ({"photo": [{}]}, "Unsupported"),
        ({"text": "x" * 5001}, "1–5000"),
        ({"voice": {**voice(), "duration": 0}}, "supported audio"),
    ],
)
async def test_bot_commands_and_validation(pipeline, message, expected):
    await bot.handle_update(update(**message))
    async with pipeline() as session:
        row = await session.scalar(select(Outbox).where(Outbox.kind == "notification"))
        assert expected in row.payload["text"]
        assert not await session.scalar(select(func.count()).select_from(Task))


async def test_bot_private_login_and_task_listing(pipeline):
    await bot.handle_update(update(text="Call Anna"))
    await bot.handle_update(update(2, text="/tasks"))
    await bot.handle_update(update(3, text="/login"))
    async with pipeline() as session:
        texts = [
            row.payload["text"]
            for row in (
                await session.scalars(
                    select(Outbox).where(Outbox.kind == "notification")
                )
            ).all()
        ]
        assert any("PENDING: Call Anna" in text for text in texts)
        assert any("login code:" in text for text in texts)
    group = update(4, text="/login")
    group["message"]["chat"]["type"] = "group"
    await bot.handle_update(group)
    async with pipeline() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.kind == "notification")
            )
            == 3
        )


async def test_voice_ack_precedes_job_commit(pipeline, monkeypatch):
    statements = []
    event.listen(
        pipeline.kw["bind"].sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, parameters, context, executemany: (
            statements.append(statement)
        ),
    )

    async def acknowledge(*args):
        assert not any(
            "INSERT INTO transcription_jobs" in statement for statement in statements
        )

    monkeypatch.setattr(bot, "send_message", AsyncMock(side_effect=acknowledge))
    await bot.handle_update(update(voice=voice()))
    bot.send_message.assert_awaited_once()
    async with pipeline() as session:
        job = await session.scalar(select(TranscriptionJob))
        queued = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
        assert job.status == "QUEUED" and queued.payload == {"job_id": job.id}


async def test_admission_counts_retries_and_active_jobs(pipeline, monkeypatch):
    monkeypatch.setattr(worker.settings, "concurrent_jobs_per_user", 1)
    await bot.handle_update(update(voice=voice()))
    await bot.handle_update(update(2, voice=voice()))
    async with pipeline() as session:
        assert (
            await session.scalar(select(func.count()).select_from(TranscriptionJob))
            == 1
        )
        user = await session.scalar(select(User))
        job = await session.scalar(select(TranscriptionJob))
        monkeypatch.setattr(worker.settings, "hourly_transcription_limit", 1)
        with pytest.raises(DomainError, match="limit"):
            await worker.enforce_admission(session, user, exclude_job_id=job.id)
        monkeypatch.setattr(worker.settings, "hourly_transcription_limit", 10)
        monkeypatch.setattr(worker.settings, "daily_transcription_limit", 1)
        with pytest.raises(DomainError, match="limit"):
            await worker.enforce_admission(session, user, exclude_job_id=job.id)


@pytest_asyncio.fixture
async def queued_job(pipeline, monkeypatch):
    await bot.handle_update(update(voice=voice()))
    async with pipeline() as session:
        job = await session.scalar(select(TranscriptionJob))
        job_id = job.id
    monkeypatch.setattr(worker, "download_audio", AsyncMock())
    monkeypatch.setattr(worker, "inspect_audio", AsyncMock(return_value=3.0))
    monkeypatch.setattr(
        worker, "convert_audio", AsyncMock(side_effect=lambda path: path)
    )
    monkeypatch.setattr(
        worker,
        "transcribe_audio",
        AsyncMock(return_value=("Call Anna tomorrow", "english")),
    )
    return job_id


async def test_worker_success_is_atomic_and_duplicate_safe(pipeline, queued_job):
    await worker.process_job(queued_job)
    await worker.process_job(queued_job)
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        tasks = (await session.scalars(select(Task))).all()
        assert job.status == "COMPLETED" and job.detected_language == "english"
        assert job.estimated_cost > 0 and job.latency_ms is not None
        assert len(tasks) == 1 and tasks[0].source_key == f"voice:{queued_job}"
        assert tasks[0].title == "Call Anna tomorrow"
    worker.transcribe_audio.assert_awaited_once()


async def test_voice_route_uses_same_parser_as_text(pipeline, queued_job, monkeypatch):
    parsed = TaskCreate(
        title="Call Anna",
        description="Discuss the report",
        due_date=datetime(2026, 10, 22, 14, tzinfo=UTC),
        priority="HIGH",
    )
    monkeypatch.setattr(worker, "parse_task", AsyncMock(return_value=parsed))

    await worker.process_job(queued_job)

    worker.parse_task.assert_awaited_once_with("Call Anna tomorrow")
    async with pipeline() as session:
        task = await session.scalar(select(Task))
        assert (task.title, task.description, task.due_date, task.priority) == (
            "Call Anna",
            "Discuss the report",
            datetime(2026, 10, 22, 14, tzinfo=UTC),
            "HIGH",
        )
        assert (await session.get(TranscriptionJob, queued_job)).status == "COMPLETED"


async def test_voice_parser_error_is_recorded_without_retry(
    pipeline, queued_job, monkeypatch
):
    monkeypatch.setattr(
        worker,
        "parse_task",
        AsyncMock(side_effect=worker.TaskParserError("Try again / Կրկին փորձիր", 503)),
    )

    await worker.process_job(queued_job)

    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "FAILED"
        assert job.error_code == "task_parse_failed"
        assert job.retry_count == 0
        notifications = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "notification"))
        )
        assert any(
            "Try again / Կրկին փորձիր" in row.payload["text"] for row in notifications
        )


async def test_voice_route_does_not_create_task_for_conversation(
    pipeline, queued_job, monkeypatch
):
    worker.transcribe_audio.return_value = ("How are you today?", "english")
    monkeypatch.setattr(worker, "parse_task", AsyncMock(return_value=None))

    await worker.process_job(queued_job)

    worker.parse_task.assert_awaited_once_with("How are you today?")
    async with pipeline() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        assert (await session.get(TranscriptionJob, queued_job)).status == "COMPLETED"
        notifications = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "notification"))
        )
        assert any(
            "couldn't identify a task" in row.payload["text"] for row in notifications
        )


async def test_worker_preserves_medium_voice_transcript(pipeline, queued_job):
    transcript = "Զանգել Աննային և քննարկել զեկույցի մանրամասները։ " * 20
    worker.transcribe_audio.return_value = (transcript, "armenian")
    await worker.process_job(queued_job)
    async with pipeline() as session:
        task = await session.scalar(select(Task))
        assert task.description == transcript.strip()
        assert 1 <= len(task.title) <= 300
        assert (await session.get(TranscriptionJob, queued_job)).status == "COMPLETED"


async def test_worker_saves_all_dictated_fields_once(pipeline, queued_job):
    worker.transcribe_audio.return_value = (
        "Title Prepare report. Description Include the sales figures. "
        "Due date 2026-12-31 at six thirty PM. Priority high.",
        "english",
    )
    await worker.process_job(queued_job)
    await worker.process_job(queued_job)
    async with pipeline() as session:
        task = (await session.scalars(select(Task))).one()
        assert task.title == "Prepare report"
        assert task.description == "Include the sales figures"
        assert task.due_date == datetime(2026, 12, 31, 14, 30, tzinfo=UTC)
        assert task.priority == "HIGH" and task.status == "PENDING"
        assert task.source == "TELEGRAM_VOICE"
        assert (await session.get(TranscriptionJob, queued_job)).status == "COMPLETED"
        events = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "event"))
        )
        assert sum(row.payload["event"] == "task.created" for row in events) == 1
        notifications = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "notification"))
        )
        confirmation = next(
            row.payload["text"]
            for row in notifications
            if "Task created" in row.payload["text"]
        )
        assert "Include the sales figures" in confirmation
        assert "Due date (Yerevan time): 2026-12-31 18:30" in confirmation
        assert "Priority: HIGH" in confirmation
    worker.transcribe_audio.assert_awaited_once()


async def test_text_saves_dictated_fields(pipeline):
    await bot.handle_update(
        update(text="Title Buy milk. Description Two bottles. Priority low.")
    )
    async with pipeline() as session:
        task = (await session.scalars(select(Task))).one()
        assert task.title == "Buy milk" and task.description == "Two bottles"
        assert task.priority == "LOW" and task.source == "TELEGRAM_TEXT"


async def test_worker_invalid_dictated_fields_has_no_partial_task(pipeline, queued_job):
    worker.transcribe_audio.return_value = (
        "Title Buy milk. Priority urgent.",
        "english",
    )
    await worker.process_job(queued_job)
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "FAILED" and job.error_code == "invalid_transcript"
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        notifications = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "notification"))
        )
        assert any(
            "priority high, medium, or low" in row.payload["text"]
            for row in notifications
        )


async def test_worker_armenian_dictation_saves_all_fields(pipeline, queued_job):
    worker.transcribe_audio.return_value = (
        "Վերնագիր Զանգել Աննային։ Նկարագրություն Քննարկել զեկույցը։ "
        "Վերջնաժամկետ 2026-12-31 ժամը 18:30։ Առաջնահերթություն բարձր։",
        "armenian",
    )
    await worker.process_job(queued_job)
    async with pipeline() as session:
        task = (await session.scalars(select(Task))).one()
        assert (
            task.title == "Զանգել Աննային" and task.description == "Քննարկել զեկույցը"
        )
        assert task.due_date == datetime(2026, 12, 31, 14, 30, tzinfo=UTC)
        assert task.priority == "HIGH" and task.source == "TELEGRAM_VOICE"
        assert (
            await session.get(TranscriptionJob, queued_job)
        ).detected_language == "armenian"
        notifications = list(
            await session.scalars(select(Outbox).where(Outbox.kind == "notification"))
        )
        confirmation = next(
            row.payload["text"]
            for row in notifications
            if "Զանգել Աննային" in row.payload["text"]
        )
        assert "Նկարագրություն: Քննարկել զեկույցը" in confirmation
        assert "Վերջնաժամկետ (Երևանի ժամանակով): 2026-12-31 18:30" in confirmation
        assert "Առաջնահերթություն: բարձր" in confirmation


async def test_armenian_text_dictation_saves_separate_fields(pipeline):
    await bot.handle_update(
        update(
            text="Վերնագիր Զանգել։ Նկարագրություն Քննարկել զեկույցը։ Առաջնահերթություն միջին։"
        )
    )
    async with pipeline() as session:
        task = (await session.scalars(select(Task))).one()
        assert task.title == "Զանգել" and task.description == "Քննարկել զեկույցը"
        assert task.priority == "MEDIUM" and task.source == "TELEGRAM_TEXT"


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (audio.AudioError("corrupted_audio"), "FAILED", "corrupted_audio"),
        (TimeoutError(), "TIMED_OUT", "timeout"),
        (ValueError("bad output"), "FAILED", "invalid_transcript"),
    ],
)
async def test_worker_failure_has_no_task_and_has_fallback(
    pipeline, queued_job, monkeypatch, failure, status, code
):
    monkeypatch.setattr(worker, "transcribe_audio", AsyncMock(side_effect=failure))
    await worker.process_job(queued_job)
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == status and job.error_code == code
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        row = await session.scalar(select(Outbox).where(Outbox.kind == "notification"))
        assert "send your task as text" in row.payload["text"]


async def test_worker_empty_transcript_does_not_create_task(
    pipeline, queued_job, monkeypatch
):
    monkeypatch.setattr(
        worker, "transcribe_audio", AsyncMock(return_value=("   ", "english"))
    )
    await worker.process_job(queued_job)
    async with pipeline() as session:
        assert (await session.get(TranscriptionJob, queued_job)).status == "FAILED"
        assert await session.scalar(select(func.count()).select_from(Task)) == 0


async def test_worker_infrastructure_failure_rolls_back_for_retry(
    pipeline, queued_job, monkeypatch
):
    monkeypatch.setattr(
        worker, "download_audio", AsyncMock(side_effect=RuntimeError("offline"))
    )
    with pytest.raises(RuntimeError):
        await worker.process_job(queued_job)
    async with pipeline() as session:
        assert (await session.get(TranscriptionJob, queued_job)).status == "RETRYING"
    await worker.process_job(str(uuid4()))


async def test_outbox_retries_failed_effect_without_starving_notifications(
    pipeline, monkeypatch
):
    await bot.handle_update(update(text="Call Anna"))
    publish = AsyncMock(side_effect=ConnectionError())
    monkeypatch.setattr(worker, "publish_event", publish)
    await worker.deliver_outbox()
    async with pipeline() as session:
        rows = (await session.scalars(select(Outbox))).all()
        event = next(row for row in rows if row.kind == "event")
        notification = next(row for row in rows if row.kind == "notification")
        assert event.delivered_at is None and event.attempts == 1
        assert notification.delivered_at is not None and notification.payload == {}
    publish.side_effect = None
    async with pipeline() as session, session.begin():
        row = await session.scalar(select(Outbox).where(Outbox.kind == "event"))
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await worker.deliver_outbox()
    assert publish.await_count == 2
    bot.send_message.assert_awaited_once()


async def test_queue_dispatch_and_stale_recovery(pipeline, queued_job, monkeypatch):
    send = Mock()
    monkeypatch.setattr(worker.celery_app, "send_task", send)
    await worker.deliver_outbox()
    send.assert_called_once_with(
        "app.worker.transcribe", args=[queued_job], retry=False
    )
    async with pipeline() as session, session.begin():
        job = await session.get(TranscriptionJob, queued_job)
        job.created_at = datetime.now(UTC) - timedelta(hours=1)
        row = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
        row.delivered_at = datetime.now(UTC) - timedelta(hours=1)
    await worker.recover_queued_jobs()
    await worker.recover_queued_jobs()
    async with pipeline() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.kind == "transcribe.recover")
            )
            == 1
        )


async def test_inspect_audio_checks_missing_corrupt_silence_and_real_format(
    tmp_path, monkeypatch
):
    path = tmp_path / "audio"
    with pytest.raises(audio.AudioError, match="invalid_size"):
        await audio.inspect_audio(path)
    path.write_bytes(b"audio")
    tools = AsyncMock(return_value=(b"broken", b""))
    monkeypatch.setattr(audio, "run_audio_tool", tools)
    with pytest.raises(audio.AudioError, match="corrupted_audio"):
        await audio.inspect_audio(path)
    metadata = json.dumps(
        {
            "format": {"duration": "3", "format_name": "ogg"},
            "streams": [{"codec_type": "audio"}],
        }
    ).encode()
    tools.side_effect = [(metadata, b""), (b"", b"max_volume: -inf dB")]
    with pytest.raises(audio.AudioError, match="no_clear_speech"):
        await audio.inspect_audio(path)
    tools.side_effect = [(metadata, b""), (b"", b"max_volume: -5.0 dB")]
    assert await audio.inspect_audio(path) == 3


@respx.mock
async def test_download_uses_fixed_host_and_bounded_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    route = respx.get("https://api.telegram.org/bottest-token/getFile").respond(
        200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}}
    )
    respx.get("https://api.telegram.org/file/bottest-token/voice/file.ogg").respond(
        200, content=b"audio"
    )
    path = tmp_path / "audio"
    await audio.download_audio("file", path)
    assert route.called and path.read_bytes() == b"audio"
    route.respond(200, json={"ok": True, "result": {"file_path": "../secret.ogg"}})
    with pytest.raises(audio.AudioError, match="invalid_file_path"):
        await audio.download_audio("file", tmp_path / "other")


@respx.mock
async def test_download_retries_transient_metadata_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(audio.asyncio, "sleep", AsyncMock())
    route = respx.get("https://api.telegram.org/bottest-token/getFile").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"file_path": "voice/file.ogg"},
                },
            ),
        ]
    )
    respx.get("https://api.telegram.org/file/bottest-token/voice/file.ogg").respond(
        200, content=b"audio"
    )
    path = tmp_path / "audio"
    await audio.download_audio("file", path)
    assert route.call_count == 2 and path.read_bytes() == b"audio"


@respx.mock
async def test_download_discards_partial_audio_before_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(audio.asyncio, "sleep", AsyncMock())
    respx.get("https://api.telegram.org/bottest-token/getFile").respond(
        200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}}
    )

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("connection interrupted")

    route = respx.get(
        "https://api.telegram.org/file/bottest-token/voice/file.ogg"
    ).mock(
        side_effect=[
            httpx.Response(200, stream=InterruptedStream()),
            httpx.Response(200, content=b"complete"),
        ]
    )
    path = tmp_path / "audio"
    await audio.download_audio("file", path)
    assert route.call_count == 2 and path.read_bytes() == b"complete"


@respx.mock
async def test_download_exhausts_transient_failures_and_keeps_existing_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(audio.asyncio, "sleep", AsyncMock())
    route = respx.get("https://api.telegram.org/bottest-token/getFile").respond(503)
    path = tmp_path / "audio"
    with pytest.raises(audio.AudioError, match="download_unavailable"):
        await audio.download_audio("file", path)
    assert route.call_count == 3 and not path.exists()
    route.respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        await audio.download_audio("file", path)
    assert route.call_count == 4
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        await audio.download_audio("file", path)
    assert route.call_count == 4 and path.read_bytes() == b"existing"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    path = tmp_path / "voice.ogg"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(audio.settings, "openai_api_key", "fixture-key")
    monkeypatch.setattr(
        audio.settings, "provider_base_url", "https://api.openai.com/v1"
    )
    monkeypatch.setattr(audio.settings, "whisper_model", "gpt-transcribe")
    monkeypatch.setattr(audio.settings, "whisper_language", "auto")
    redis = AsyncMock()
    redis.__aenter__.return_value = redis
    redis.incr.return_value = 1
    monkeypatch.setattr(audio.Redis, "from_url", Mock(return_value=redis))
    monkeypatch.setattr(audio, "provider_gate", AsyncMock())
    monkeypatch.setattr(audio.asyncio, "sleep", AsyncMock())
    return path, redis


@respx.mock
async def test_transcription_retries_rate_limit_and_timeout(provider):
    path, _ = provider
    route = respx.post("https://api.openai.com/v1/audio/transcriptions")
    route.side_effect = [
        httpx.ReadTimeout("timeout"),
        httpx.Response(429),
        httpx.Response(200, json={"text": "Call Anna", "languages": [{"code": "en"}]}),
    ]
    assert await audio.transcribe_audio(path) == ("Call Anna", "english")
    assert route.call_count == 3
    assert audio.asyncio.sleep.await_count == 2
    request = route.calls.last.request
    assert b'name="model"\r\n\r\ngpt-transcribe' in request.content
    assert b'name="languages[]"\r\n\r\nhy' in request.content
    assert b'name="languages[]"\r\n\r\nen' in request.content
    assert b'name="language"' not in request.content
    assert b"verbose_json" not in request.content


@respx.mock
@pytest.mark.parametrize(
    "model,endpoint",
    [
        ("base", "http://local-whisper:8080/v1"),
        ("whisper-1", "https://api.openai.com/v1"),
    ],
)
async def test_legacy_transcription_payload_and_language(
    provider, monkeypatch, model, endpoint
):
    path, _ = provider
    monkeypatch.setattr(audio.settings, "whisper_model", model)
    monkeypatch.setattr(audio.settings, "provider_base_url", endpoint)
    monkeypatch.setattr(audio.settings, "whisper_language", "hy")
    route = respx.post(f"{endpoint}/audio/transcriptions").respond(
        200,
        json={
            "text": "Զանգել Աննային",
            "language": "armenian",
            "segments": [{"avg_logprob": -0.2, "no_speech_prob": 0.01}],
        },
    )
    assert await audio.transcribe_audio(path) == ("Զանգել Աննային", "armenian")
    body = route.calls.last.request.content
    assert b'name="response_format"\r\n\r\nverbose_json' in body
    assert b'name="language"\r\n\r\nhy' in body
    assert b'name="languages[]"' not in body


@respx.mock
@pytest.mark.parametrize(
    "segment,code",
    [
        ({"no_speech_prob": 0.8}, "no_clear_speech"),
        ({"avg_logprob": -1.2}, "no_clear_speech"),
        ({"avg_logprob": "bad"}, "invalid_transcript"),
        (None, "invalid_transcript"),
    ],
)
async def test_legacy_transcription_rejects_unusable_segments(
    provider, monkeypatch, segment, code
):
    path, _ = provider
    monkeypatch.setattr(audio.settings, "whisper_model", "whisper-1")
    respx.post("https://api.openai.com/v1/audio/transcriptions").respond(
        200,
        json={"text": "invented speech", "language": "english", "segments": [segment]},
    )
    with pytest.raises(audio.AudioError, match=code):
        await audio.transcribe_audio(path)


@respx.mock
@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(503), "provider_unavailable"),
        (httpx.Response(401), "provider_rejected"),
        (httpx.Response(200, json={"text": 1}), "invalid_transcript"),
        (
            httpx.Response(
                200, json={"text": "Bonjour", "languages": [{"code": "fr"}]}
            ),
            "unsupported_language",
        ),
        (
            httpx.Response(200, json={"text": "Call Anna", "languages": "invalid"}),
            "invalid_transcript",
        ),
    ],
)
async def test_transcription_failures_controlled(provider, response, code):
    path, _ = provider
    respx.post("https://api.openai.com/v1/audio/transcriptions").return_value = response
    with pytest.raises(audio.AudioError, match=code):
        await audio.transcribe_audio(path)


async def test_provider_rate_limit_and_circuit(monkeypatch):
    redis = AsyncMock()
    redis.get.return_value = "open"
    with pytest.raises(audio.AudioError, match="provider_unavailable"):
        await audio.provider_gate(redis)
    redis.get.return_value = None
    redis.eval.return_value = audio.settings.global_ai_requests_per_minute + 1
    with pytest.raises(audio.AudioError, match="provider_busy"):
        await audio.provider_gate(redis)
    redis.eval.return_value = 1
    await audio.provider_gate(redis)


async def test_webhook_secret_validation_and_health(monkeypatch):
    monkeypatch.setattr(bot.settings, "webhook_secret", "fixture-secret")
    handler = AsyncMock()
    monkeypatch.setattr(bot, "handle_update", handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=bot.app), base_url="http://bot"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (
            await client.post("/telegram/webhook", json=update(text="task"))
        ).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": "fixture-secret"}
        assert (
            await client.post(
                "/telegram/webhook", json=update(text="task"), headers=headers
            )
        ).status_code == 200
        assert (
            await client.post("/telegram/webhook", content=b"bad", headers=headers)
        ).status_code == 422
        assert (
            await client.post(
                "/telegram/webhook", content=b"a" * 262145, headers=headers
            )
        ).status_code == 413
        handler.side_effect = RuntimeError("db offline")
        assert (
            await client.post(
                "/telegram/webhook", json=update(text="task"), headers=headers
            )
        ).status_code == 503


@respx.mock
@pytest.mark.parametrize(
    "languages,code",
    [
        (None, "invalid_transcript"),
        ([None], "invalid_transcript"),
        ([{}], "invalid_transcript"),
        ([{"code": 1}], "invalid_transcript"),
        ([{"code": "fr"}], "unsupported_language"),
    ],
)
async def test_transcription_rejects_invalid_or_unsupported_languages(
    provider, languages, code
):
    path, _ = provider
    respx.post("https://api.openai.com/v1/audio/transcriptions").respond(
        200,
        json={"text": "invented speech", "languages": languages},
    )
    with pytest.raises(audio.AudioError, match=code):
        await audio.transcribe_audio(path)


@respx.mock
async def test_transcription_language_preference_and_circuit_opens(
    provider, monkeypatch
):
    path, redis = provider
    monkeypatch.setattr(audio.settings, "whisper_language", "hy")
    route = respx.post("https://api.openai.com/v1/audio/transcriptions")
    route.respond(
        200,
        json={
            "text": "Զանգել Աննային",
            "languages": [{"code": "hy"}],
        },
    )
    assert await audio.transcribe_audio(path) == ("Զանգել Աննային", "armenian")
    assert b'name="languages[]"\r\n\r\nhy' in route.calls.last.request.content
    assert b'name="languages[]"\r\n\r\nen' not in route.calls.last.request.content
    redis.incr.return_value = 5
    route.respond(503)
    with pytest.raises(audio.AudioError, match="provider_unavailable"):
        await audio.transcribe_audio(path)
    redis.set.assert_awaited_with("ai:circuit:open", "1", ex=30)


async def test_missing_provider_key_fails_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.settings, "openai_api_key", "")
    with pytest.raises(audio.AudioError, match="provider_unavailable"):
        await audio.transcribe_audio(tmp_path / "missing")


@respx.mock
@pytest.mark.parametrize(
    "content,length", [(b"", None), (b"audio", "30000000"), (b"audio", "invalid")]
)
async def test_download_rejects_empty_or_oversized_response(
    tmp_path, monkeypatch, content, length
):
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    respx.get("https://api.telegram.org/bottest-token/getFile").respond(
        200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}}
    )
    headers = {"content-length": length} if length else {}
    respx.get("https://api.telegram.org/file/bottest-token/voice/file.ogg").respond(
        200, content=content, headers=headers
    )
    with pytest.raises(audio.AudioError, match="invalid_size"):
        await audio.download_audio("file", tmp_path / "audio")


@respx.mock
async def test_download_stream_limit_without_content_length(tmp_path, monkeypatch):
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 600000
            yield b"x" * 600000

    monkeypatch.setattr(audio.settings, "max_audio_file_size_mb", 1)
    monkeypatch.setattr(audio.settings, "telegram_bot_token", "test-token")
    respx.get("https://api.telegram.org/bottest-token/getFile").respond(
        200, json={"ok": True, "result": {"file_path": "voice/file.ogg"}}
    )
    respx.get(
        "https://api.telegram.org/file/bottest-token/voice/file.ogg"
    ).return_value = httpx.Response(200, stream=Chunks())
    with pytest.raises(audio.AudioError, match="invalid_size"):
        await audio.download_audio("file", tmp_path / "audio")
    assert (tmp_path / "audio").stat().st_size == 600000


async def test_real_audio_tools_reject_corruption_and_silence_and_convert(tmp_path):
    path = tmp_path / "input.wav"
    await audio.run_audio_tool(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        str(path),
    )
    assert await audio.inspect_audio(path) == 2
    source = tmp_path / "voice"
    source.write_bytes(path.read_bytes())
    result = await audio.convert_audio(source)
    assert result.suffix == ".wav" and await audio.inspect_audio(result) == 2
    silent = tmp_path / "silence.wav"
    await audio.run_audio_tool(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono",
        "-t",
        "2",
        str(silent),
    )
    with pytest.raises(audio.AudioError, match="no_clear_speech"):
        await audio.inspect_audio(silent)
    source.write_bytes(b"broken audio")
    with pytest.raises(audio.AudioError, match="corrupted_audio"):
        await audio.inspect_audio(source)


async def test_audio_subprocess_is_killed_on_timeout(monkeypatch):
    process = Mock()
    process.communicate = AsyncMock(side_effect=TimeoutError())
    process.wait = AsyncMock()
    monkeypatch.setattr(
        audio.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    with pytest.raises(TimeoutError):
        await audio.run_audio_tool("ffmpeg", "-version")
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


async def test_temporary_audio_removed_on_provider_failure(
    pipeline, queued_job, monkeypatch
):
    paths = []

    async def download(file_id, path):
        path.write_bytes(b"sensitive voice")
        paths.append(path)

    monkeypatch.setattr(worker, "download_audio", download)
    monkeypatch.setattr(
        worker,
        "transcribe_audio",
        AsyncMock(side_effect=audio.AudioError("provider_unavailable")),
    )
    await worker.process_job(queued_job)
    assert paths and not paths[0].exists() and not paths[0].parent.exists()


async def test_telegram_send_uses_one_api_call_and_plain_text(monkeypatch):
    from aioresponses import aioresponses

    monkeypatch.setattr(bot.settings, "telegram_bot_token", "123:fixture")
    with aioresponses() as telegram:
        telegram.post(
            "https://api.telegram.org/bot123:fixture/sendMessage",
            payload={
                "ok": True,
                "result": {
                    "message_id": 1,
                    "date": 1,
                    "chat": {"id": 123, "type": "private"},
                    "text": "<script>",
                },
            },
        )
        await bot.send_message("123", "<script>")
        calls = [call for requests in telegram.requests.values() for call in requests]
        assert len(calls) == 1
        fields = {
            meta["name"]: value for meta, _, value in calls[0].kwargs["data"]._fields
        }
        assert fields["text"] == "<script>" and "parse_mode" not in fields


async def test_infrastructure_retry_budget_ends_in_dead_letter(
    pipeline, queued_job, monkeypatch
):
    monkeypatch.setattr(
        worker, "download_audio", AsyncMock(side_effect=RuntimeError("offline"))
    )
    for expected in range(1, 4):
        with pytest.raises(RuntimeError):
            await worker.process_job(queued_job)
        async with pipeline() as session:
            job = await session.get(TranscriptionJob, queued_job)
            assert job.status == "RETRYING" and job.retry_count == expected
    await worker.process_job(queued_job)
    await worker.process_job(queued_job)
    assert worker.download_audio.await_count == 4
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "DEAD_LETTER" and job.error_code == "dead_letter"
        assert job.completed_at is not None
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.kind == "notification")
            )
            == 1
        )


@pytest.mark.parametrize("via_recovery", [False, True])
async def test_expired_job_never_calls_provider(pipeline, queued_job, via_recovery):
    async with pipeline() as session, session.begin():
        job = await session.get(TranscriptionJob, queued_job)
        job.created_at = datetime.now(UTC) - timedelta(days=1, seconds=1)
    if via_recovery:
        await worker.recover_queued_jobs()
    else:
        await worker.process_job(queued_job)
    worker.download_audio.assert_not_awaited()
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "FAILED" and job.error_code == "expired"


async def test_recovery_exhaustion_and_global_admission_bound(
    pipeline, queued_job, monkeypatch
):
    async with pipeline() as session, session.begin():
        job = await session.get(TranscriptionJob, queued_job)
        monkeypatch.setattr(worker.settings, "global_queued_jobs_limit", 1)
        user = await session.get(User, job.user_id)
        with pytest.raises(DomainError, match="queue is busy"):
            await worker.enforce_admission(session, user)
        job.created_at = datetime.now(UTC) - timedelta(hours=1)
        job.retry_count = 3
        row = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
        row.delivered_at = datetime.now(UTC) - timedelta(hours=1)
    await worker.recover_queued_jobs()
    async with pipeline() as session:
        assert (
            await session.get(TranscriptionJob, queued_job)
        ).error_code == "dead_letter"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Outbox)
                .where(Outbox.kind == "transcribe.recover")
            )
            == 0
        )


async def test_outbox_backoff_dead_letter_and_retention(pipeline, monkeypatch):
    await bot.handle_update(update(text="Call Anna"))
    publish = AsyncMock(side_effect=ConnectionError())
    monkeypatch.setattr(worker, "publish_event", publish)
    await worker.deliver_outbox()
    await worker.deliver_outbox()
    publish.assert_awaited_once()
    async with pipeline() as session, session.begin():
        row = await session.scalar(select(Outbox).where(Outbox.kind == "event"))
        assert row.available_at > datetime.now(UTC) - timedelta(seconds=1)
        row.attempts, row.available_at = 11, datetime.now(UTC) - timedelta(seconds=1)
        row_id = row.id
    await worker.deliver_outbox()
    async with pipeline() as session, session.begin():
        row = await session.get(Outbox, row_id)
        assert (
            row.kind == "event" and row.error_code == "exhausted" and row.payload == {}
        )
        assert row.delivered_at is not None and row.attempts == 12
        row.delivered_at = datetime.now(UTC) - timedelta(days=8)
    await worker.deliver_outbox()
    assert publish.await_count == 2
    async with pipeline() as session:
        assert await session.get(Outbox, row_id) is None


async def test_dead_letter_job_retention_preserves_completed_tasks(
    pipeline, queued_job, monkeypatch
):
    await worker.process_job(queued_job)
    async with pipeline() as session, session.begin():
        job = await session.get(TranscriptionJob, queued_job)
        job.status, job.error_code = "FAILED", "dead_letter"
        job.completed_at = datetime.now(UTC) - timedelta(days=8)
    monkeypatch.setattr(worker, "publish_event", AsyncMock())
    await worker.deliver_outbox()
    async with pipeline() as session:
        assert await session.get(TranscriptionJob, queued_job) is None
        assert await session.scalar(select(func.count()).select_from(Task)) == 1


async def test_expired_outbox_drops_sensitive_payload_without_delivery(
    pipeline, queued_job, monkeypatch
):
    async with pipeline() as session, session.begin():
        row = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
        row.created_at = datetime.now(UTC) - timedelta(days=2)
        row_id = row.id
    send = Mock()
    monkeypatch.setattr(worker.celery_app, "send_task", send)
    await worker.deliver_outbox()
    send.assert_not_called()
    async with pipeline() as session:
        row = await session.get(Outbox, row_id)
        assert (
            row.kind == "transcribe"
            and row.error_code == "expired"
            and row.payload == {}
        )


@respx.mock
async def test_provider_usage_counts_attempts_and_failures(provider):
    path, redis = provider
    route = respx.post("https://api.openai.com/v1/audio/transcriptions")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"text": "Call Anna", "languages": [{"code": "en"}]}),
    ]
    await audio.transcribe_audio(path)
    calls = [call.args[1:] for call in redis.hincrby.await_args_list]
    assert calls.count(("attempts", 1)) == 2
    assert calls.count(("http_failures", 1)) == 1
    assert calls.count(("accepted", 1)) == 1


async def test_polling_retries_failed_update_before_acknowledging_offset(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    values = [
        SimpleNamespace(update_id=i, model_dump=Mock(return_value={"update_id": i}))
        for i in (1, 2)
    ]
    telegram = Mock()
    telegram.get_updates = AsyncMock(
        side_effect=[values, [values[1]], asyncio.CancelledError()]
    )
    seen = []

    async def handle(update):
        seen.append(update["update_id"])
        if seen == [1, 2]:
            raise RuntimeError("database offline")

    monkeypatch.setattr(bot, "handle_update", handle)
    monkeypatch.setattr(bot.asyncio, "sleep", AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        await bot.poll_updates(telegram)
    assert seen == [1, 2, 2]
    assert [call.kwargs["offset"] for call in telegram.get_updates.await_args_list] == [
        None,
        2,
        3,
    ]
    bot.asyncio.sleep.assert_awaited_once_with(2)


async def test_polling_lifespan_cancels_and_closes_client(monkeypatch):
    import asyncio

    telegram = Mock()
    telegram.__aenter__ = AsyncMock(return_value=telegram)
    telegram.__aexit__ = AsyncMock()
    monkeypatch.setattr(bot, "Bot", Mock(return_value=telegram))
    monkeypatch.setattr(bot.settings, "telegram_mode", "polling")
    monkeypatch.setattr(bot.settings, "telegram_bot_token", "123:fixture")
    started, stopped = asyncio.Event(), asyncio.Event()

    async def poll(_telegram):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(bot, "poll_updates", poll)
    async with bot.lifespan(bot.app):
        await asyncio.wait_for(started.wait(), 1)
    assert stopped.is_set()
    telegram.__aexit__.assert_awaited_once()


def test_whisper_backoff_is_configured_jittered_and_capped(monkeypatch):
    monkeypatch.setattr(audio.random, "uniform", lambda *_: 0.25)
    monkeypatch.setattr(audio.settings, "whisper_retry_backoff_base", 2)
    monkeypatch.setattr(audio.settings, "whisper_retry_backoff_max", 30)
    assert [audio.whisper_retry_delay(i) for i in (0, 1, 2, 10)] == [
        2.25,
        4.25,
        8.25,
        30,
    ]


async def test_provider_exhaustion_is_terminal_and_not_reprocessed(
    pipeline, queued_job, monkeypatch
):
    provider = AsyncMock(side_effect=audio.AudioError("provider_unavailable"))
    monkeypatch.setattr(worker, "transcribe_audio", provider)
    await worker.process_job(queued_job)
    await worker.process_job(queued_job)
    provider.assert_awaited_once()
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "DEAD_LETTER" and job.error_code == "provider_unavailable"
        assert await session.scalar(select(func.count()).select_from(Task)) == 0


async def test_abandoned_processing_claim_is_recovered(pipeline, queued_job):
    async with pipeline() as session, session.begin():
        job = await session.get(TranscriptionJob, queued_job)
        job.status = "PROCESSING"
        job.created_at = job.started_at = datetime.now(UTC) - timedelta(hours=1)
        row = await session.scalar(select(Outbox).where(Outbox.kind == "transcribe"))
        row.delivered_at = job.created_at
    await worker.recover_queued_jobs()
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "RETRYING" and job.retry_count == 1
    await worker.process_job(queued_job)
    async with pipeline() as session:
        assert (await session.get(TranscriptionJob, queued_job)).status == "COMPLETED"


def test_worker_heartbeat_has_expiry_and_tolerates_redis_failure(monkeypatch):
    from types import SimpleNamespace

    from redis.exceptions import ConnectionError

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock()
    monkeypatch.setattr(worker.SyncRedis, "from_url", Mock(return_value=client))
    sender = SimpleNamespace(eventer=SimpleNamespace(hostname="transcription@test"))
    worker.worker_heartbeat(sender)
    client.set.assert_called_once_with("worker:alive:transcription", "1", ex=60)
    client.set.side_effect = ConnectionError()
    worker.worker_heartbeat(sender)


async def test_outbox_honors_telegram_retry_after(pipeline, monkeypatch):
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    await bot.handle_update(update(text="Call Anna"))
    monkeypatch.setattr(
        bot,
        "send_message",
        AsyncMock(
            side_effect=TelegramRetryAfter(
                method=SendMessage(chat_id=123, text="fixture"),
                message="rate limited",
                retry_after=120,
            )
        ),
    )
    monkeypatch.setattr(worker, "publish_event", AsyncMock())
    await worker.deliver_outbox()
    async with pipeline() as session:
        row = await session.scalar(select(Outbox).where(Outbox.kind == "notification"))
        assert row.delivered_at is None and row.attempts == 1
        assert 115 < (row.available_at - datetime.now(UTC)).total_seconds() <= 120
    await worker.deliver_outbox()
    bot.send_message.assert_awaited_once()


async def test_bot_rate_limit_bounds_all_messages_and_warns_once(pipeline, monkeypatch):
    monkeypatch.setattr(bot, "BOT_MESSAGES_PER_MINUTE", 2, raising=False)
    await bot.handle_update(update(1, text="First task"))
    await bot.handle_update(update(2, text="/help"))
    await bot.handle_update(update(3, voice=voice()))
    await bot.handle_update(update(4, text="Do not create this"))
    assert not await bot.handle_update(update(4, text="Duplicate"))
    other = update(5, text="Other user's task")
    other["message"]["from"]["id"] = other["message"]["chat"]["id"] = 456
    await bot.handle_update(other)
    async with pipeline() as session:
        assert set(await session.scalars(select(Task.title))) == {
            "First task",
            "Other user's task",
        }
        assert (
            await session.scalar(select(func.count()).select_from(TranscriptionJob))
            == 0
        )
        texts = list(
            await session.scalars(
                select(Outbox.payload).where(Outbox.kind == "notification")
            )
        )
        assert sum("Too many messages" in row["text"] for row in texts) == 1
    bot.send_message.assert_not_awaited()


async def test_bot_rate_limit_expires_without_redis(pipeline, monkeypatch):
    from app.models import ProcessedUpdate

    monkeypatch.setattr(bot, "BOT_MESSAGES_PER_MINUTE", 1, raising=False)
    await bot.handle_update(update(1, text="First task"))
    await bot.handle_update(update(2, text="Limited task"))
    async with pipeline() as session, session.begin():
        receipts = (await session.scalars(select(ProcessedUpdate))).all()
        for receipt in receipts:
            receipt.created_at = datetime.now(UTC) - timedelta(seconds=61)
    await bot.handle_update(update(3, text="After cooldown"))
    async with pipeline() as session:
        assert set(await session.scalars(select(Task.title))) == {
            "First task",
            "After cooldown",
        }


async def test_worker_inaudible_marker_has_fallback_and_no_task(
    pipeline, queued_job, monkeypatch
):
    monkeypatch.setattr(
        worker, "transcribe_audio", AsyncMock(return_value=("[ Inaudible ]", "english"))
    )
    await worker.process_job(queued_job)
    async with pipeline() as session:
        job = await session.get(TranscriptionJob, queued_job)
        assert job.status == "FAILED" and job.error_code == "invalid_transcript"
        assert await session.scalar(select(func.count()).select_from(Task)) == 0
        notification = await session.scalar(
            select(Outbox).where(Outbox.kind == "notification")
        )
        assert "send your task as text" in notification.payload["text"]
