"""Store embeddings at half precision.

348k vectors at 1536 float32 dimensions are 2.1GB of raw data before the graph,
and the HNSW build spilled to disk at 78k tuples on this host: postgres reported
"hnsw graph no longer fits into maintenance_work_mem". Half precision halves both
the column and the index, which is the difference between an index that fits in
memory and one that does not. Recall loss for embeddings in this range is well
under a percent, and the ranking is fused with lexical search on top.

Revision ID: 024_halfvec_embeddings
Revises: 023_media_skipped_status
"""

from collections.abc import Sequence

from alembic import op

revision: str = "024_halfvec_embeddings"
down_revision: str | None = "023_media_skipped_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_telegram_messages_embedding_hnsw"
_CHUNK_INDEX = "ix_message_content_chunks_embedding_hnsw"


def upgrade() -> None:
    # Both indexes use vector_cosine_ops, which refuses a halfvec column, so
    # they have to come down before the type changes and go back up after.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_CHUNK_INDEX}")
    op.execute(
        "ALTER TABLE telegram_messages "
        "ALTER COLUMN embedding TYPE halfvec(1536) USING embedding::halfvec(1536)"
    )
    op.execute(
        "ALTER TABLE message_content_chunks "
        "ALTER COLUMN embedding TYPE halfvec(1536) USING embedding::halfvec(1536)"
    )
    op.execute(
        f"CREATE INDEX {_INDEX} ON telegram_messages "
        "USING hnsw (embedding halfvec_cosine_ops)"
    )
    op.execute(
        f"CREATE INDEX {_CHUNK_INDEX} ON message_content_chunks "
        "USING hnsw (embedding halfvec_cosine_ops)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_CHUNK_INDEX}")
    op.execute(
        "ALTER TABLE message_content_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.execute(
        "ALTER TABLE telegram_messages "
        "ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.execute(
        f"CREATE INDEX {_INDEX} ON telegram_messages "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        f"CREATE INDEX {_CHUNK_INDEX} ON message_content_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
