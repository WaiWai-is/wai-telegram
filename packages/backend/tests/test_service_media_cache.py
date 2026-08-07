import hashlib
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.media_cache_service import (
    MediaCacheError,
    MediaCacheBusy,
    _RedisLease,
    _cache_key,
    _fetch_lock_key,
    _ensure_media_root,
    _prepare_partial_download,
    _recover_completed_download,
    _stream_download,
)


def test_fetch_lock_stays_stable_while_media_object_path_is_versioned():
    user_id = uuid4()

    unresolved = _cache_key(user_id, -100123, 77)
    resolved = _cache_key(user_id, -100123, 77, "document:123:456:2:reference")

    assert resolved != unresolved
    assert _fetch_lock_key(user_id, -100123, 77) == _fetch_lock_key(
        user_id, -100123, 77
    )


class _Chunks:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Client:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def iter_download(self, media, **kwargs):
        self.calls.append((media, kwargs))
        return _Chunks(self.chunks)


async def test_stream_download_resumes_part_and_hashes_full_file(tmp_path):
    part = tmp_path / "original.part"
    part.write_bytes(b"existing-")
    client = _Client([b"chunk-1", b"chunk-2"])

    with (
        patch("app.services.media_cache_service.settings") as service_settings,
        patch(
            "app.services.media_cache_service._save_progress",
            new_callable=AsyncMock,
        ) as save_progress,
    ):
        service_settings.media_download_chunk_bytes = 512 * 1024
        service_settings.media_download_stall_timeout_seconds = 120
        service_settings.media_progress_checkpoint_bytes = 4
        size, digest = await _stream_download(
            client,
            "telegram-media",
            part,
            uuid4(),
        )

    expected = b"existing-chunk-1chunk-2"
    assert part.read_bytes() == expected
    assert size == len(expected)
    assert digest == hashlib.sha256(expected).hexdigest()
    assert client.calls[0][1]["offset"] == len(b"existing-")
    assert save_progress.await_count >= 2


async def test_stream_download_uses_stall_timeout_per_chunk_not_total(tmp_path):
    part = tmp_path / "original.part"
    client = _Client([b"one", b"two", b"three"])

    with (
        patch("app.services.media_cache_service.settings") as service_settings,
        patch(
            "app.services.media_cache_service._save_progress",
            new_callable=AsyncMock,
        ),
    ):
        service_settings.media_download_chunk_bytes = 512 * 1024
        service_settings.media_download_stall_timeout_seconds = 120
        service_settings.media_progress_checkpoint_bytes = 1024
        size, _digest = await _stream_download(
            client,
            "telegram-media",
            part,
            uuid4(),
        )

    assert size == 11


def test_production_cache_refuses_to_write_when_volume_is_not_mounted(tmp_path):
    with patch("app.services.media_cache_service.settings") as service_settings:
        service_settings.environment = "production"
        service_settings.media_root = tmp_path / "not-a-mount"

        with pytest.raises(MediaCacheError, match="not mounted"):
            _ensure_media_root()


def test_oversized_partial_download_is_reset_before_resume(tmp_path):
    part = tmp_path / "original.part"
    part.write_bytes(b"corrupt-extra-bytes")

    offset = _prepare_partial_download(part, expected_size=4)

    assert offset == 0
    assert part.read_bytes() == b""


async def test_redis_lease_loss_is_detected_before_more_file_writes():
    redis = AsyncMock()
    redis.get.return_value = b"another-owner"
    lease = _RedisLease(redis, "media:fetch:test")

    with pytest.raises(MediaCacheBusy, match="lease was lost"):
        await lease.assert_owned()


async def test_completed_file_is_recovered_after_crash_between_rename_and_db_commit(
    tmp_path,
):
    completed = tmp_path / "original.mp4"
    completed.write_bytes(b"completed-video")

    recovered = await _recover_completed_download(tmp_path, expected_size=15)

    assert recovered is not None
    path, size, digest = recovered
    assert path == completed
    assert size == 15
    assert digest == hashlib.sha256(b"completed-video").hexdigest()
