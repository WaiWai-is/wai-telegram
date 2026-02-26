from unittest.mock import MagicMock

from app.services.sync_service import (
    _get_chat_title,
    _get_chat_type,
    _get_media_type,
    _get_sender_name,
)
from app.models.chat import ChatType


class TestGetChatType:
    def test_private_user(self):
        dialog = MagicMock()
        from telethon.tl.types import User as TelegramUser

        dialog.entity = MagicMock(spec=TelegramUser)
        assert _get_chat_type(dialog) == ChatType.PRIVATE

    def test_group(self):
        dialog = MagicMock()
        from telethon.tl.types import Chat

        dialog.entity = MagicMock(spec=Chat)
        assert _get_chat_type(dialog) == ChatType.GROUP

    def test_supergroup(self):
        dialog = MagicMock()
        from telethon.tl.types import Channel

        dialog.entity = MagicMock(spec=Channel)
        dialog.entity.megagroup = True
        assert _get_chat_type(dialog) == ChatType.SUPERGROUP

    def test_channel(self):
        dialog = MagicMock()
        from telethon.tl.types import Channel

        dialog.entity = MagicMock(spec=Channel)
        dialog.entity.megagroup = False
        assert _get_chat_type(dialog) == ChatType.CHANNEL


class TestGetChatTitle:
    def test_user_full_name(self):
        dialog = MagicMock()
        from telethon.tl.types import User as TelegramUser

        dialog.entity = MagicMock(spec=TelegramUser)
        dialog.entity.first_name = "John"
        dialog.entity.last_name = "Doe"
        assert _get_chat_title(dialog) == "John Doe"

    def test_user_first_name_only(self):
        dialog = MagicMock()
        from telethon.tl.types import User as TelegramUser

        dialog.entity = MagicMock(spec=TelegramUser)
        dialog.entity.first_name = "Alice"
        dialog.entity.last_name = ""
        assert _get_chat_title(dialog) == "Alice"

    def test_group_title(self):
        dialog = MagicMock()
        from telethon.tl.types import Chat

        dialog.entity = MagicMock(spec=Chat)
        dialog.entity.title = "My Group"
        assert _get_chat_title(dialog) == "My Group"


class TestGetSenderName:
    def test_user_sender(self):
        from telethon.tl.types import User as TelegramUser

        message = MagicMock()
        message.sender = MagicMock(spec=TelegramUser)
        message.sender.first_name = "Bob"
        message.sender.last_name = "Smith"
        assert _get_sender_name(message) == "Bob Smith"

    def test_no_sender(self):
        message = MagicMock()
        message.sender = None
        assert _get_sender_name(message) is None


class TestGetMediaType:
    def test_no_media(self):
        message = MagicMock()
        message.media = None
        assert _get_media_type(message) is None

    def test_photo(self):
        from telethon.tl.types import MessageMediaPhoto

        message = MagicMock()
        message.media = MagicMock(spec=MessageMediaPhoto)
        assert _get_media_type(message) == "photo"

    def test_voice(self):
        from telethon.tl.types import MessageMediaDocument

        message = MagicMock()
        message.media = MagicMock(spec=MessageMediaDocument)
        doc = MagicMock()
        voice_attr = MagicMock()
        voice_attr.voice = True
        doc.attributes = [voice_attr]
        message.media.document = doc
        assert _get_media_type(message) == "voice"
