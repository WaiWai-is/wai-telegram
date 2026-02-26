"""Add deterministic pagination indexes for chats and messages

Revision ID: 009_cursor_pagination_indexes
Revises: 008_drop_auto_sync_columns
Create Date: 2026-02-25

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_cursor_pagination_indexes"
down_revision: Union[str, None] = "008_drop_auto_sync_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_telegram_messages_chat_sent_tie
        ON telegram_messages (chat_id, sent_at DESC, telegram_message_id DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_telegram_chats_user_activity_tie
        ON telegram_chats (user_id, last_activity_at DESC, last_message_id DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_telegram_messages_chat_sent_tie")
    op.execute("DROP INDEX IF EXISTS ix_telegram_chats_user_activity_tie")
