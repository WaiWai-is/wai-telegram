"""Record explicit transcription requests for media outside the configured set.

MEDIA_TRANSCRIPTION_TYPES narrows what the background pipeline transcribes so a
full archive does not buy speech-to-text for every forwarded video. Candidate
test submissions arrive as plain videos, and an explicit prepare_media call is
the signal that one specific file is worth transcribing anyway. The request has
to survive worker restarts and dispatch hops, so it lives on the media object.

Revision ID: 025_transcription_requested
Revises: 024_halfvec_embeddings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025_transcription_requested"
down_revision: str | None = "024_halfvec_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_objects",
        sa.Column(
            "transcription_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("media_objects", "transcription_requested_at")
