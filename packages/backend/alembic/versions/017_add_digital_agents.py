"""Add digital_agents table for autonomous AI agents.

Revision ID: 017
Revises: 016
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa

revision = "017_add_digital_agents"
down_revision = "016_add_commitments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "digital_agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("tools", sa.String(500), server_default=""),
        sa.Column("schedule_type", sa.String(20), nullable=False),
        sa.Column("cron_expression", sa.String(50)),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer(), server_default="0"),
        sa.Column("error_count", sa.Integer(), server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_result", sa.Text()),
        sa.Column("max_tokens_per_run", sa.Integer(), server_default="4096"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_digital_agents_user_status", "digital_agents", ["user_id", "status"]
    )
    op.create_index(
        "ix_digital_agents_next_run", "digital_agents", ["next_run_at", "status"]
    )


def downgrade():
    op.drop_index("ix_digital_agents_next_run")
    op.drop_index("ix_digital_agents_user_status")
    op.drop_table("digital_agents")
