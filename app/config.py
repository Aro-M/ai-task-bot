"""Validated environment configuration shared by every process."""

import secrets
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

JOB_TTL = 86400
MAX_JOB_RETRIES = 3
DEAD_LETTER_DAYS = 7
MAX_OUTBOX_ATTEMPTS = 12
BOT_MESSAGES_PER_MINUTE = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    database_url: str = "sqlite+aiosqlite:///./taskbot.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    telegram_bot_token: str = ""
    telegram_mode: Literal["polling", "webhook"] = "webhook"
    webhook_secret: str = ""
    openai_api_key: str = ""
    provider_base_url: str = "https://api.openai.com/v1"
    whisper_model: str = "whisper-1"
    whisper_language: str = "auto"
    whisper_timeout_sec: int = Field(default=45, ge=1, le=600)
    whisper_max_retries: int = Field(default=3, ge=1, le=5)
    whisper_retry_backoff_base: float = Field(default=2, ge=0.1, le=30)
    whisper_retry_backoff_max: float = Field(default=30, ge=1, le=60)
    min_audio_duration_sec: int = Field(default=1, ge=1, le=1200)
    max_audio_duration_sec: int = Field(default=120, ge=1, le=1200)
    max_audio_file_size_mb: int = Field(default=20, ge=1, le=25)
    transcription_job_timeout_sec: int = Field(default=60, ge=1, le=600)
    environment: str = "development"
    frontend_origin: str = "http://localhost:8080"
    daily_transcription_limit: int = Field(
        default=50,
        ge=1,
        validation_alias=AliasChoices(
            "DAILY_TRANSCRIPTION_LIMIT_PER_USER", "DAILY_TRANSCRIPTION_LIMIT"
        ),
    )
    concurrent_jobs_per_user: int = Field(
        default=2,
        ge=1,
        validation_alias=AliasChoices(
            "MAX_CONCURRENT_JOBS_PER_USER", "CONCURRENT_JOBS_PER_USER"
        ),
    )
    global_queued_jobs_limit: int = Field(default=1000, ge=1)
    hourly_transcription_limit: int = Field(default=10, ge=1)
    global_ai_requests_per_minute: int = Field(default=60, ge=1)
    whisper_cost_per_minute: float = Field(default=0.006, ge=0)

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        if self.min_audio_duration_sec > self.max_audio_duration_sec:
            raise ValueError("Minimum audio duration exceeds maximum")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test, or production")
        if self.whisper_language not in {"auto", "en", "hy"}:
            raise ValueError("WHISPER_LANGUAGE must be auto, en, or hy")
        if self.environment == "production":
            for secret in (self.jwt_secret, self.webhook_secret):
                if secret.startswith("REPLACE_"):
                    raise ValueError(
                        "Replace example secrets before running production"
                    )
            if "jwt_secret" not in self.model_fields_set or len(self.jwt_secret) < 32:
                raise ValueError(
                    "Production requires an explicit JWT_SECRET of 32+ characters"
                )
            if not all(
                (self.telegram_bot_token, self.openai_api_key, self.webhook_secret)
            ):
                raise ValueError(
                    "Production requires Telegram, provider, and webhook secrets"
                )
            if len(self.webhook_secret) < 32:
                raise ValueError("Production WEBHOOK_SECRET must have 32+ characters")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Production requires PostgreSQL with asyncpg")
            if not self.frontend_origin.startswith("https://"):
                raise ValueError("Production FRONTEND_ORIGIN requires HTTPS")
            if self.provider_base_url.rstrip("/") != "https://api.openai.com/v1":
                raise ValueError("Production provider host is fixed to OpenAI")
        return self


settings = Settings()
