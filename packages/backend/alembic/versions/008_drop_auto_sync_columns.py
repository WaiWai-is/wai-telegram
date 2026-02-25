"""Drop auto_sync_enabled and auto_sync_interval_minutes from user_settings

Revision ID: 008_drop_auto_sync_columns
Revises: 007_chat_preview_fields
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "008_drop_auto_sync_columns"
down_revision: Union[str, None] = "007_chat_preview_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("user_settings", "auto_sync_enabled")
    op.drop_column("user_settings", "auto_sync_interval_minutes")


def downgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "auto_sync_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "auto_sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
