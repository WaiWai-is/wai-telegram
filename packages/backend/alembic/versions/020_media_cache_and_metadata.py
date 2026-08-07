"""Add durable media cache, transcript segments, and complete message metadata.

Revision ID: 020_media_cache_and_metadata
Revises: 019_single_user_mode
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "020_media_cache_and_metadata"
down_revision = "019_single_user_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column(
        "digital_agents",
        sa.Column(
            "max_runtime_seconds", sa.Integer(), server_default="300", nullable=False
        ),
    )
    op.add_column(
        "digital_agents",
        sa.Column("max_tool_turns", sa.Integer(), server_default="10", nullable=False),
    )

    op.add_column("telegram_messages", sa.Column("entities", sa.JSON(), nullable=True))
    op.add_column(
        "telegram_messages", sa.Column("visible_urls", sa.JSON(), nullable=True)
    )
    op.add_column(
        "telegram_messages", sa.Column("hidden_urls", sa.JSON(), nullable=True)
    )
    op.add_column("telegram_messages", sa.Column("buttons", sa.JSON(), nullable=True))
    op.add_column(
        "telegram_messages", sa.Column("webpage_preview", sa.JSON(), nullable=True)
    )
    op.add_column(
        "telegram_messages", sa.Column("reply_to_message_id", sa.BigInteger())
    )
    op.add_column("telegram_messages", sa.Column("thread_id", sa.BigInteger()))
    op.add_column(
        "telegram_messages", sa.Column("forward_origin", sa.JSON(), nullable=True)
    )
    op.add_column("telegram_messages", sa.Column("album_id", sa.BigInteger()))
    op.add_column("telegram_messages", sa.Column("reactions", sa.JSON(), nullable=True))
    op.add_column(
        "telegram_messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_telegram_messages_deleted_at",
        "telegram_messages",
        ["deleted_at"],
    )
    op.add_column("telegram_messages", sa.Column("poll", sa.JSON(), nullable=True))
    op.add_column("telegram_messages", sa.Column("contact", sa.JSON(), nullable=True))
    op.add_column("telegram_messages", sa.Column("location", sa.JSON(), nullable=True))
    op.add_column(
        "telegram_messages", sa.Column("service_event", sa.JSON(), nullable=True)
    )
    op.add_column(
        "telegram_messages", sa.Column("searchable_metadata", sa.Text(), nullable=True)
    )
    op.execute("ALTER TABLE telegram_messages ADD COLUMN search_vector tsvector")
    op.execute("ALTER TABLE message_content_chunks ADD COLUMN search_vector tsvector")

    op.create_table(
        "media_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("telegram_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_media_id", sa.String(255), nullable=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=True),
        sa.Column("file_name", sa.String(512), nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("stage", sa.String(32), server_default="fetch", nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("byte_offset", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summarized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "stage IN ('fetch', 'extraction', 'summary', 'index', 'complete')",
            name="ck_media_objects_stage",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'fetching', 'cached', 'extracting', 'indexing', "
            "'processing', 'ready', 'ready_download_only', 'retry_wait', "
            "'no_speech', 'source_deleted', 'unsupported', 'disk_full', 'failed')",
            name="ck_media_objects_status",
        ),
        sa.CheckConstraint("byte_offset >= 0", name="ck_media_objects_byte_offset"),
        sa.CheckConstraint("retry_count >= 0", name="ck_media_objects_retry_count"),
        sa.UniqueConstraint("cache_key"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_media_objects_user_id", "media_objects", ["user_id"])
    op.create_index("ix_media_objects_status", "media_objects", ["status"])
    op.create_index(
        "ix_media_objects_user_status", "media_objects", ["user_id", "status"]
    )
    op.execute(
        """
        CREATE FUNCTION wai_media_object_owner_matches_message() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM telegram_messages m
            JOIN telegram_chats c ON c.id = m.chat_id
            WHERE m.id = NEW.message_id AND c.user_id = NEW.user_id
          ) THEN
            RAISE EXCEPTION 'media object owner does not own message';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_media_object_owner_matches_message
        AFTER INSERT OR UPDATE OF user_id, message_id ON media_objects
        DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW
        EXECUTE FUNCTION wai_media_object_owner_matches_message()
        """
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("telegram_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("speaker", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "sequence", name="uq_transcript_segments_message_sequence"
        ),
    )
    op.create_index(
        "ix_transcript_segments_message_id", "transcript_segments", ["message_id"]
    )
    op.create_index(
        "ix_transcript_segments_message_time",
        "transcript_segments",
        ["message_id", "start_ms", "end_ms"],
    )

    op.create_table(
        "message_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("telegram_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "revision", name="uq_message_revisions_message_revision"
        ),
    )
    op.create_index(
        "ix_message_revisions_message_id", "message_revisions", ["message_id"]
    )

    op.create_table(
        "metadata_reconciliation_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            sa.Uuid(),
            sa.ForeignKey("telegram_chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_telegram_message_id",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "chat_id", name="uq_metadata_reconciliation_user_chat"
        ),
    )
    op.create_index(
        "ix_metadata_reconciliation_checkpoints_user_id",
        "metadata_reconciliation_checkpoints",
        ["user_id"],
    )
    op.create_index(
        "ix_metadata_reconciliation_checkpoints_chat_id",
        "metadata_reconciliation_checkpoints",
        ["chat_id"],
    )

    op.execute(
        """
        CREATE FUNCTION wai_telegram_messages_search_vector() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          NEW.search_vector := to_tsvector(
            'simple',
            left(coalesce(NEW.text, ''), 30000) || ' ' ||
            left(coalesce(NEW.content_summary, ''), 15000) || ' ' ||
            left(coalesce(NEW.content_text, ''), 30000) || ' ' ||
            left(coalesce(NEW.sender_name, ''), 2000) || ' ' ||
            left(coalesce(NEW.media_file_name, ''), 4000) || ' ' ||
            left(coalesce(NEW.searchable_metadata, ''), 15000)
          );
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_telegram_messages_search_vector
        BEFORE INSERT OR UPDATE OF text, content_summary, content_text, sender_name,
          media_file_name, searchable_metadata
        ON telegram_messages FOR EACH ROW
        EXECUTE FUNCTION wai_telegram_messages_search_vector()
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_telegram_messages_text_fts")
    op.execute(
        """
        CREATE FUNCTION wai_message_chunks_search_vector() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          NEW.search_vector := to_tsvector('simple', coalesce(NEW.text, ''));
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_message_chunks_search_vector
        BEFORE INSERT OR UPDATE OF text ON message_content_chunks FOR EACH ROW
        EXECUTE FUNCTION wai_message_chunks_search_vector()
        """
    )


def downgrade():
    raise RuntimeError(
        "Downgrade is intentionally disabled because it destroys media cache, "
        "transcripts, message revisions, and reconciliation checkpoints. Restore "
        "a verified backup instead."
    )
