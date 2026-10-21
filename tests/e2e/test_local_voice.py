"""Opt-in real CPU speech recognition; only the Telegram network edge is mocked."""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import respx
from celery.contrib.testing.worker import start_worker
from sqlalchemy import select

from app import bot, worker
from app.auth import create_token
from app.config import settings
from app.models import Outbox, Task, TranscriptionJob
from app.timezone import TASK_TIMEZONE
from tests.integration.conftest import next_event, telegram_update

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("RUN_LOCAL_AI") != "1",
        reason="Run make test-local-ai for real free CPU transcription",
    ),
]


@pytest.mark.parametrize(
    "structured", [False, True], ids=["public-speech", "dictated-fields"]
)
async def test_local_speech_voice_queue_task_sse_and_confirmation(
    stack, live_api, monkeypatch, structured
):
    assert settings.provider_base_url == "http://local-whisper:8080/v1"
    assert settings.openai_api_key == "test-only-key"
    assert settings.whisper_cost_per_minute == 0
    factory, _, _, owner, _ = stack
    speech = Path(
        "tests/fixtures/voice-fields.wav"
        if structured
        else "/fixtures/local-ai/jfk.wav"
    ).read_bytes()
    tomorrow = (datetime.now(TASK_TIMEZONE) + timedelta(days=1)).date()
    queue = f"local-speech-{uuid4().hex}"
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    monkeypatch.setattr(worker.celery_app.conf, "task_default_queue", queue)
    manager = start_worker(
        worker.celery_app,
        pool="solo",
        concurrency=1,
        queues=[queue],
        perform_ping_check=False,
        shutdown_timeout=10,
    )
    await asyncio.to_thread(manager.__enter__)
    started = time.monotonic()
    try:
        with respx.mock(assert_all_called=False) as routes:
            routes.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile"
            ).respond(
                200,
                json={"ok": True, "result": {"file_path": "voice/local-sample.wav"}},
            )
            routes.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/voice/local-sample.wav"
            ).respond(200, content=speech)
            routes.route(host="local-whisper").pass_through()
            routes.route(host="127.0.0.1").pass_through()
            async with httpx.AsyncClient(
                cookies={"session": create_token(owner.id)}, timeout=80
            ) as browser:
                async with browser.stream("GET", f"{live_api}/api/events") as response:
                    lines = response.aiter_lines()
                    assert await next_event(lines, "ready") == "event: ready"
                    await bot.handle_update(
                        telegram_update(
                            800,
                            audio={
                                "file_id": "local-speech",
                                "duration": 11,
                                "file_size": len(speech),
                                "mime_type": "audio/wav",
                            },
                        )
                    )
                    bot.send_message.assert_awaited_once()
                    async with factory() as session:
                        job_id = await session.scalar(select(TranscriptionJob.id))
                    await worker.deliver_outbox()
                    async with asyncio.timeout(80):
                        while True:
                            async with factory() as session:
                                job = await session.get(TranscriptionJob, job_id)
                                if job.status not in {
                                    "QUEUED",
                                    "PROCESSING",
                                    "RETRYING",
                                }:
                                    break
                            await asyncio.sleep(0.1)
                    assert job.status == "COMPLETED", (job.status, job.error_code)
                    await worker.deliver_outbox()
                    assert (
                        await next_event(lines, "task.created") == "event: task.created"
                    )
                    event = json.loads((await anext(lines)).removeprefix("data: "))
                    await worker.process_job(job_id)
                    async with factory() as session:
                        tasks = list(await session.scalars(select(Task)))
                        assert len(tasks) == 1 and tasks[0].id == event["task_id"]
                        assert tasks[0].source == "TELEGRAM_VOICE"
                        if structured:
                            assert tasks[0].title.casefold() == "call anna"
                            assert (
                                tasks[0].description.casefold() == "discuss the report"
                            )
                            assert tasks[0].priority == "HIGH"
                            due = tasks[0].due_date.astimezone(TASK_TIMEZONE)
                            assert due.date() == tomorrow
                            assert due.hour == 18
                            assert due.minute == 0
                        else:
                            assert (
                                "country" in tasks[0].title.lower()
                                and "ask" in tasks[0].title.lower()
                            )
                        assert job.estimated_cost == 0 and job.model_name == "base"
                        assert not (
                            await session.scalars(
                                select(Outbox).where(Outbox.delivered_at.is_(None))
                            )
                        ).all()
                    assert bot.send_message.await_count == 2
                    assert (
                        "Task created from your voice"
                        in bot.send_message.await_args.args[1]
                    )
                    if structured:
                        confirmation = bot.send_message.await_args.args[1]
                        assert "Priority: HIGH" in confirmation
                        assert "Due date (Yerevan time):" in confirmation
                        assert "discuss the report" in confirmation.casefold()
        print(
            json.dumps(
                {
                    "scenario": "real local base model, Telegram edge mocked, queue/DB/SSE real",
                    "structured_fields": structured,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "estimated_provider_usd": 0,
                }
            )
        )
    finally:
        await asyncio.to_thread(manager.__exit__, None, None, None)
