"""Carry scheduled agents over the find_files -> get_files rename.

Revision ID: 027_rename_find_files_tool
Revises: 026_canonical_channel_peer_ids
"""

from collections.abc import Sequence

from alembic import op

revision: str = "027_rename_find_files_tool"
down_revision: str | None = "026_canonical_channel_peer_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A digital agent keeps its tool list as free text and revalidates it at
    # every scheduled run, so a name left behind here fails the agent at run time
    # rather than at deploy time. The service also aliases the old name, which
    # covers rows written between the deploy and this migration.
    op.execute(
        "UPDATE digital_agents SET tools = replace(tools, 'find_files', 'get_files') "
        "WHERE tools LIKE '%find_files%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE digital_agents SET tools = replace(tools, 'get_files', 'find_files') "
        "WHERE tools LIKE '%get_files%'"
    )
