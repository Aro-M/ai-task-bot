"""Visible worker lifecycle and profile update timestamps; retain legacy timeout values."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD = "'QUEUED','PROCESSING','COMPLETED','FAILED','TIMED_OUT','CANCELLED'"
NEW = OLD + ",'RETRYING','DEAD_LETTER'"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.drop_constraint("jobstatus", "transcription_jobs", type_="check")
    op.alter_column(
        "transcription_jobs", "status", existing_type=sa.String(10), type_=sa.String(11)
    )
    op.create_check_constraint("jobstatus", "transcription_jobs", f"status IN ({NEW})")
    op.execute(
        "UPDATE transcription_jobs SET status='DEAD_LETTER' WHERE status='FAILED' AND error_code='dead_letter'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE transcription_jobs SET status='FAILED' WHERE status='DEAD_LETTER'"
    )
    op.execute("UPDATE transcription_jobs SET status='QUEUED' WHERE status='RETRYING'")
    op.drop_constraint("jobstatus", "transcription_jobs", type_="check")
    op.alter_column(
        "transcription_jobs", "status", existing_type=sa.String(11), type_=sa.String(10)
    )
    op.create_check_constraint("jobstatus", "transcription_jobs", f"status IN ({OLD})")
    op.drop_column("users", "updated_at")
