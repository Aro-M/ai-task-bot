"""Owner-scoped dashboard API and authenticated event stream."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import (
    COOKIE_NAME,
    SESSION_SECONDS,
    consume_login_code,
    create_token,
    verify_token,
)
from app.config import settings
from app.db import Session, get_session
from app.logging import configure_logging, exception_context
from app.models import JobStatus, Outbox, Task, TranscriptionJob, User
from app.schemas import JobOut, TaskCreate, TaskOut, TaskPatch
from app.services import DomainError, create_task, delete_task, owned_task, update_task

app = FastAPI(
    title="AI Task Bot", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
configure_logging()
logger = logging.getLogger(__name__)


@app.middleware("http")
async def trusted_origin(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.monotonic()
    request_id = str(uuid4())
    request.state.request_id = request_id
    response: Response
    try:
        if (
            request.url.path.startswith("/api/")
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("origin") != settings.frontend_origin
        ):
            response = error_response(request, 403, "Untrusted request origin")
        else:
            response = await call_next(request)
    except Exception as exc:
        # Exception text may contain SQL parameters or task text; log only its type.
        logger.error(
            "request.failed",
            extra={
                "request_id": request_id,
                "error_code": type(exc).__name__,
                "stack": exception_context(exc),
            },
        )
        response = await unexpected_error(request, exc)
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": response.headers.get("Cache-Control", "no-store"),
        }
    )
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    logger.info(
        "request.finished",
        extra={
            "request_id": request_id,
            "status": response.status_code,
            "latency_ms": round((time.monotonic() - started) * 1000),
        },
    )
    try:
        async with asyncio.timeout(0.1):
            await cast(
                Awaitable[int],
                get_redis().eval(
                    "redis.call('HINCRBY',KEYS[1],'requests',1); redis.call('HINCRBY',KEYS[1],'errors',ARGV[1]); redis.call('EXPIRE',KEYS[1],604800); return 1",
                    1,
                    f"api:metrics:{datetime.now(UTC):%Y-%m-%d}",
                    str(int(response.status_code >= 400)),
                ),
            )
    except (TimeoutError, RedisError, OSError):
        pass
    return response


def error_response(
    request: Request,
    status: int,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    codes = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }
    code = (
        "TASK_NOT_FOUND"
        if status == 404 and request.url.path.startswith("/api/tasks/")
        else codes.get(status, "INTERNAL_ERROR")
    )
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": getattr(request.state, "request_id", str(uuid4())),
            },
            "detail": message,
        },
        status_code=status,
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(request, exc.status_code, str(exc.detail), exc.headers)


@app.exception_handler(DomainError)
async def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    return error_response(_request, exc.status_code, str(exc))


@app.exception_handler(RequestValidationError)
async def invalid_request(
    _request: Request, _exc: RequestValidationError
) -> JSONResponse:
    return error_response(_request, 422, "Invalid request data")


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(TimeoutError)
async def database_error(
    _request: Request, _exc: SQLAlchemyError | TimeoutError
) -> JSONResponse:
    return error_response(_request, 503, "Database temporarily unavailable")


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    return error_response(_request, 500, "Unexpected server error")


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=100,
        socket_connect_timeout=2,
        socket_timeout=3,
    )


async def rate_limit(key: str, limit: int, seconds: int) -> None:
    try:
        count = await cast(
            Awaitable[int],
            get_redis().eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                1,
                f"api:rate:{key}",
                str(seconds),
            ),
        )
    except (TimeoutError, RedisError, OSError) as exc:
        raise HTTPException(503, "Request limiting temporarily unavailable") from exc
    if count > limit:
        raise HTTPException(
            429, "Too many requests", headers={"Retry-After": str(seconds)}
        )


SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


async def get_current_user(request: Request, session: SessionDep) -> User:
    try:
        user_id = verify_token(request.cookies.get(COOKIE_NAME, ""))
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    await rate_limit(f"user:{user_id}", 120, 60)
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(401, "Invalid or expired session")
    return user


UserDep = Annotated[User, Depends(get_current_user)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{8}$")


def user_info(user: User) -> dict[str, str | None]:
    return {
        "id": user.id,
        "first_name": user.first_name,
        "username": user.username,
        "telegram_user_id": user.telegram_user_id,
    }


@app.post("/api/auth/login")
async def login(
    data: LoginRequest, request: Request, response: Response, session: SessionDep
) -> dict[str, str | None]:
    address = request.client.host if request.client else "unknown"
    await rate_limit(f"login:{address}", 5, 60)
    user_id = await consume_login_code(session, data.code)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired login code")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(401, "Invalid or expired login code")
    await session.commit()
    response.set_cookie(
        COOKIE_NAME,
        create_token(user.id),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path="/api",
    )
    response.headers["Cache-Control"] = "no-store"
    return user_info(user)


@app.get("/api/auth/me")
async def me(user: UserDep, response: Response) -> dict[str, str | None]:
    response.headers["Cache-Control"] = "no-store"
    return user_info(user)


@app.post("/api/auth/logout", status_code=204)
async def logout(response: Response, user: UserDep) -> None:
    response.delete_cookie(COOKIE_NAME, path="/api", samesite="strict")


@app.delete("/api/auth/me", status_code=204)
async def delete_account(
    response: Response, user: UserDep, session: SessionDep
) -> None:
    await session.execute(select(User).where(User.id == user.id).with_for_update())
    await session.delete(user)
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/api", samesite="strict")


@app.get("/api/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/api/health/ready")
async def readiness(session: SessionDep) -> dict[str, str]:
    await session.execute(select(1))
    try:
        redis = get_redis()
        await redis.ping()
        if not all(
            [
                await redis.exists(f"worker:alive:{role}")
                for role in ("transcription", "notifications")
            ]
        ):
            raise HTTPException(503, "Background workers unavailable")
    except (RedisError, OSError) as exc:
        raise HTTPException(503, "Redis temporarily unavailable") from exc
    return {
        "status": "ready",
        "configuration": "validated",
        "postgres": "ok",
        "redis": "ok",
        "workers": "ok",
    }


@app.get("/api/health")
async def health(request: Request, session: SessionDep) -> Any:
    try:
        await session.execute(select(1))
        await get_redis().ping()
    except (TimeoutError, SQLAlchemyError, RedisError, OSError):
        return error_response(request, 503, "Dependencies temporarily unavailable")
    return {"status": "ok"}


@app.get("/api/tasks")
async def tasks(
    user: UserDep,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Literal["PENDING", "IN_PROGRESS", "COMPLETED"] | None = None,
    source: (
        Literal[
            "telegram_text",
            "telegram_voice",
            "dashboard",
            "TELEGRAM_TEXT",
            "TELEGRAM_VOICE",
            "DASHBOARD",
        ]
        | None
    ) = None,
    sort: Literal[
        "created_at_desc", "created_at_asc", "updated_at_desc", "due_date_asc"
    ] = "created_at_desc",
    search: str | None = Query(None, max_length=200),
) -> dict[str, Any]:
    filters = [Task.user_id == user.id]
    if status:
        filters.append(Task.status == status)
    if source:
        filters.append(Task.source == source.upper())
    orderings: dict[str, Any] = {
        "created_at_desc": Task.created_at.desc(),
        "created_at_asc": Task.created_at.asc(),
        "updated_at_desc": Task.updated_at.desc(),
        "due_date_asc": Task.due_date.asc().nullslast(),
    }
    ordering = orderings[sort]
    if search:
        term = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(
            or_(
                Task.title.ilike(f"%{term}%", escape="\\"),
                Task.description.ilike(f"%{term}%", escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(Task).where(*filters))
    rows = (
        await session.scalars(
            select(Task)
            .where(*filters)
            .order_by(ordering, Task.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [TaskOut.model_validate(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ((total or 0) + page_size - 1) // page_size,
    }


@app.get("/api/tasks/stats")
async def task_stats(user: UserDep, session: SessionDep) -> dict[str, Any]:
    rows = await session.execute(
        select(Task.status, func.count())
        .where(Task.user_id == user.id)
        .group_by(Task.status)
    )
    counts = {row[0]: row[1] for row in rows}
    return {
        "total": sum(counts.values()),
        "by_status": {
            status: counts.get(status, 0)
            for status in ("PENDING", "IN_PROGRESS", "COMPLETED")
        },
    }


@app.post("/api/tasks", response_model=TaskOut, status_code=201)
async def add_task(data: TaskCreate, user: UserDep, session: SessionDep) -> Task:
    task = await create_task(session, user.id, data)
    await session.commit()
    return task


@app.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: UUID, user: UserDep, session: SessionDep) -> Task:
    return await owned_task(session, user.id, str(task_id))


@app.patch("/api/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: UUID, data: TaskPatch, user: UserDep, session: SessionDep
) -> Task:
    task = await owned_task(session, user.id, str(task_id))
    await update_task(session, task, data)
    await session.commit()
    return task


@app.delete("/api/tasks/{task_id}", status_code=204)
async def remove_task(task_id: UUID, user: UserDep, session: SessionDep) -> None:
    task = await owned_task(session, user.id, str(task_id))
    await delete_task(session, task)
    await session.commit()


@app.get("/api/jobs", response_model=list[JobOut])
async def jobs(
    user: UserDep,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Sequence[TranscriptionJob]:
    return (
        await session.scalars(
            select(TranscriptionJob)
            .where(TranscriptionJob.user_id == user.id)
            .order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()


@app.post("/api/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: UUID, user: UserDep, session: SessionDep
) -> TranscriptionJob:
    from app.worker import enforce_admission

    # Serialize admissions without blocking the worker's foreign-key reads.
    await session.execute(
        select(User).where(User.id == user.id).with_for_update(key_share=True)
    )
    job = await session.scalar(
        select(TranscriptionJob)
        .where(TranscriptionJob.id == str(job_id))
        .with_for_update()
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.user_id != user.id:
        raise HTTPException(403, "Job belongs to another user")
    if job.status not in {"FAILED", "TIMED_OUT"}:
        raise HTTPException(409, "Only failed or timed-out jobs can be retried")
    from app.config import JOB_TTL, MAX_JOB_RETRIES

    if (
        job.retry_count >= MAX_JOB_RETRIES
        or (datetime.now(UTC) - job.created_at).total_seconds() >= JOB_TTL
    ):
        raise HTTPException(
            409, "Retry limit or job lifetime reached. Send a new message."
        )
    await enforce_admission(session, user, exclude_job_id=job.id)
    job.status = JobStatus.QUEUED
    job.error_code = job.error_message = None
    job.started_at = job.completed_at = None
    job.retry_count += 1
    session.add(Outbox(user_id=user.id, kind="transcribe", payload={"job_id": job.id}))
    await session.commit()
    return job


@app.get("/api/events")
async def events(request: Request, user: UserDep) -> StreamingResponse:
    pubsub = get_redis().pubsub()
    try:
        await pubsub.subscribe(f"user:{user.id}:events")
    except (TimeoutError, RedisError, OSError) as exc:
        await pubsub.aclose()
        raise HTTPException(503, "Events temporarily unavailable") from exc

    async def stream() -> AsyncIterator[str]:
        try:
            yield "event: ready\ndata: {}\n\n"
            deadline = time.monotonic() + SESSION_SECONDS
            while time.monotonic() < deadline and not await request.is_disconnected():
                try:
                    verify_token(request.cookies.get(COOKIE_NAME, ""))
                    async with Session() as event_session:
                        if (
                            await event_session.scalar(
                                select(User.id).where(User.id == user.id)
                            )
                            is None
                        ):
                            break
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=2
                    )
                except (
                    TimeoutError,
                    RedisError,
                    OSError,
                    SQLAlchemyError,
                    jwt.InvalidTokenError,
                ):
                    break
                if message is None:
                    yield ": keepalive\n\n"
                    continue
                try:
                    data = json.loads(message["data"])
                    kind = data["event"]
                    if kind not in {
                        "task.created",
                        "task.updated",
                        "task.deleted",
                        "job.updated",
                        "transcription.started",
                        "transcription.completed",
                        "transcription.failed",
                    }:
                        continue
                    safe = {
                        key: data[key]
                        for key in ("event", "task_id", "job_id")
                        if key in data
                    }
                except (ValueError, TypeError, KeyError):
                    continue
                yield f"event: {kind}\ndata: {json.dumps(safe)}\n\n"
        finally:
            await pubsub.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
