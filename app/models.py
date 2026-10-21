"""Relational ownership, idempotency, and durable effects."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite drops timezone metadata; restore the same UTC invariant on both databases."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime must include a timezone")
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class TaskSource(StrEnum):
    DASHBOARD = "DASHBOARD"
    TELEGRAM_TEXT = "TELEGRAM_TEXT"
    TELEGRAM_VOICE = "TELEGRAM_VOICE"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Base(DeclarativeBase):
    pass


def uuid_column() -> Any:
    return mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = uuid_column()
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(256))
    last_name: Mapped[str | None] = mapped_column(String(256))
    language_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_created", "user_id", "created_at"),
        Index("ix_tasks_user_status", "user_id", "status"),
    )

    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, create_constraint=True),
        default=TaskStatus.PENDING,
    )
    source: Mapped[TaskSource] = mapped_column(
        Enum(TaskSource, native_enum=False, create_constraint=True)
    )
    due_date: Mapped[datetime | None] = mapped_column(UTCDateTime())
    priority: Mapped[Priority | None] = mapped_column(
        Enum(Priority, native_enum=False, create_constraint=True)
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_key: Mapped[str | None] = mapped_column(String(128), unique=True)


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE")
    )
    telegram_file_id: Mapped[str] = mapped_column(String(512))
    chat_id: Mapped[str] = mapped_column(String(32))
    audio_duration_sec: Mapped[float]
    audio_file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, create_constraint=True),
        default=JobStatus.QUEUED,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    model_name: Mapped[str] = mapped_column(String(128))
    detected_language: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_delivery", "delivered_at", "created_at"),)

    id: Mapped[str] = uuid_column()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))


class LoginCode(Base):
    __tablename__ = "login_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"
    __table_args__ = (Index("ix_updates_user_created", "user_id", "created_at"),)

    update_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )

    user_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now()
    )
