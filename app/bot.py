"""Telegram webhook ingestion. No download or provider I/O occurs here."""

import asyncio
import contextlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audio import AudioError, validate_metadata
from app.config import BOT_MESSAGES_PER_MINUTE, settings
from app.db import Session
from app.logging import configure_logging
from app.models import Outbox, ProcessedUpdate, Task, TranscriptionJob, User
from app.schemas import TaskCreate
from app.services import DomainError, create_task, extract_fields, normalize_text


async def poll_updates(telegram: Bot) -> None:
    offset = None
    failures = 0
    while True:
        try:
            updates = await telegram.get_updates(
                offset=offset,
                timeout=25,
                request_timeout=30,
                allowed_updates=["message"],
            )
            for update in updates:
                await handle_update(
                    update.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
                # Advance only after commit; failures redeliver this update and remaining batch.
                offset = update.update_id + 1
            failures = 0
        except Exception as exc:
            failures += 1
            logger.warning(
                "telegram.polling_failed", extra={"error_code": type(exc).__name__}
            )
            delay = min(60, 2 ** min(failures, 6))
            retry_after = getattr(exc, "retry_after", 0)
            if isinstance(retry_after, int) and 0 < retry_after <= 86400:
                delay = max(delay, retry_after)
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if settings.telegram_mode == "polling" and settings.telegram_bot_token:
        async with Bot(
            settings.telegram_bot_token, session=AiohttpSession(timeout=5, limit=20)
        ) as telegram:
            task = asyncio.create_task(poll_updates(telegram))
            try:
                yield
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    else:
        yield


app = FastAPI(
    title="Telegram task ingestion", docs_url=None, redoc_url=None, lifespan=lifespan
)
logger = logging.getLogger(__name__)
configure_logging()
HELP = (
    "Send a text or voice message to create a task. "
    "For separate fields, say: Title buy milk. Description two bottles. "
    "Due date tomorrow at six PM UTC. Priority high. "
    "Start with Title; description, due date and priority are optional. "
    "Dates use UTC. New tasks start as To do. "
    "Voice audio is transcribed and temporary audio is deleted after processing. "
    "/tasks shows your latest tasks. /login gives a private dashboard login code."
    "\n\nՀայերեն կամ անգլերեն թելադրանքի օրինակ՝ "
    "Վերնագիր Զանգել Աննային։ Նկարագրություն Քննարկել զեկույցը։ "
    "Վերջնաժամկետ վաղը ժամը 14:00 UTC։ Առաջնահերթություն բարձր։ "
    "Կարող ես նաև խառնել երկու լեզուները։ Ժամերը UTC են․ Երևանի 18:00-ը՝ 14:00 UTC։"
)


async def send_message(chat_id: str, text: str) -> None:
    async with Bot(
        settings.telegram_bot_token, session=AiohttpSession(timeout=3, limit=20)
    ) as telegram:
        await telegram.send_message(chat_id=chat_id, text=text[:4000], parse_mode=None)


def reply(session: AsyncSession, user: User, chat_id: str, text: str) -> None:
    session.add(
        Outbox(
            user_id=user.id,
            kind="notification",
            payload={"chat_id": chat_id, "text": text[:4000]},
        )
    )


def valid_telegram_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**63


async def handle_update(update: dict[str, Any]) -> bool:
    if not isinstance(update, dict) or not valid_telegram_id(update.get("update_id")):
        raise ValueError("Invalid update")
    update_id = update["update_id"]
    logger.info("telegram.update", extra={"request_id": f"telegram:{update_id}"})
    async with Session() as session, session.begin():
        if await session.get(ProcessedUpdate, update_id):
            return False
        # The unique primary key serializes concurrent delivery of the same update.
        try:
            async with session.begin_nested():
                receipt = ProcessedUpdate(update_id=update_id)
                session.add(receipt)
                await session.flush()
        except IntegrityError:
            return False
        message = update.get("message")
        if not isinstance(message, dict):
            return True
        sender, chat = message.get("from", {}), message.get("chat", {})
        # Dashboard login codes and personal tasks are only exchanged in private chats.
        if (
            not isinstance(sender, dict)
            or not isinstance(chat, dict)
            or chat.get("type") != "private"
            or not valid_telegram_id(sender.get("id"))
            or chat.get("id") != sender.get("id")
            or sender.get("is_bot")
        ):
            return True
        chat_id = str(chat["id"])
        user = await session.scalar(
            select(User).where(User.telegram_user_id == str(sender["id"]))
        )
        if user is None:
            user = User(
                telegram_user_id=str(sender["id"]),
                first_name=str(sender.get("first_name", "Telegram user"))[:128],
                username=(
                    str(sender["username"])[:64] if sender.get("username") else None
                ),
                last_name=(
                    str(sender["last_name"])[:128] if sender.get("last_name") else None
                ),
                language_code=str(sender.get("language_code", ""))[:16] or None,
            )
            session.add(user)
            await session.flush()
        else:
            for field, limit in (
                ("first_name", 128),
                ("last_name", 128),
                ("username", 64),
                ("language_code", 16),
            ):
                if field in sender:
                    setattr(
                        user,
                        field,
                        (
                            str(sender[field])[:limit]
                            if sender[field] is not None
                            else None
                        ),
                    )
        # Serialize per-user admission in PostgreSQL so text still works during Redis outages.
        await session.execute(
            select(User.id).where(User.id == user.id).with_for_update(key_share=True)
        )
        receipt.user_id = user.id
        count = await session.scalar(
            select(func.count())
            .select_from(ProcessedUpdate)
            .where(
                ProcessedUpdate.user_id == user.id,
                ProcessedUpdate.created_at >= datetime.now(UTC) - timedelta(seconds=60),
            )
        )
        if (count or 0) > BOT_MESSAGES_PER_MINUTE:
            if count == BOT_MESSAGES_PER_MINUTE + 1:
                reply(
                    session,
                    user,
                    chat_id,
                    "Too many messages. Please wait a minute and try again.",
                )
            return True
        text = message.get("text")
        command = (
            text.split(maxsplit=1)[0].split("@", 1)[0]
            if isinstance(text, str) and text.strip()
            else ""
        )
        if command in {"/start", "/help"}:
            reply(session, user, chat_id, HELP)
        elif command == "/login":
            from app.auth import issue_login_code

            code = await issue_login_code(session, user.id)
            reply(
                session,
                user,
                chat_id,
                f"Your dashboard login code: {code}\nValid for 5 minutes. Do not share this code.",
            )
        elif command == "/tasks":
            tasks = (
                await session.scalars(
                    select(Task)
                    .where(Task.user_id == user.id)
                    .order_by(Task.created_at.desc())
                    .limit(10)
                )
            ).all()
            reply(
                session,
                user,
                chat_id,
                "\n".join(f"{task.status}: {task.title}" for task in tasks)
                or "No tasks yet. Send text or voice to create one.",
            )
        elif isinstance(text, str):
            try:
                if text.startswith("/"):
                    reply(session, user, chat_id, HELP)
                else:
                    task = await create_task(
                        session,
                        user.id,
                        TaskCreate(**extract_fields(normalize_text(text))),
                        source="TELEGRAM_TEXT",
                        source_key=f"telegram:{update_id}",
                    )
                    reply(session, user, chat_id, f"✅ Task created: {task.title}")
            except (DomainError, ValueError):
                reply(
                    session,
                    user,
                    chat_id,
                    "Please send task text containing 1–5000 characters.",
                )
        elif isinstance(message.get("voice") or message.get("audio"), dict):
            audio = message.get("voice") or message["audio"]
            try:
                from app.worker import enforce_admission

                validate_metadata(
                    audio.get("duration"),
                    audio.get("file_size"),
                    audio.get(
                        "mime_type", "audio/ogg" if message.get("voice") else None
                    ),
                )
                file_id = audio.get("file_id")
                if not isinstance(file_id, str) or not 1 <= len(file_id) <= 512:
                    raise AudioError("missing_file")
                await enforce_admission(session, user)
                # A successful acknowledgement precedes any committed queue effect.
                await send_message(
                    chat_id, "🎙 Voice message received. Transcribing your task…"
                )
                job = TranscriptionJob(
                    user_id=user.id,
                    telegram_file_id=file_id,
                    chat_id=chat_id,
                    audio_duration_sec=audio["duration"],
                    audio_file_size_bytes=audio["file_size"],
                    mime_type=audio.get("mime_type", "audio/ogg"),
                    model_name=settings.whisper_model,
                    status="QUEUED",
                )
                session.add(job)
                await session.flush()
                session.add(
                    Outbox(
                        user_id=user.id, kind="transcribe", payload={"job_id": job.id}
                    )
                )
                logger.info(
                    "transcription.queued", extra={"job_id": job.id, "status": "QUEUED"}
                )
            except AudioError:
                reply(
                    session,
                    user,
                    chat_id,
                    f"Please send supported audio lasting {settings.min_audio_duration_sec}–{settings.max_audio_duration_sec} seconds and under {settings.max_audio_file_size_mb} MB, or send text.",
                )
            except DomainError as exc:
                reply(session, user, chat_id, str(exc))
        else:
            reply(
                session,
                user,
                chat_id,
                "⚠️ Unsupported message type. Please send a text or voice message to create a task.",
            )
    return True


@app.post("/telegram/webhook")
async def webhook(request: Request) -> dict[str, bool]:
    if not settings.webhook_secret or not hmac.compare_digest(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").encode(),
        settings.webhook_secret.encode(),
    ):
        raise HTTPException(403, "Invalid webhook secret")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise HTTPException(413, "Update too large")
    try:
        await handle_update(json.loads(body))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid Telegram update") from None
    except Exception:
        logger.error("telegram.ingestion_failed")
        raise HTTPException(503, "Please retry later") from None
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.bot:app", host="0.0.0.0", port=8001)
