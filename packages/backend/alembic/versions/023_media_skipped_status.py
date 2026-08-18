"""Allow the settled media status for files that can never yield text.

Deleted sources and silent recordings are final outcomes, not failures: retrying
cannot produce text, and counting them as errors hides the failures that do need
attention. The status column is guarded by a CHECK constraint, so the new value
has to be admitted here before it can be written.

Revision ID: 023_media_skipped_status
Revises: 022_search_indexes
"""

from collections.abc import Sequence

from alembic import op

revision: str = "023_media_skipped_status"
down_revision: str | None = "022_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_telegram_messages_media_processing_status"
_TABLE = "telegram_messages"
_WITH_SKIPPED = (
    "media_processing_status IS NULL OR media_processing_status IN "
    "('pending', 'queued', 'processing', 'ready', 'failed', 'skipped')"
)
_WITHOUT_SKIPPED = (
    "media_processing_status IS NULL OR media_processing_status IN "
    "('pending', 'queued', 'processing', 'ready', 'failed')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _WITH_SKIPPED)


def downgrade() -> None:
    op.execute(
        "UPDATE telegram_messages SET media_processing_status = 'failed' "
        "WHERE media_processing_status = 'skipped'"
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _WITHOUT_SKIPPED)
