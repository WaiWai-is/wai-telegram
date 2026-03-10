"""Tests for app.services.messaging_service — pure unit tests (no Telegram calls)."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.messaging_service import (
    _handle_telethon_error,
    _sanitize_file_name,
    _validate_url,
)


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_allows_http(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
            ]
            _validate_url("http://example.com/file.pdf")

    def test_allows_https(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
            ]
            _validate_url("https://example.com/file.pdf")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("ftp://example.com/file.pdf")

    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url("file:///etc/passwd")

    def test_rejects_no_hostname(self):
        with pytest.raises(ValueError, match="hostname"):
            _validate_url("http:///path")

    def test_rejects_private_ip(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0))
            ]
            with pytest.raises(ValueError, match="private"):
                _validate_url("http://internal.example.com/file")

    def test_rejects_loopback(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))
            ]
            with pytest.raises(ValueError, match="private"):
                _validate_url("http://localhost/file")

    def test_rejects_link_local(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.1.1", 0))
            ]
            with pytest.raises(ValueError, match="private"):
                _validate_url("http://link-local.example.com/file")

    def test_rejects_unresolvable_hostname(self):
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.side_effect = socket.gaierror("Name not found")
            with pytest.raises(ValueError, match="Cannot resolve hostname"):
                _validate_url("http://nonexistent.invalid/file")

    def test_strips_ipv6_zone_id(self):
        """Ensure IPv6 zone IDs like %eth0 are stripped before parsing."""
        with patch("app.services.messaging_service.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fe80::1%eth0", 80, 0, 0))
            ]
            with pytest.raises(ValueError, match="private"):
                _validate_url("http://[fe80::1%25eth0]/file")


# ---------------------------------------------------------------------------
# _sanitize_file_name
# ---------------------------------------------------------------------------


class TestSanitizeFileName:
    def test_normal_filename(self):
        assert _sanitize_file_name("report.pdf") == "report.pdf"

    def test_strips_path_components(self):
        assert _sanitize_file_name("/etc/passwd") == "passwd"

    def test_removes_null_bytes(self):
        assert _sanitize_file_name("file\x00name.txt") == "file_name.txt"

    def test_removes_slashes(self):
        # Path.name strips forward slashes; backslash is replaced by _
        assert _sanitize_file_name("a/b\\c.txt") == "b_c.txt"

    def test_strips_forward_slash_path(self):
        assert _sanitize_file_name("dir/subdir/file.txt") == "file.txt"

    def test_removes_dangerous_chars(self):
        result = _sanitize_file_name('file|<>:"name.txt')
        assert "|" not in result
        assert "<" not in result
        assert ">" not in result

    def test_strips_leading_dashes(self):
        assert _sanitize_file_name("--flag.txt") == "flag.txt"

    def test_strips_leading_dots(self):
        assert _sanitize_file_name(".hidden.txt") == "hidden.txt"

    def test_truncates_long_name(self):
        long_name = "a" * 300 + ".pdf"
        result = _sanitize_file_name(long_name)
        assert len(result) <= 200

    def test_preserves_extension_on_truncation(self):
        long_name = "a" * 300 + ".pdf"
        result = _sanitize_file_name(long_name)
        assert result.endswith(".pdf")

    def test_empty_after_sanitize_returns_file(self):
        assert _sanitize_file_name("...") == "file"

    def test_returns_file_for_empty_string(self):
        assert _sanitize_file_name("") == "file"


# ---------------------------------------------------------------------------
# _handle_telethon_error
# ---------------------------------------------------------------------------


class TestHandleTelethonError:
    def test_flood_wait_error(self):
        from telethon.errors import FloodWaitError

        # FloodWaitError needs a real request; create via RPCError subclass
        try:
            raise FloodWaitError(request=None, capture=42)
        except FloodWaitError as err:
            with pytest.raises(ValueError, match="rate limit"):
                _handle_telethon_error(err)

    def test_chat_write_forbidden(self):
        from telethon.errors import ChatWriteForbiddenError

        try:
            raise ChatWriteForbiddenError(request=None)
        except ChatWriteForbiddenError as err:
            with pytest.raises(ValueError, match="permission"):
                _handle_telethon_error(err)

    def test_user_banned(self):
        from telethon.errors import UserBannedInChannelError

        try:
            raise UserBannedInChannelError(request=None)
        except UserBannedInChannelError as err:
            with pytest.raises(ValueError, match="banned"):
                _handle_telethon_error(err)

    def test_generic_error(self):
        err = RuntimeError("something broke")
        with pytest.raises(ValueError, match="Telegram error"):
            _handle_telethon_error(err)


# ---------------------------------------------------------------------------
# send_message (mock Telethon)
# ---------------------------------------------------------------------------


class TestSendMessage:
    async def test_send_message_success(self, db_session, test_user):
        from app.services.messaging_service import send_message
        from tests.factories import TelegramChatFactory

        chat = TelegramChatFactory.create(user_id=test_user.id)
        db_session.add(chat)
        await db_session.flush()

        mock_result = MagicMock()
        mock_result.id = 999

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=mock_result)
        mock_client.disconnect = AsyncMock()

        with patch(
            "app.services.messaging_service.get_client", return_value=mock_client
        ):
            result = await send_message(db_session, test_user.id, chat.id, "Hello")

        assert result["telegram_message_id"] == 999
        assert result["text"] == "Hello"
        mock_client.disconnect.assert_awaited_once()

    async def test_send_message_chat_not_found(self, db_session, test_user):
        from app.services.messaging_service import send_message

        with pytest.raises(ValueError, match="not found"):
            await send_message(db_session, test_user.id, uuid4(), "Hello")


# ---------------------------------------------------------------------------
# send_file (streaming download to temp file)
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self.headers = {"content-length": str(sum(len(chunk) for chunk in chunks))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self, chunk_size: int = 64 * 1024):
        for chunk in self._chunks:
            yield chunk


class _FakeHTTPClient:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method: str, url: str):
        assert method == "GET"
        assert url == "https://example.com/doc.pdf"
        return _FakeStreamResponse(self._chunks)


class TestSendFile:
    async def test_send_file_streams_to_temp_file(self, db_session, test_user):
        from app.services.messaging_service import send_file
        from tests.factories import TelegramChatFactory

        chat = TelegramChatFactory.create(user_id=test_user.id)
        db_session.add(chat)
        await db_session.flush()

        mock_result = MagicMock()
        mock_result.id = 456

        observed = {}

        async def fake_telethon_send_file(chat_id, file_path, caption=None, file_name=None):
            observed["chat_id"] = chat_id
            observed["caption"] = caption
            observed["file_name"] = file_name
            observed["file_bytes"] = open(file_path, "rb").read()
            return mock_result

        mock_client = AsyncMock()
        mock_client.send_file.side_effect = fake_telethon_send_file
        mock_client.disconnect = AsyncMock()

        fake_http_client = _FakeHTTPClient([b"hello ", b"world"])

        with (
            patch("app.services.messaging_service._validate_url", return_value=None),
            patch("app.services.messaging_service.httpx.AsyncClient", return_value=fake_http_client),
            patch("app.services.messaging_service.get_client", return_value=mock_client),
        ):
            result = await send_file(
                db_session,
                test_user.id,
                chat.id,
                "https://example.com/doc.pdf",
                caption="Report",
            )

        assert result["telegram_message_id"] == 456
        assert result["file_name"] == "doc.pdf"
        assert observed["caption"] == "Report"
        assert observed["file_name"] == "doc.pdf"
        assert observed["file_bytes"] == b"hello world"
        mock_client.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# reply_to_message (mock Telethon)
# ---------------------------------------------------------------------------


class TestReplyToMessage:
    async def test_reply_success(self, db_session, test_user):
        from app.services.messaging_service import reply_to_message
        from tests.factories import TelegramChatFactory

        chat = TelegramChatFactory.create(user_id=test_user.id)
        db_session.add(chat)
        await db_session.flush()

        mock_result = MagicMock()
        mock_result.id = 1001

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=mock_result)
        mock_client.disconnect = AsyncMock()

        with patch(
            "app.services.messaging_service.get_client", return_value=mock_client
        ):
            result = await reply_to_message(
                db_session, test_user.id, chat.id, 500, "Reply text"
            )

        assert result["telegram_message_id"] == 1001
        mock_client.send_message.assert_awaited_once()
        # Verify reply_to was passed
        call_kwargs = mock_client.send_message.call_args
        assert (
            call_kwargs.kwargs.get("reply_to") == 500
            or call_kwargs[1].get("reply_to") == 500
        )
