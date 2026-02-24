"""Add user_settings table

Revision ID: 005_user_settings
Revises: 004_add_last_activity_at
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005_user_settings"
down_revision: Union[str, None] = "004_add_last_activity_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("digest_hour_utc", sa.SmallInteger(), nullable=False, server_default="9"),
        sa.Column("digest_telegram_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_sync_interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("realtime_sync_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_settings_user_id", table_name="user_settings")
    op.drop_table("user_settings")
