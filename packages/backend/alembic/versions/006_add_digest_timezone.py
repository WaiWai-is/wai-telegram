"""Add digest_timezone to user_settings

Revision ID: 006_add_digest_timezone
Revises: 005_user_settings
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006_add_digest_timezone"
down_revision: Union[str, None] = "005_user_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("digest_timezone", sa.String(50), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "digest_timezone")
