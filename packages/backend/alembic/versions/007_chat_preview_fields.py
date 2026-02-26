"""Add chat preview fields for Telegram-style chat list

Revision ID: 007_chat_preview_fields
Revises: 006_add_digest_timezone
Create Date: 2026-02-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_chat_preview_fields"
down_revision: Union[str, None] = "006_add_digest_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_chats",
        sa.Column("last_message_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_chats",
        sa.Column("last_message_sender_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "telegram_chats",
        sa.Column("unread_count", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("telegram_chats", "unread_count")
    op.drop_column("telegram_chats", "last_message_sender_name")
    op.drop_column("telegram_chats", "last_message_text")
