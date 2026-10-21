"""A locked database transaction owns each job and its durable effects."""

import asyncio
import logging
import random
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from celery import Celery
from celery.signals import after_setup_logger, heartbeat_sent
from redis import Redis as SyncRedis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai import TaskParserError, parse_task
from app.audio import (
    AudioError,
    convert_audio,
    download_audio,
    inspect_audio,
    transcribe_audio,
)
from app.config import (
    DEAD_LETTER_DAYS,
    JOB_TTL,
    MAX_JOB_RETRIES,
    MAX_OUTBOX_ATTEMPTS,
    settings,
)
from app.db import CONNECT_ARGS
from app.events import job_id_from_payload, publish_event
from app.logging import configure_logging, exception_context
from app.models import JobStatus, Outbox, Task, TranscriptionJob, User
from app.services import DomainError, clean_transcript, create_task
from app.timezone import TASK_TIMEZONE

logger = logging.getLogger(__name__)
configure_logging()


@after_setup_logger.connect
def worker_logging(**kwargs: Any) -> None:
    configure_logging()


@heartbeat_sent.connect
def worker_heartbeat(sender: Any, **kwargs: Any) -> None:
    role = sender.eventer.hostname.split("@", 1)[0]
    if role not in {"transcription", "notifications"}:
        return
    try:
        with SyncRedis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            max_connections=2,
        ) as redis:
            redis.set(f"worker:alive:{role}", "1", ex=60)
    except (RedisError, OSError):
        logger.warning("worker.heartbeat_failed", extra={"kind": role})


worker_engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,
    connect_args=CONNECT_ARGS,
    hide_parameters=True,
)
WorkerSession = async_sessionmaker(worker_engine, expire_on_commit=False)
celery_app = Celery("ai-task-bot", broker=settings.redis_url)
celery_app.conf.update(
    imports=("app.bot",),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_pool_limit=10,
    task_default_queue="transcription",
    task_routes={"app.worker.dispatch_outbox": {"queue": "notifications"}},
    broker_transport_options={
        "visibility_timeout": max(300, settings.transcription_job_timeout_sec * 3),
        "socket_timeout": 3,
        "socket_connect_timeout": 3,
        "max_connections": 20,
    },
    beat_schedule={
        "deliver-outbox": {
            "task": "app.worker.dispatch_outbox",
            "schedule": 1.0,
            "options": {"expires": 5},
        }
    },
)
FALLBACK = "❌ We couldn’t transcribe your voice message. Please try again, speak more clearly, or send your task as text."


