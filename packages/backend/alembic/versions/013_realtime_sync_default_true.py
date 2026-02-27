"""Default realtime_sync_enabled to true

Revision ID: 013_realtime_sync_default_true
Revises: 012_api_key_expiration
Create Date: 2026-02-26
"""

from typing import Union

from alembic import op

revision: str = "013_realtime_sync_default_true"
down_revision: Union[str, None] = "012_api_key_expiration"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.alter_column(
        "user_settings",
        "realtime_sync_enabled",
        server_default="true",
    )


def downgrade() -> None:
    op.alter_column(
        "user_settings",
        "realtime_sync_enabled",
        server_default="false",
    )
