"""Associate replay receipts with owners for database-backed bot admission."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processed_updates", sa.Column("user_id", sa.Uuid(as_uuid=False), nullable=True)
    )
    op.add_column(
        "processed_updates",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_updates_user",
        "processed_updates",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_updates_user_created", "processed_updates", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_updates_user_created", table_name="processed_updates")
    op.drop_constraint("fk_updates_user", "processed_updates", type_="foreignkey")
    op.drop_column("processed_updates", "created_at")
    op.drop_column("processed_updates", "user_id")
