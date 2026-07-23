"""Add durable media content, summaries, and chunk embeddings.

Revision ID: 018_add_media_content
Revises: 017_add_digital_agents
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "018_add_media_content"
down_revision = "017_add_digital_agents"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "telegram_messages",
        sa.Column("media_file_name", sa.String(512), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_mime_type", sa.String(255), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("content_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("content_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_processing_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_processing_error_code", sa.String(64), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("media_processing_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column(
            "media_processing_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "telegram_messages",
        sa.Column(
            "media_processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_messages",
        sa.Column(
            "media_processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("content_model", sa.String(100), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("summary_model", sa.String(100), nullable=True),
    )
    op.create_check_constraint(
        "ck_telegram_messages_media_processing_status",
        "telegram_messages",
        "media_processing_status IS NULL OR media_processing_status IN "
        "('pending', 'queued', 'processing', 'ready', 'failed')",
    )
    op.create_index(
        "ix_telegram_messages_media_processing_status",
        "telegram_messages",
        ["media_processing_status"],
    )

    op.execute(
        """
        UPDATE telegram_messages
        SET content_text = text,
            text = NULL
        WHERE transcribed_at IS NOT NULL
          AND content_text IS NULL
        """
    )
    op.execute(
        """
        UPDATE telegram_messages
        SET media_processing_status = 'pending'
        WHERE has_media = true
          AND media_type IN (
              'voice', 'video_note', 'audio', 'video', 'photo', 'document'
          )
        """
    )

    op.create_table(
        "message_content_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("telegram_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "message_id",
            "chunk_index",
            name="uq_message_content_chunks_message_index",
        ),
    )
    op.create_index(
        "ix_message_content_chunks_message_id",
        "message_content_chunks",
        ["message_id"],
    )
    op.create_index(
        "ix_message_content_chunks_embedding_hnsw",
        "message_content_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade():
    # Restore the legacy searchable transcript location before dropping the
    # separated content column. The old schema cannot preserve both caption
    # and transcript, so transcript matches its previous behavior.
    op.execute(
        """
        UPDATE telegram_messages
        SET text = content_text
        WHERE transcribed_at IS NOT NULL
          AND content_text IS NOT NULL
        """
    )

    op.drop_index(
        "ix_message_content_chunks_embedding_hnsw",
        table_name="message_content_chunks",
    )
    op.drop_index(
        "ix_message_content_chunks_message_id",
        table_name="message_content_chunks",
    )
    op.drop_table("message_content_chunks")

    op.drop_index(
        "ix_telegram_messages_media_processing_status",
        table_name="telegram_messages",
    )
    op.drop_constraint(
        "ck_telegram_messages_media_processing_status",
        "telegram_messages",
        type_="check",
    )
    for column in (
        "summary_model",
        "content_model",
        "media_processed_at",
        "media_processing_started_at",
        "media_processing_attempts",
        "media_processing_error",
        "media_processing_error_code",
        "media_processing_status",
        "content_summary",
        "content_text",
        "media_duration_seconds",
        "media_file_size",
        "media_mime_type",
        "media_file_name",
    ):
        op.drop_column("telegram_messages", column)
