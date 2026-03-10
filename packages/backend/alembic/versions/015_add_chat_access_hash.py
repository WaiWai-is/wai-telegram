"""Add access_hash column to telegram_chats

Revision ID: 015_add_chat_access_hash
Revises: 014_api_key_scopes
Create Date: 2026-03-10
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_add_chat_access_hash"
down_revision: Union[str, None] = "014_api_key_scopes"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_chats",
        sa.Column("access_hash", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_chats", "access_hash")
