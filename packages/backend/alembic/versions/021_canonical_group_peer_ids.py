"""Canonicalize legacy Telegram group peer IDs.

Revision ID: 021_canonical_group_peer_ids
Revises: 020_media_cache_and_metadata
"""

from collections.abc import Sequence

from alembic import op

revision: str = "021_canonical_group_peer_ids"
down_revision: str | None = "020_media_cache_and_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Realtime Telethon events use a negative peer ID for basic groups, while
    # the dialog sync historically stored the entity's positive raw ID. Merge
    # both representations before enforcing the canonical event-compatible ID.
    op.execute(
        """
        DELETE FROM telegram_messages AS legacy_message
        USING telegram_chats AS legacy_chat, telegram_chats AS canonical_chat
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND canonical_chat.user_id = legacy_chat.user_id
          AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
          AND legacy_message.chat_id = legacy_chat.id
          AND EXISTS (
              SELECT 1
              FROM telegram_messages AS canonical_message
              WHERE canonical_message.chat_id = canonical_chat.id
                AND canonical_message.telegram_message_id = legacy_message.telegram_message_id
          )
        """
    )
    op.execute(
        """
        UPDATE telegram_messages AS message
        SET chat_id = canonical_chat.id
        FROM telegram_chats AS legacy_chat
        JOIN telegram_chats AS canonical_chat
          ON canonical_chat.user_id = legacy_chat.user_id
         AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND message.chat_id = legacy_chat.id
        """
    )
    op.execute(
        """
        UPDATE sync_jobs AS job
        SET chat_id = canonical_chat.id
        FROM telegram_chats AS legacy_chat
        JOIN telegram_chats AS canonical_chat
          ON canonical_chat.user_id = legacy_chat.user_id
         AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND job.chat_id = legacy_chat.id
        """
    )
    op.execute(
        """
        UPDATE metadata_reconciliation_checkpoints AS canonical_checkpoint
        SET last_telegram_message_id = GREATEST(
                canonical_checkpoint.last_telegram_message_id,
                legacy_checkpoint.last_telegram_message_id
            ),
            processed_count = GREATEST(
                canonical_checkpoint.processed_count,
                legacy_checkpoint.processed_count
            ),
            status = CASE
                WHEN canonical_checkpoint.status = 'completed'
                  OR legacy_checkpoint.status = 'completed'
                THEN 'completed'
                ELSE canonical_checkpoint.status
            END,
            error_detail = COALESCE(
                canonical_checkpoint.error_detail,
                legacy_checkpoint.error_detail
            ),
            started_at = LEAST(
                canonical_checkpoint.started_at,
                legacy_checkpoint.started_at
            ),
            completed_at = GREATEST(
                canonical_checkpoint.completed_at,
                legacy_checkpoint.completed_at
            ),
            updated_at = GREATEST(
                canonical_checkpoint.updated_at,
                legacy_checkpoint.updated_at
            )
        FROM metadata_reconciliation_checkpoints AS legacy_checkpoint,
             telegram_chats AS legacy_chat,
             telegram_chats AS canonical_chat
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND canonical_chat.user_id = legacy_chat.user_id
          AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
          AND legacy_checkpoint.chat_id = legacy_chat.id
          AND canonical_checkpoint.user_id = canonical_chat.user_id
          AND canonical_checkpoint.chat_id = canonical_chat.id
        """
    )
    op.execute(
        """
        DELETE FROM metadata_reconciliation_checkpoints AS legacy_checkpoint
        USING telegram_chats AS legacy_chat, telegram_chats AS canonical_chat
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND canonical_chat.user_id = legacy_chat.user_id
          AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
          AND legacy_checkpoint.chat_id = legacy_chat.id
          AND EXISTS (
              SELECT 1
              FROM metadata_reconciliation_checkpoints AS canonical_checkpoint
              WHERE canonical_checkpoint.user_id = canonical_chat.user_id
                AND canonical_checkpoint.chat_id = canonical_chat.id
          )
        """
    )
    op.execute(
        """
        UPDATE metadata_reconciliation_checkpoints AS checkpoint
        SET chat_id = canonical_chat.id
        FROM telegram_chats AS legacy_chat
        JOIN telegram_chats AS canonical_chat
          ON canonical_chat.user_id = legacy_chat.user_id
         AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND checkpoint.chat_id = legacy_chat.id
        """
    )
    op.execute(
        """
        UPDATE telegram_chats AS canonical_chat
        SET access_hash = COALESCE(canonical_chat.access_hash, legacy_chat.access_hash),
            username = COALESCE(canonical_chat.username, legacy_chat.username),
            last_sync_at = GREATEST(canonical_chat.last_sync_at, legacy_chat.last_sync_at),
            last_activity_at = GREATEST(
                canonical_chat.last_activity_at,
                legacy_chat.last_activity_at
            ),
            last_message_text = COALESCE(
                canonical_chat.last_message_text,
                legacy_chat.last_message_text
            ),
            last_message_sender_name = COALESCE(
                canonical_chat.last_message_sender_name,
                legacy_chat.last_message_sender_name
            ),
            unread_count = GREATEST(
                COALESCE(canonical_chat.unread_count, 0),
                COALESCE(legacy_chat.unread_count, 0)
            ),
            created_at = LEAST(canonical_chat.created_at, legacy_chat.created_at)
        FROM telegram_chats AS legacy_chat
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND canonical_chat.user_id = legacy_chat.user_id
          AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
        """
    )
    op.execute(
        """
        DELETE FROM telegram_chats AS legacy_chat
        USING telegram_chats AS canonical_chat
        WHERE legacy_chat.chat_type = 'GROUP'
          AND legacy_chat.telegram_chat_id > 0
          AND canonical_chat.user_id = legacy_chat.user_id
          AND canonical_chat.telegram_chat_id = -legacy_chat.telegram_chat_id
        """
    )
    op.execute(
        """
        UPDATE telegram_chats AS chat
        SET telegram_chat_id = -chat.telegram_chat_id
        WHERE chat.chat_type = 'GROUP'
          AND chat.telegram_chat_id > 0
        """
    )
    op.execute(
        """
        UPDATE telegram_chats AS chat
        SET total_messages_synced = (
                SELECT COUNT(*) FROM telegram_messages AS message
                WHERE message.chat_id = chat.id
            ),
            last_message_id = (
                SELECT MAX(message.telegram_message_id)
                FROM telegram_messages AS message
                WHERE message.chat_id = chat.id
            )
        WHERE chat.chat_type = 'GROUP'
          AND chat.telegram_chat_id < 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE telegram_chats
        SET telegram_chat_id = -telegram_chat_id
        WHERE chat_type = 'GROUP'
          AND telegram_chat_id < 0
        """
    )
