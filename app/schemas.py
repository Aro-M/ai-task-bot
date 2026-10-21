import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import JobStatus, Priority, TaskSource, TaskStatus


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    # Preserve visible user text while removing control and invisible formatting characters.
    return " ".join(
        "".join(
            c
            for c in text
            if not unicodedata.category(c).startswith("C") or c.isspace()
        ).split()
    )


class TaskFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "description", check_fields=False, mode="before")
    @classmethod
    def clean_text_fields(cls, value: Any) -> Any:
        return normalize_text(value) if isinstance(value, str) else value

    @field_validator("due_date", check_fields=False)
    @classmethod
    def aware_due_date(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("due_date requires an explicit timezone")
            value = value.astimezone(UTC)
        return value


class TaskCreate(TaskFields):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None
    priority: Priority | None = None


class TaskPatch(TaskFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None

    @model_validator(mode="after")
    def nonempty_valid_patch(self) -> "TaskPatch":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field")
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    description: str | None
    status: TaskStatus
    source: TaskSource
    due_date: datetime | None
    priority: Priority | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    audio_duration_sec: float
    audio_file_size_bytes: int
    status: JobStatus
    error_code: str | None
    error_message: str | None
    model_name: str
    detected_language: str | None
    latency_ms: int | None
    retry_count: int
    estimated_cost: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
