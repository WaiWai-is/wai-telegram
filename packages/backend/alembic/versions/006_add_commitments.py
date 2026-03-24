"""Add commitments table for tracking promises.

Revision ID: 006
Revises: 005
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "006_add_commitments"
down_revision = "005_user_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commitments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("who", sa.String(200), nullable=False),
        sa.Column("what", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("deadline", sa.String(100)),
        sa.Column("status", sa.String(20), default="open"),
        sa.Column("source_chat", sa.String(200)),
        sa.Column("source_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_commitments_user_status", "commitments", ["user_id", "status"])
    op.create_index(
        "ix_commitments_user_direction", "commitments", ["user_id", "direction"]
    )


def downgrade():
    op.drop_index("ix_commitments_user_direction")
    op.drop_index("ix_commitments_user_status")
    op.drop_table("commitments")
