"""Explicit initial schema; migrations remain independent of future ORM changes."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("telegram_user_id", sa.String(32), unique=True, nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(256), nullable=False),
        sa.Column("last_name", sa.String(256), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "COMPLETED",
                name="taskstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "DASHBOARD",
                "TELEGRAM_TEXT",
                "TELEGRAM_VOICE",
                name="tasksource",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "priority",
            sa.Enum(
                "LOW",
                "MEDIUM",
                "HIGH",
                name="priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_key", sa.String(128), unique=True, nullable=True),
    )
    op.create_index("ix_tasks_user_created", "tasks", ["user_id", "created_at"])
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_file_id", sa.String(512), nullable=False),
        sa.Column("chat_id", sa.String(32), nullable=False),
        sa.Column("audio_duration_sec", sa.Float(), nullable=False),
        sa.Column("audio_file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                "TIMED_OUT",
                "CANCELLED",
                name="jobstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("detected_language", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_jobs_status_created", "transcription_jobs", ["status", "created_at"]
    )
    op.create_index(
        "ix_jobs_user_created", "transcription_jobs", ["user_id", "created_at"]
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_outbox_delivery", "outbox", ["delivered_at", "created_at"])
    op.create_table(
        "login_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_codes_user_id", "login_codes", ["user_id"])
    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True, autoincrement=False),
    )


def downgrade() -> None:
    op.drop_table("processed_updates")
    op.drop_table("login_codes")
    op.drop_table("outbox")
    op.drop_table("transcription_jobs")
    op.drop_table("tasks")
    op.drop_table("users")
