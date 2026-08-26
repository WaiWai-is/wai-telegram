from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models.chat import TelegramChat
from app.services.metadata_reconciliation import (
    UNREACHABLE_CHAT_ERRORS,
    _metadata_message_values,
)
from app.services.messaging_service import TelegramEntityNotFoundError


def test_unresolvable_stale_dialog_is_an_unreachable_chat() -> None:
    assert TelegramEntityNotFoundError in UNREACHABLE_CHAT_ERRORS


def test_metadata_reconciliation_never_schedules_historical_media():
    chat = TelegramChat(
        id=uuid4(),
        user_id=uuid4(),
        telegram_chat_id=123,
        chat_type="private",
        title="Archive",
    )
    message = SimpleNamespace(
        id=99,
        text="Archive file",
        message="Archive file",
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="application/pdf",
                size=1234,
                attributes=[SimpleNamespace(file_name="archive.pdf")],
            )
        ),
        sender_id=1,
        sender=None,
        out=False,
        date=datetime.now(UTC),
        entities=None,
        buttons=None,
        reply_to=None,
        fwd_from=None,
        grouped_id=None,
        reactions=None,
        edit_date=None,
        action=None,
    )

    values = _metadata_message_values(chat, message)

    assert values["media_file_name"] == "archive.pdf"
    assert "media_processing_status" not in values
    assert values["searchable_metadata"] == "archive.pdf"
