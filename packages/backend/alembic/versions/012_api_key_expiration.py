"""Add expires_at column to api_keys

Revision ID: 012_api_key_expiration
Revises: 011_api_keys_table
Create Date: 2026-02-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_api_key_expiration"
down_revision: Union[str, None] = "011_api_keys_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

API_KEY_DEFAULT_EXPIRY_DAYS = 365


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "expires_at")
