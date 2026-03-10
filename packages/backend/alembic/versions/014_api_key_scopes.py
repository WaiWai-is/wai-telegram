"""Add scopes column to api_keys

Revision ID: 014_api_key_scopes
Revises: 013_realtime_sync_default_true
Create Date: 2026-03-10
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_api_key_scopes"
down_revision: Union[str, None] = "013_realtime_sync_default_true"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "scopes",
            sa.String(50),
            nullable=False,
            server_default="read,write",
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "scopes")
