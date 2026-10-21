"""Real Redis/Celery/PostgreSQL/SSE; only Telegram and Whisper HTTP are mocked."""

import asyncio
import io
import json
import math
import struct
import wave
from uuid import uuid4

import httpx
import pytest
import respx
from aioresponses import CallbackResult, aioresponses
from celery.contrib.testing.worker import start_worker
from sqlalchemy import select

from app import bot, worker
from app.auth import create_token
from app.config import settings
from app.models import Outbox, Task, TranscriptionJob
from tests.integration.conftest import next_event, telegram_update

pytestmark = pytest.mark.e2e


def audio_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(
            b"".join(
                struct.pack(
                    "<h", int(8000 * math.sin(2 * math.pi * 440 * index / 16000))
                )
                for index in range(32000)
            )
        )
    return output.getvalue()


async def wait_job(factory, job_id, expected):
    for _ in range(200):
        async with factory() as session:
            job = await session.get(TranscriptionJob, job_id)
            if job.status == expected:
                return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not reach {expected}")


async def test_telegram_text_voice_queue_sse_and_dashboard_crud(stack, live_api):
    factory, redis, client, owner, other = stack
    queue = f"test-{uuid4().hex}"
    worker.celery_app.conf.task_default_queue = queue
    manager = start_worker(
        worker.celery_app,
        pool="solo",
        concurrency=1,
        queues=[queue],
        perform_ping_check=False,
        shutdown_timeout=10,
    )
    await asyncio.to_thread(manager.__enter__)
    payload = audio_bytes()
    sent = []

    def telegram_send(url, **kwargs):
        fields = {meta["name"]: value for meta, _, value in kwargs["data"]._fields}
        sent.append(fields["text"])
        return CallbackResult(
            status=200,
            payload={
                "ok": True,
                "result": {
                    "message_id": len(sent),
                    "date": 0,
                    "chat": {"id": 1001, "type": "private"},
                    "text": "sent",
                },
            },
        )

    try:
        with (
            aioresponses() as telegram,
            respx.mock(assert_all_called=False) as provider,
        ):
            telegram.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                callback=telegram_send,
                repeat=True,
            )
            provider.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile"
            ).respond(
                200, json={"ok": True, "result": {"file_path": "voice/fixture.wav"}}
            )
            provider.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/voice/fixture.wav"
            ).respond(200, content=payload)
            whisper = provider.post(
                f"{settings.provider_base_url}/audio/transcriptions"
            ).respond(
                200,
                json={"text": "Զանգել Աննային վաղը", "languages": [{"code": "hy"}]},
            )
            # Let real browser requests through while intercepting external providers only.
            provider.route(host="127.0.0.1").pass_through()
            async with httpx.AsyncClient(
                cookies={"session": create_token(owner.id)}, timeout=15
            ) as browser:
                async with browser.stream("GET", f"{live_api}/api/events") as response:
                    lines = response.aiter_lines()
                    assert await anext(lines) == "event: ready"
                    await anext(lines)
                    await anext(lines)
                    assert await bot.handle_update(
                        telegram_update(700, text="Prepare report")
                    )
                    await worker.deliver_outbox()
                    assert (
                        await next_event(lines, "task.created") == "event: task.created"
                    )
                    text_task_id = json.loads(
                        (await anext(lines)).removeprefix("data: ")
                    )["task_id"]
                    await anext(lines)
                    assert any(
                        "Task+created" in text
                        or "Task%20created" in text
                        or "Task created" in text
                        for text in sent
                    )
                    audio = {
                        "file_id": "fixture",
                        "duration": 2,
                        "file_size": len(payload),
                        "mime_type": "audio/ogg",
                    }
                    assert await bot.handle_update(telegram_update(701, audio=audio))
                    assert any("Transcribing" in text for text in sent)
                    async with factory() as session:
                        job = await session.scalar(select(TranscriptionJob))
                    # Durable enqueue crosses real Redis into the Celery worker thread.
                    await worker.deliver_outbox()
                    await wait_job(factory, job.id, "COMPLETED")
                    assert whisper.call_count == 1
                    await worker.deliver_outbox()
                    assert (
                        await next_event(lines, "task.created") == "event: task.created"
                    )
                    voice_id = json.loads((await anext(lines)).removeprefix("data: "))[
                        "task_id"
                    ]
                    # Retrying the delivered queue message cannot create another task.
                    worker.celery_app.send_task("app.worker.transcribe", args=[job.id])
                    await asyncio.sleep(0.2)
                    listing = (await client.get("/api/tasks")).json()
                    assert listing["total"] == 2
                    assert {item["source"] for item in listing["items"]} == {
                        "TELEGRAM_TEXT",
                        "TELEGRAM_VOICE",
                    }
                    assert (
                        await client.patch(
                            f"/api/tasks/{voice_id}", json={"status": "COMPLETED"}
                        )
                    ).json()["completed_at"]
                    assert (
                        await client.delete(f"/api/tasks/{text_task_id}")
                    ).status_code == 204
                    client.cookies.set("session", create_token(other.id))
                    assert (
                        await client.get(f"/api/tasks/{voice_id}")
                    ).status_code == 403
                    async with factory() as session:
                        assert (await session.get(Task, voice_id)).status == "COMPLETED"
                        assert await session.get(Task, text_task_id) is None
                        notices = (
                            await session.scalars(
                                select(Outbox).where(
                                    Outbox.kind == "notification",
                                    Outbox.delivered_at.is_not(None),
                                )
                            )
                        ).all()
                        assert all(row.payload == {} for row in notices)
    finally:
        await asyncio.to_thread(manager.__exit__, None, None, None)


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"text": "", "languages": [{"code": "en"}]}, "invalid_transcript"),
        (
            {"text": "Private text", "languages": [{"code": "fr"}]},
            "unsupported_language",
        ),
    ],
)
async def test_provider_invalid_output_creates_no_task(stack, response, expected):
    factory, redis, client, owner, other = stack
    payload = audio_bytes()
    with aioresponses() as telegram, respx.mock(assert_all_called=False) as provider:
        telegram.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            payload={
                "ok": True,
                "result": {
                    "message_id": 1,
                    "date": 0,
                    "chat": {"id": 1001, "type": "private"},
                    "text": "sent",
                },
            },
            repeat=True,
        )
        provider.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile"
        ).respond(200, json={"ok": True, "result": {"file_path": "voice/fixture.wav"}})
        provider.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/voice/fixture.wav"
        ).respond(200, content=payload)
        provider.post(f"{settings.provider_base_url}/audio/transcriptions").respond(
            200, json=response
        )
        await bot.handle_update(
            telegram_update(
                702,
                audio={
                    "file_id": "fixture",
                    "duration": 2,
                    "file_size": len(payload),
                    "mime_type": "audio/ogg",
                },
            )
        )
        async with factory() as session:
            job = await session.scalar(select(TranscriptionJob))
        await worker.process_job(job.id)
        job = await wait_job(factory, job.id, "FAILED")
        assert job.error_code == expected
        async with factory() as session:
            assert not (await session.scalars(select(Task))).all()
            notice = await session.scalar(
                select(Outbox).where(Outbox.kind == "notification")
            )
            assert "send your task as text" in notice.payload["text"]
