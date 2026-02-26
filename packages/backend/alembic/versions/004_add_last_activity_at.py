"""Add last_activity_at column to telegram_chats

Revision ID: 004_add_last_activity_at
Revises: 003_api_key_prefix
Create Date: 2026-02-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_last_activity_at"
down_revision: Union[str, None] = "003_api_key_prefix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_chats",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_telegram_chats_last_activity_at",
        "telegram_chats",
        ["last_activity_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_chats_last_activity_at", table_name="telegram_chats")
    op.drop_column("telegram_chats", "last_activity_at")
