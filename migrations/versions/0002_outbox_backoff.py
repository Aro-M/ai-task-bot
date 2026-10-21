"""Persist effect retry deadlines without changing existing job/status contracts."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("error_code", sa.String(64), nullable=True))
    op.add_column(
        "outbox",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("outbox", "available_at")
    op.drop_column("outbox", "error_code")
