"""Add indexes used by hybrid and exact message search.

Revision ID: 022_search_indexes
Revises: 021_canonical_group_peer_ids
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022_search_indexes"
down_revision: str | None = "021_canonical_group_peer_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Production already contains a large message corpus. Concurrent builds keep
    # message ingestion and reads available while PostgreSQL creates the indexes.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_telegram_messages_search_vector_gin "
            "ON telegram_messages USING gin (search_vector)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_message_content_chunks_search_vector_gin "
            "ON message_content_chunks USING gin (search_vector)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_telegram_messages_media_file_name_trgm "
            "ON telegram_messages USING gin (media_file_name gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_telegram_messages_searchable_metadata_trgm "
            "ON telegram_messages USING gin (searchable_metadata gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_telegram_messages_searchable_metadata_trgm"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_telegram_messages_media_file_name_trgm"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_message_content_chunks_search_vector_gin"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_telegram_messages_search_vector_gin"
        )
