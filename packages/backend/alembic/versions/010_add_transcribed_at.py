"""Add transcribed_at column to telegram_messages

Revision ID: 010_add_transcribed_at
Revises: 009_cursor_pagination_indexes
Create Date: 2026-02-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_transcribed_at"
down_revision: Union[str, None] = "009_cursor_pagination_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_messages",
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_messages", "transcribed_at")
