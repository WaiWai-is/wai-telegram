import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.listener.main import TelegramListener
from app.models.message import TelegramMessage
from app.services.media_content_service import MediaInfo
from app.services.media_processing_service import (
    ClaimedMediaMessage,
    MediaDownloadError,
    _download_telegram_media,
    _get_media_client,
    disconnect_media_clients,
)
from app.services.sync_service import _media_values


def _message_row(telegram_message_id: int, media_values: dict) -> dict:
    return {
        "chat_id": uuid4(),
        "telegram_message_id": telegram_message_id,
        "text": None,
        "sender_id": 1,
        "sender_name": "Mik",
        "is_outgoing": True,
        "sent_at": datetime.now(UTC),
        "transcribed_at": None,
        **media_values,
    }


@pytest.mark.parametrize("media_first", [True, False])
def test_sync_batch_preserves_media_columns_in_any_message_order(media_first):
    media_info = MediaInfo(
        media_type="voice",
        file_name="voice.ogg",
        mime_type="audio/ogg",
        file_size=123,
        duration_seconds=5,
    )
    with patch(
        "app.services.sync_service.get_media_info",
        side_effect=[media_info, None],
    ):
        media_values = _media_values(SimpleNamespace(media=object()))
        text_values = _media_values(SimpleNamespace(media=None))

    rows = [
        _message_row(1, media_values),
        _message_row(2, text_values),
    ]
    if not media_first:
        rows.reverse()

    stmt = (
        pg_insert(TelegramMessage)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_telegram_messages_chat_msg")
        .returning(TelegramMessage.id)
    )
    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "media_file_name_m0" in compiled
    assert "media_file_name_m1" in compiled


async def test_telegram_media_download_has_an_operation_timeout(tmp_path):
    job = ClaimedMediaMessage(
        id=uuid4(),
        user_id=uuid4(),
        chat_id=uuid4(),
        telegram_message_id=123,
        caption=None,
        media_type="photo",
        file_name="photo.jpg",
        mime_type="image/jpeg",
        file_size=None,
        duration_seconds=None,
        existing_content_text=None,
        transcribed_at=None,
    )
    cached_path = tmp_path / "photo.jpg"
    cached_path.write_bytes(b"photo")
    cached = SimpleNamespace(
        path=cached_path,
        file_name="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=5,
    )

    with patch(
        "app.services.media_processing_service.fetch_media_to_cache",
        new_callable=AsyncMock,
        return_value=cached,
    ) as fetch:
        path, info = await _download_telegram_media(job, tmp_path)

    assert path == cached_path
    assert info.file_size == 5
    fetch.assert_awaited_once()
    source = inspect.getsource(_download_telegram_media)
    assert "asyncio.timeout" not in source
    assert "media_download_timeout_seconds" not in source


async def test_media_worker_reuses_client_and_disconnects_it_on_shutdown():
    await disconnect_media_clients()
    user_id = uuid4()
    db = AsyncMock()
    client = MagicMock()
    client.is_connected.return_value = True
    client.disconnect = AsyncMock()

    with patch(
        "app.services.media_processing_service.get_client",
        new_callable=AsyncMock,
        return_value=client,
    ) as create_client:
        first = await _get_media_client(user_id, db)
        second = await _get_media_client(user_id, db)

    assert first is client
    assert second is client
    create_client.assert_awaited_once_with(user_id, db)

    await disconnect_media_clients()
    client.disconnect.assert_awaited_once()


async def test_stalled_cache_download_discards_reusable_client(tmp_path):
    from app.services.media_cache_service import MediaDownloadStalled
    from app.services.media_processing_service import _media_clients

    user_id = uuid4()
    job = ClaimedMediaMessage(
        id=uuid4(),
        user_id=user_id,
        chat_id=uuid4(),
        telegram_message_id=123,
        caption=None,
        media_type="photo",
        file_name="photo.jpg",
        mime_type="image/jpeg",
        file_size=None,
        duration_seconds=None,
        existing_content_text=None,
        transcribed_at=None,
    )
    client = MagicMock()
    client.is_connected.return_value = True
    client.disconnect = AsyncMock()
    _media_clients[user_id] = client

    async def get_failed_client(_user_id, _db):
        return client

    async def stalled(*_args, **kwargs):
        await kwargs["get_media_client"](user_id, AsyncMock())
        raise MediaDownloadStalled("no progress")

    with patch(
        "app.services.media_processing_service.fetch_media_to_cache",
        new_callable=AsyncMock,
        side_effect=stalled,
    ):
        with pytest.raises(MediaDownloadError, match="download_stalled"):
            await _download_telegram_media(job, tmp_path)

    assert user_id not in _media_clients
    client.disconnect.assert_awaited_once()


def test_media_worker_uses_one_persistent_telegram_connection():
    service = (
        Path(__file__).parents[3].joinpath("systemd/wai-media.service").read_text()
    )

    assert "--concurrency=1" in service
    assert "--max-tasks-per-child" not in service


def test_realtime_listener_uses_the_bounded_priority_dispatcher():
    source = inspect.getsource(TelegramListener._handle_message)

    assert "enqueue_media_processing" not in source


