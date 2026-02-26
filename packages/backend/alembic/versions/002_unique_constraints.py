"""Add unique constraints for data integrity

Revision ID: 002_unique_constraints
Revises: 001_initial
Create Date: 2026-02-24

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_unique_constraints"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Deduplicate telegram_chats: keep row with latest created_at per (user_id, telegram_chat_id) ---
    op.execute("""
        DELETE FROM telegram_chats
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, telegram_chat_id) id
            FROM telegram_chats
            ORDER BY user_id, telegram_chat_id, created_at DESC
        )
    """)
    op.create_unique_constraint(
        "uq_telegram_chats_user_chat",
        "telegram_chats",
        ["user_id", "telegram_chat_id"],
    )

    # --- Deduplicate telegram_messages: keep row with latest created_at per (chat_id, telegram_message_id) ---
    op.execute("""
        DELETE FROM telegram_messages
        WHERE id NOT IN (
            SELECT DISTINCT ON (chat_id, telegram_message_id) id
            FROM telegram_messages
            ORDER BY chat_id, telegram_message_id, created_at DESC
        )
    """)
    op.create_unique_constraint(
        "uq_telegram_messages_chat_msg",
        "telegram_messages",
        ["chat_id", "telegram_message_id"],
    )

    # --- Deduplicate daily_digests: keep row with latest created_at per (user_id, digest_date) ---
    op.execute("""
        DELETE FROM daily_digests
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, digest_date) id
            FROM daily_digests
            ORDER BY user_id, digest_date, created_at DESC
        )
    """)
    op.create_unique_constraint(
        "uq_daily_digests_user_date",
        "daily_digests",
        ["user_id", "digest_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_daily_digests_user_date", "daily_digests", type_="unique")
    op.drop_constraint(
        "uq_telegram_messages_chat_msg", "telegram_messages", type_="unique"
    )
    op.drop_constraint("uq_telegram_chats_user_chat", "telegram_chats", type_="unique")
