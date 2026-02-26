"""Create api_keys table and drop old user API key columns

Revision ID: 011_api_keys_table
Revises: 010_add_transcribed_at
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "011_api_keys_table"
down_revision: Union[str, None] = "010_add_transcribed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hint", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_prefix", "api_keys", ["key_prefix"])

    # Drop old single-key columns from users table
    op.drop_index("ix_users_api_key_prefix", table_name="users", if_exists=True)
    op.drop_column("users", "api_key_hash")
    op.drop_column("users", "api_key_prefix")


def downgrade() -> None:
    op.add_column("users", sa.Column("api_key_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("api_key_prefix", sa.String(16), nullable=True))
    op.create_index("ix_users_api_key_prefix", "users", ["api_key_prefix"])

    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_table("api_keys")