def test_signed_media_download_has_no_application_rate_limit_and_no_token_logs():
    root = Path(__file__).parents[3]
    route_source = inspect.getsource(
        __import__(
            "app.api.v1.chats", fromlist=["download_message_media"]
        ).download_message_media
    )
    nginx = root.joinpath("nginx/telegram-ai.conf").read_text()
    backend_service = root.joinpath("systemd/wai-backend.service").read_text()

    assert "limiter.limit" not in route_source
    signed_location = nginx.split("location ~ ^/api/v1/chats/", 1)[1].split("}", 1)[0]
    assert "access_log off" in signed_location
    assert "limit_req" not in signed_location
    assert "--no-access-log" in backend_service

    mcp_location = nginx.split("location = /mcp {", 1)[1].split("}", 1)[0]
    assert "access_log off" in mcp_location


def test_large_media_pipeline_has_no_document_total_timeout_and_uses_sendfile():
    root = Path(__file__).parents[3]
    document_source = inspect.getsource(
        __import__(
            "app.services.media_content_service", fromlist=["extract_document_text"]
        ).extract_document_text
    )
    nginx = root.joinpath("nginx/telegram-ai.conf").read_text()
    protected_location = nginx.split("location /_protected_media/", 1)[1].split("}", 1)[
        0
    ]

    assert "wait_for" not in document_source
    assert "document_extraction_timeout_seconds" not in document_source
    assert "sendfile on" in protected_location
    assert "directio" not in protected_location


def test_cutover_backup_secret_is_not_exposed_to_application_services():
    root = Path(__file__).parents[3]
    production_env = root.joinpath(".env.production.example").read_text()
    workflow = root.joinpath(".github/workflows/deploy.yml").read_text()
    backup_script = root.joinpath("scripts/auth-cutover-backup.sh").read_text()

    assert "BACKUP_ENCRYPTION_PASSPHRASE" not in production_env
    assert "BACKUP_ENCRYPTION_PASSPHRASE" not in workflow
    assert "/etc/wai-telegram/auth-backup-passphrase" in backup_script
    assert "--passphrase-file" in backup_script

    preflight = root.joinpath("scripts/single-user-preflight.sh").read_text()
    assert "stat -c '%u:%a'" in preflight
    assert '"0:600"' in preflight


def test_media_writers_have_explicit_media_volume_group():
    root = Path(__file__).parents[3]
    for unit_name in (
        "wai-backend.service",
        "wai-media.service",
        "wai-media-process.service",
        "wai-media-index.service",
    ):
        unit = root.joinpath("systemd", unit_name).read_text()
        assert "SupplementaryGroups=wai-media" in unit


def test_restic_is_pinned_and_checksum_verified_before_backup_setup():
    root = Path(__file__).parents[3]
    installer = root.joinpath("scripts/install-restic.sh").read_text()
    workflow = root.joinpath(".github/workflows/deploy.yml").read_text()

    assert 'RESTIC_VERSION="0.19.1"' in installer
    assert "restic_0.19.1_linux_amd64.bz2" in installer
    assert "restic_0.19.1_linux_arm64.bz2" in installer
    assert "sha256sum --check" in installer
    assert "^restic 0\\.19\\.1 compiled with go" in installer
    assert '"$release_dir/scripts/install-restic.sh"' in workflow


def test_deferred_media_deploy_is_explicit_and_skips_heavy_runtime():
    root = Path(__file__).parents[3]
    workflow = root.joinpath(".github/workflows/deploy.yml").read_text()
    preflight = root.joinpath("scripts/single-user-preflight.sh").read_text()
    backup = root.joinpath("scripts/auth-cutover-backup.sh").read_text()

    assert "media_mode" in workflow
    assert "deferred" in workflow
    assert '[ "$MEDIA_PIPELINE_ENABLED" = "false" ]' in preflight
    assert 'if [ "$MEDIA_MODE" = "full" ]' in workflow
    assert "tee >(docker exec -i" not in backup
    assert (
        'incomplete_destination="$BACKUP_ROOT/.auth-cutover-$timestamp.incomplete"'
        in backup
    )
    assert '--decrypt "$encrypted_dump" >/dev/null' in backup
    assert 'restore_status="${PIPESTATUS[1]}"' in backup
    assert 'cd "$incomplete_destination"' in backup
    assert "sha256sum database.dump.gpg > SHA256SUMS" in backup
    assert "sha256sum --check SHA256SUMS" in backup
    assert 'sha256sum "$encrypted_dump"' not in backup
    assert 'plain_dump="$work_dir/database.dump"' not in backup
    assert 'verification_dump="$work_dir/database-verify.dump"' not in backup


def test_production_deploy_tolerates_slow_imports_and_stalled_ssh_sessions():
    root = Path(__file__).parents[3]
    workflow = root.joinpath(".github/workflows/deploy.yml").read_text()

    assert "inspect ping --timeout=30" in workflow
    assert "celery_ping_output=$(" in workflow
    assert '[[ "$celery_ping_output" == *pong* ]]' in workflow
    assert "| grep -q pong" not in workflow
    assert workflow.count("-o ConnectTimeout=10") == 6
    assert workflow.count("-o ServerAliveInterval=15") == 6
    assert workflow.count("-o ServerAliveCountMax=2") == 6
