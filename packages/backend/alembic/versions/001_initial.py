"""Initial schema

Revision ID: 001_initial
Revises:
Create Date: 2025-01-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("api_key_hash", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Telegram sessions table
    op.create_table(
        "telegram_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("session_string", sa.Text(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_sessions_user_id", "telegram_sessions", ["user_id"])

    # Telegram chats table
    op.create_table(
        "telegram_chats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "chat_type",
            sa.Enum("PRIVATE", "GROUP", "SUPERGROUP", "CHANNEL", name="chattype"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("total_messages_synced", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_chats_user_id", "telegram_chats", ["user_id"])
    op.create_index(
        "ix_telegram_chats_telegram_chat_id", "telegram_chats", ["telegram_chat_id"]
    )

    # Telegram messages table
    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("has_media", sa.Boolean(), nullable=False, default=False),
        sa.Column("media_type", sa.String(50), nullable=True),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("is_outgoing", sa.Boolean(), nullable=False, default=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["telegram_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_messages_chat_id", "telegram_messages", ["chat_id"])
    op.create_index(
        "ix_telegram_messages_telegram_message_id",
        "telegram_messages",
        ["telegram_message_id"],
    )
    op.create_index("ix_telegram_messages_sent_at", "telegram_messages", ["sent_at"])
    op.create_index(
        "ix_telegram_messages_chat_sent", "telegram_messages", ["chat_id", "sent_at"]
    )

    # Convert embedding column to vector type and create HNSW index
    op.execute(
        "ALTER TABLE telegram_messages ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.execute(
        """
        CREATE INDEX ix_telegram_messages_embedding_hnsw
        ON telegram_messages USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Sync jobs table
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="syncstatus",
            ),
            nullable=False,
        ),
        sa.Column("messages_processed", sa.Integer(), nullable=False, default=0),
        sa.Column("last_processed_id", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["telegram_chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_jobs_user_id", "sync_jobs", ["user_id"])
    op.create_index("ix_sync_jobs_chat_id", "sync_jobs", ["chat_id"])

    # Daily digests table
    op.create_table(
        "daily_digests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary_stats", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_digests_user_id", "daily_digests", ["user_id"])
    op.create_index("ix_daily_digests_digest_date", "daily_digests", ["digest_date"])

    # Full-text search index on messages
    op.execute(
        """
        CREATE INDEX ix_telegram_messages_text_fts
        ON telegram_messages USING gin (to_tsvector('english', coalesce(text, '')))
        """
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_messages_text_fts")
    op.drop_table("daily_digests")
    op.drop_table("sync_jobs")
    op.drop_index("ix_telegram_messages_embedding_hnsw")
    op.drop_table("telegram_messages")
    op.drop_table("telegram_chats")
    op.drop_table("telegram_sessions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS syncstatus")
    op.execute("DROP TYPE IF EXISTS chattype")
    op.execute("DROP EXTENSION IF EXISTS vector")
