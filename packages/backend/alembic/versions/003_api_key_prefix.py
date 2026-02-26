"""Add api_key_prefix column for O(1) API key lookup

Revision ID: 003_api_key_prefix
Revises: 002_unique_constraints
Create Date: 2026-02-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_api_key_prefix"
down_revision: Union[str, None] = "002_unique_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("api_key_prefix", sa.String(16), nullable=True))
    op.create_index("ix_users_api_key_prefix", "users", ["api_key_prefix"])


def downgrade() -> None:
    op.drop_index("ix_users_api_key_prefix", table_name="users")
    op.drop_column("users", "api_key_prefix")
