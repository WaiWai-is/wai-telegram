"""Add closed single-user account state.

Revision ID: 019_single_user_mode
Revises: 018_add_media_content
Create Date: 2026-08-06
"""

import os
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "019_single_user_mode"
down_revision = "018_add_media_content"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    user_count = bind.execute(sa.text("SELECT count(*) FROM users")).scalar_one()
    owner_raw = os.environ.get("OWNER_USER_ID")
    if user_count:
        if not owner_raw:
            raise RuntimeError(
                "OWNER_USER_ID is required before migrating an existing installation"
            )
        owner_id = UUID(owner_raw)
        active_session_users = tuple(
            bind.execute(
                sa.text(
                    "SELECT DISTINCT user_id FROM telegram_sessions "
                    "WHERE is_active IS TRUE ORDER BY user_id"
                )
            ).scalars()
        )
        recent_key_users = tuple(
            bind.execute(
                sa.text(
                    "SELECT DISTINCT user_id FROM api_keys "
                    "WHERE is_active IS TRUE AND last_used_at >= now() - interval '60 minutes' "
                    "ORDER BY user_id"
                )
            ).scalars()
        )
        top_volume_users = tuple(
            bind.execute(
                sa.text(
                    "WITH volumes AS ("
                    " SELECT c.user_id, count(m.id) AS message_count"
                    " FROM telegram_chats c"
                    " LEFT JOIN telegram_messages m ON m.chat_id = c.id"
                    " GROUP BY c.user_id"
                    "), maximum AS (SELECT max(message_count) AS value FROM volumes)"
                    " SELECT user_id FROM volumes, maximum"
                    " WHERE message_count = maximum.value AND message_count > 0"
                    " ORDER BY user_id"
                )
            ).scalars()
        )
        expected = (owner_id,)
        if (
            active_session_users != expected
            or recent_key_users != expected
            or top_volume_users != expected
        ):
            raise RuntimeError(
                "Owner evidence is ambiguous; migration stopped before schema mutation"
            )

    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "uq_users_single_active",
        "users",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    if user_count:
        bind.execute(
            sa.text("UPDATE users SET is_active = (id = :owner_id)"),
            {"owner_id": owner_id},
        )


def downgrade():
    raise RuntimeError(
        "Downgrade is intentionally disabled: it would reopen access and remove "
        "the single-active-user database guard. Restore a verified backup instead."
    )