async def enforce_admission(
    session: AsyncSession, user: User, exclude_job_id: str | None = None
) -> None:
    await session.execute(
        select(User.id).where(User.id == user.id).with_for_update(key_share=True)
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # Serialize cross-user admissions; all callers already hold their own owner lock.
        await session.execute(text("SELECT pg_advisory_xact_lock(817263)"))
    total = await session.scalar(
        select(func.count())
        .select_from(TranscriptionJob)
        .where(TranscriptionJob.status.in_(["QUEUED", "RETRYING", "PROCESSING"]))
    )
    if (total or 0) >= settings.global_queued_jobs_limit:
        raise DomainError("Voice queue is busy. Please send your task as text.", 429)
    active = (
        select(func.count())
        .select_from(TranscriptionJob)
        .where(
            TranscriptionJob.user_id == user.id,
            TranscriptionJob.status.in_(["QUEUED", "RETRYING", "PROCESSING"]),
        )
    )
    if exclude_job_id:
        active = active.where(TranscriptionJob.id != exclude_job_id)
    if (await session.scalar(active) or 0) >= settings.concurrent_jobs_per_user:
        raise DomainError(
            "Please wait for your current voice tasks to finish, or send text.", 429
        )
    now = datetime.now(UTC)
    for since, limit in (
        (now - timedelta(hours=1), settings.hourly_transcription_limit),
        (
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            settings.daily_transcription_limit,
        ),
    ):
        count = await session.scalar(
            select(func.count())
            .select_from(Outbox)
            .where(
                Outbox.user_id == user.id,
                Outbox.kind == "transcribe",
                Outbox.created_at >= since,
            )
        )
        if (count or 0) >= limit:
            raise DomainError(
                "Your voice transcription limit has been reached. Please send your task as text.",
                429,
            )


def notify(session: AsyncSession, user_id: str, chat_id: str, text: str) -> None:
    session.add(
        Outbox(
            user_id=user_id,
            kind="notification",
            payload={"chat_id": str(chat_id), "text": text},
        )
    )


async def locked_job(session: AsyncSession, job_id: str) -> TranscriptionJob | None:
    owner_id = await session.scalar(
        select(TranscriptionJob.user_id).where(TranscriptionJob.id == job_id)
    )
    if owner_id is None:
        return None
    # Every job writer locks owner before job, matching account deletion's cascade order.
    owner_id = await session.scalar(
        select(User.id)
        .where(User.id == owner_id)
        .with_for_update(read=True, key_share=True, skip_locked=True)
    )
    if owner_id is None:
        return None
    return await session.scalar(
        select(TranscriptionJob)
        .where(TranscriptionJob.id == job_id)
        .with_for_update(skip_locked=True)
    )


def fail_job(session: AsyncSession, job: TranscriptionJob, code: str) -> None:
    job.status = JobStatus.DEAD_LETTER if code == "dead_letter" else JobStatus.FAILED
    job.error_code = code
    job.error_message = "Voice task expired or exhausted retries. Please send text."
    job.completed_at = datetime.now(UTC)
    logger.warning(
        "transcription.dead_letter",
        extra={"job_id": job.id, "error_code": code, "retry_count": job.retry_count},
    )
    notify(session, job.user_id, job.chat_id, FALLBACK)
    session.add(
        Outbox(
            user_id=job.user_id,
            kind="event",
            payload={
                "event": "transcription.failed",
                "job_id": job.id,
                "user_id": job.user_id,
            },
        )
    )


async def process_job(job_id: str) -> None:
    async with WorkerSession() as session, session.begin():
        job = await locked_job(session, job_id)
        if job is None or job.status not in {"QUEUED", "RETRYING"}:
            return
        if (datetime.now(UTC) - job.created_at).total_seconds() >= JOB_TTL:
            fail_job(session, job, "expired")
            return
        job.status, job.started_at = JobStatus.PROCESSING, datetime.now(UTC)
        session.add(
            Outbox(
                user_id=job.user_id,
                kind="event",
                payload={
                    "event": "transcription.started",
                    "job_id": job.id,
                    "user_id": job.user_id,
                },
            )
        )
    try:
        await _process_job(job_id)
    except Exception:
        # The processing transaction rolled back; persist the retry budget separately.
        async with WorkerSession() as session, session.begin():
            job = await locked_job(session, job_id)
            if job is None or job.status != "PROCESSING":
                return
            if job.retry_count >= MAX_JOB_RETRIES:
                fail_job(session, job, "dead_letter")
                return
            job.retry_count += 1
            job.status = JobStatus.RETRYING
        raise


async def _process_job(job_id: str) -> None:
    started = time.monotonic()
    async with WorkerSession() as session, session.begin():
        job = await locked_job(session, job_id)
        if job is None or job.status != "PROCESSING":
            return
        if await session.scalar(
            select(Task.id).where(Task.source_key == f"voice:{job.id}")
        ):
            job.status = JobStatus.COMPLETED
            return
        if (datetime.now(UTC) - job.created_at).total_seconds() >= JOB_TTL:
            fail_job(session, job, "expired")
            return
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        logger.info(
            "transcription.started", extra={"job_id": job.id, "status": job.status}
        )
        try:
            async with asyncio.timeout(settings.transcription_job_timeout_sec):
                with tempfile.TemporaryDirectory(prefix="task-voice-") as directory:
                    path = Path(directory) / "voice"
                    await download_audio(job.telegram_file_id, path)
                    duration = await inspect_audio(path)
                    canonical = await convert_audio(path)
                    transcript, language = await transcribe_audio(canonical)
                job.audio_duration_sec = duration
                job.detected_language = language
                job.estimated_cost = duration / 60 * settings.whisper_cost_per_minute
                text = clean_transcript(transcript)
                armenian = language in {"hy", "armenian", "Armenian"}
                data = await parse_task(text)
                if data is None:
                    job.status = JobStatus.COMPLETED
                    notify(
                        session,
                        job.user_id,
                        job.chat_id,
                        (
                            "Ձայնը լսեցի, բայց առաջադրանքի գործողություն չգտա։ "
                            "Ասա՝ ինչ պետք է անեմ։"
                            if armenian
                            else "I heard your message, but couldn't identify a task. "
                            "Tell me what action to add."
                        ),
                    )
                else:
                    task = await create_task(
                        session,
                        job.user_id,
                        data,
                        source="TELEGRAM_VOICE",
                        source_key=f"voice:{job.id}",
                    )
                    job.status = JobStatus.COMPLETED
                    created_label, description_label, due_label, priority_label = (
                        (
                            "✅ Ձայնից ստեղծվեց առաջադրանք՝",
                            "Նկարագրություն",
                            "Վերջնաժամկետ (Երևանի ժամանակով)",
                            "Առաջնահերթություն",
                        )
                        if armenian
                        else (
                            "✅ Task created from your voice message:",
                            "Description",
                            "Due date (Yerevan time)",
                            "Priority",
                        )
                    )
                    confirmation = [f"{created_label}\n{task.title}"]
                    if task.description:
                        preview = task.description[:1000]
                        if len(task.description) > 1000:
                            preview += (
                                "… (ամբողջ նկարագրությունը՝ վահանակում)"
                                if armenian
                                else "… (full description in dashboard)"
                            )
                        confirmation.append(f"{description_label}: {preview}")
                    if task.due_date:
                        due_date = task.due_date.astimezone(TASK_TIMEZONE)
                        confirmation.append(f"{due_label}: {due_date:%Y-%m-%d %H:%M}")
                    if task.priority:
                        priority = (
                            {"HIGH": "բարձր", "MEDIUM": "միջին", "LOW": "ցածր"}[
                                task.priority
                            ]
                            if armenian
                            else task.priority
                        )
                        confirmation.append(f"{priority_label}: {priority}")
                    notify(session, job.user_id, job.chat_id, "\n".join(confirmation))
        except TimeoutError:
            job.status, job.error_code = JobStatus.TIMED_OUT, "timeout"
            job.error_message = "Transcription exceeded the time limit."
            notify(session, job.user_id, job.chat_id, FALLBACK)
        except (AudioError, DomainError, ValueError, httpx.HTTPError) as exc:
            job.status = (
                JobStatus.DEAD_LETTER
                if isinstance(exc, AudioError)
                and exc.code in {"provider_unavailable", "download_unavailable"}
                else JobStatus.FAILED
            )
            if isinstance(exc, AudioError):
                job.error_code = exc.code
            elif isinstance(exc, TaskParserError):
                job.error_code = "task_parse_failed"
            elif isinstance(exc, httpx.HTTPError):
                job.error_code = "download_failed"
            else:
                job.error_code = "invalid_transcript"
            job.error_message = "Audio could not be converted into a task."
            notify(
                session,
                job.user_id,
                job.chat_id,
                (
                    (
                        str(exc)
                        if isinstance(exc, TaskParserError)
                        else f"❌ {exc}. Please send your task as text."
                    )
                    if isinstance(exc, DomainError)
                    else FALLBACK
                ),
            )
        except Exception as exc:
            # Roll back on infrastructure failure; late acknowledgement/redelivery retries the job.
            logger.error(
                "transcription.infrastructure_failure",
                extra={
                    "job_id": job.id,
                    "error_code": type(exc).__name__,
                    "stack": exception_context(exc),
                },
            )
            raise
        if (
            job.status in {JobStatus.FAILED, JobStatus.TIMED_OUT}
            and job.retry_count >= MAX_JOB_RETRIES
        ):
            job.error_message = (
                f"Retry budget exhausted ({job.error_code}). Please send text."
            )
            job.status, job.error_code = JobStatus.DEAD_LETTER, "dead_letter"
        job.completed_at = datetime.now(UTC)
        job.latency_ms = round((time.monotonic() - started) * 1000)
        session.add(
            Outbox(
                user_id=job.user_id,
                kind="event",
                payload={
                    "event": (
                        "transcription.completed"
                        if job.status == JobStatus.COMPLETED
                        else "transcription.failed"
                    ),
                    "job_id": job.id,
                    "user_id": job.user_id,
                },
            )
        )
        logger.info(
            "transcription.finished",
            extra={
                "job_id": job.id,
                "status": job.status,
                "error_code": job.error_code,
                "latency_ms": job.latency_ms,
                "retry_count": job.retry_count,
            },
        )


async def deliver_outbox(limit: int = 10) -> None:
    from app.bot import send_message

    # One row per transaction: a crash releases its lock without acknowledging its effect.
    failed_ids: list[str] = []
    for _ in range(limit):
        async with WorkerSession() as session, session.begin():
            row = await session.scalar(
                select(Outbox)
                .where(
                    Outbox.delivered_at.is_(None),
                    Outbox.id.not_in(failed_ids),
                    Outbox.available_at <= datetime.now(UTC),
                )
                .order_by(Outbox.attempts, Outbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                break
            if (datetime.now(UTC) - row.created_at).total_seconds() >= JOB_TTL:
                row.error_code, row.payload = "expired", {}
                row.delivered_at = datetime.now(UTC)
                continue
            row.attempts += 1
            try:
                if row.kind == "event":
                    await publish_event(row.user_id, row.payload)
                elif row.kind in {"transcribe", "transcribe.recover"}:
                    celery_app.send_task(
                        "app.worker.transcribe",
                        args=[job_id_from_payload(row.payload)],
                        retry=False,
                    )
                elif row.kind == "notification":
                    await send_message(row.payload["chat_id"], row.payload["text"])
                    row.payload = {}
                else:
                    raise ValueError("Unknown outbox kind")
                row.delivered_at = datetime.now(UTC)
            except Exception as exc:
                logger.warning(
                    "outbox.delivery_failed",
                    extra={"outbox_id": row.id, "kind": row.kind},
                )
                # Preserve the failed attempt and its retry deadline across restarts.
                failed_ids.append(row.id)
                if row.attempts >= MAX_OUTBOX_ATTEMPTS:
                    row.error_code, row.payload = "exhausted", {}
                    row.delivered_at = datetime.now(UTC)
                else:
                    retry_after = getattr(exc, "retry_after", 0)
                    delay = random.uniform(1, min(60, 2**row.attempts))
                    if (
                        isinstance(retry_after, (int, float))
                        and 0 < retry_after <= JOB_TTL
                    ):
                        delay = max(delay, retry_after)
                    row.available_at = datetime.now(UTC) + timedelta(seconds=delay)
    await recover_queued_jobs()
    async with WorkerSession() as session, session.begin():
        cutoff = datetime.now(UTC) - timedelta(days=DEAD_LETTER_DAYS)
        await session.execute(
            delete(Outbox).where(
                Outbox.error_code.is_not(None), Outbox.delivered_at < cutoff
            )
        )
        await session.execute(
            delete(TranscriptionJob).where(
                (TranscriptionJob.status == "DEAD_LETTER")
                | (
                    (TranscriptionJob.status == "FAILED")
                    & TranscriptionJob.error_code.in_(["dead_letter", "expired"])
                ),
                TranscriptionJob.completed_at < cutoff,
            )
        )


async def recover_queued_jobs() -> None:
    cutoff = datetime.now(UTC) - timedelta(
        seconds=max(300, settings.transcription_job_timeout_sec * 3)
    )
    async with WorkerSession() as session, session.begin():
        job_ids = (
            await session.scalars(
                select(TranscriptionJob.id)
                .where(
                    TranscriptionJob.status.in_(["QUEUED", "RETRYING", "PROCESSING"]),
                    TranscriptionJob.created_at < cutoff,
                )
                .order_by(TranscriptionJob.created_at)
                .limit(100)
            )
        ).all()
        for job_id in job_ids:
            job = await locked_job(session, job_id)
            if (
                job is None
                or job.status not in {"QUEUED", "RETRYING", "PROCESSING"}
                or job.created_at >= cutoff
            ):
                continue
            if (datetime.now(UTC) - job.created_at).total_seconds() >= JOB_TTL:
                fail_job(session, job, "expired")
                continue
            if (
                job.status == "PROCESSING"
                and job.started_at is not None
                and job.started_at >= cutoff
            ):
                continue
            last = await session.scalar(
                select(Outbox)
                .where(
                    Outbox.kind.in_(["transcribe", "transcribe.recover"]),
                    Outbox.payload["job_id"].as_string() == job.id,
                )
                .order_by(Outbox.created_at.desc())
                .limit(1)
            )
            if last is None or (
                last.delivered_at is not None
                and last.delivered_at.replace(tzinfo=UTC) < cutoff
            ):
                if job.retry_count >= MAX_JOB_RETRIES:
                    fail_job(session, job, "dead_letter")
                    continue
                job.retry_count += 1
                job.status = JobStatus.RETRYING
                session.add(
                    Outbox(
                        user_id=job.user_id,
                        kind="transcribe.recover",
                        payload={"job_id": job.id},
                    )
                )


@celery_app.task(
    name="app.worker.transcribe",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=MAX_JOB_RETRIES,
    soft_time_limit=settings.transcription_job_timeout_sec + 20,
    time_limit=settings.transcription_job_timeout_sec + 30,
)
def transcribe(self: Any, job_id: str) -> None:
    asyncio.run(process_job(job_id))


@celery_app.task(name="app.worker.dispatch_outbox", soft_time_limit=90, time_limit=100)
def dispatch_outbox() -> None:
    asyncio.run(deliver_outbox())
