"""Persistent, resumable Telegram media cache outside release directories."""

import asyncio
import errno
import hashlib
import logging
import mimetypes
import os
import re
import shutil
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.chat import TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, MediaStage
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.models.user import User
from app.services.media_content_service import MediaInfo, get_media_info
from app.services.messaging_service import _resolve_chat_entity
from app.services.telegram_links import media_download_filename

logger = logging.getLogger(__name__)
settings = get_settings()


class MediaCacheError(RuntimeError):
    code = "media_cache_error"


class MediaCacheBusy(MediaCacheError):
    code = "fetch_in_progress"


class MediaSourceDeleted(MediaCacheError):
    code = "source_deleted"


class MediaDiskFull(MediaCacheError):
    code = "disk_full"


class MediaDownloadStalled(MediaCacheError):
    code = "download_stalled"


@dataclass(frozen=True)
class CachedMedia:
    media_object_id: UUID
    message_id: UUID
    status: str
    stage: str
    path: Path | None
    relative_path: str | None
    file_name: str | None
    mime_type: str | None
    size_bytes: int | None
    sha256: str | None
    byte_offset: int
    retry_after: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None


def _cache_key(
    user_id: UUID,
    telegram_chat_id: int,
    telegram_message_id: int,
    telegram_media_id: str | None = None,
) -> str:
    identity = (
        f"v2:{user_id}:{telegram_chat_id}:{telegram_message_id}:"
        f"{telegram_media_id or 'unresolved'}"
    ).encode()
    return hashlib.sha256(identity).hexdigest()


def _fetch_lock_key(
    user_id: UUID,
    telegram_chat_id: int,
    telegram_message_id: int,
) -> str:
    """Return the stable lock identity shared by every media revision."""
    identity = f"v1:{user_id}:{telegram_chat_id}:{telegram_message_id}".encode()
    return hashlib.sha256(identity).hexdigest()


def telegram_media_identity(message: Any) -> str | None:
    """Return a stable, non-secret identity for an MTProto media object."""
    media = getattr(message, "media", None)
    for kind in ("document", "photo"):
        item = getattr(media, kind, None)
        if item is None:
            continue
        item_id = getattr(item, "id", None)
        if item_id is None:
            continue
        reference = getattr(item, "file_reference", None) or b""
        if not isinstance(reference, bytes):
            reference = bytes(reference)
        reference_hash = hashlib.sha256(reference).hexdigest()[:16]
        return ":".join(
            (
                kind,
                str(item_id),
                str(getattr(item, "access_hash", "")),
                str(getattr(item, "dc_id", "")),
                reference_hash,
            )
        )
    return None


def _safe_suffix(file_name: str | None, mime_type: str | None) -> str:
    suffix = Path(file_name).suffix if file_name else ""
    if not suffix and mime_type:
        suffix = mimetypes.guess_extension(mime_type) or ""
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        return ".bin"
    return suffix.lower()


def _absolute_cache_path(relative_path: str) -> Path:
    root = settings.media_root.resolve()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents:
        raise MediaCacheError("Invalid media cache path")
    return candidate


def _ensure_media_root() -> Path:
    from app.services.media_content_service import scope_accumulates_media

    root = settings.media_root
    if settings.environment == "production":
        if not root.is_dir():
            raise MediaCacheError(f"Production media root is missing: {root}")
        # A dedicated volume keeps retained media off the system disk. Nothing is
        # retained when only voice notes and video notes are transcribed, so the
        # writability check below is the whole requirement.
        if scope_accumulates_media() and not root.is_mount():
            raise MediaCacheError(f"Production media volume is not mounted: {root}")
    else:
        root.mkdir(parents=True, exist_ok=True)
    if not os.access(root, os.W_OK | os.X_OK):
        raise MediaCacheError(f"Media cache root is not writable: {root}")
    return root


def _snapshot(obj: MediaObject) -> CachedMedia:
    path = _absolute_cache_path(obj.relative_path) if obj.relative_path else None
    return CachedMedia(
        media_object_id=obj.id,
        message_id=obj.message_id,
        status=str(obj.status),
        stage=str(obj.stage),
        path=path,
        relative_path=obj.relative_path,
        file_name=obj.file_name,
        mime_type=obj.mime_type,
        size_bytes=obj.size_bytes,
        sha256=obj.sha256,
        byte_offset=obj.byte_offset,
        retry_after=obj.retry_after,
        error_code=obj.error_code,
        error_detail=obj.error_detail,
    )


async def _record_cache_metric(name: str) -> None:
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.hincrby("media:metrics", name, 1)
    finally:
        await client.aclose()


async def _load_owned_message(
    db: AsyncSession,
    user_id: UUID,
    message_id: UUID,
) -> tuple[TelegramMessage, TelegramChat]:
    row = (
        await db.execute(
            select(TelegramMessage, TelegramChat)
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .join(User, User.id == TelegramChat.user_id)
            .where(
                TelegramMessage.id == message_id,
                TelegramChat.user_id == user_id,
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise MediaCacheError("Media message is unavailable for the active owner")
    message, chat = row
    if not message.has_media:
        raise MediaCacheError("Message has no downloadable media")
    return message, chat


async def get_or_create_media_object(
    db: AsyncSession,
    user_id: UUID,
    message_id: UUID,
) -> MediaObject:
    message, chat = await _load_owned_message(db, user_id, message_id)
    existing = (
        await db.execute(
            select(MediaObject).where(MediaObject.message_id == message_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise MediaCacheError("Media cache ownership mismatch")
        return existing

    obj = MediaObject(
        user_id=user_id,
        message_id=message_id,
        cache_key=_cache_key(
            user_id,
            chat.telegram_chat_id,
            message.telegram_message_id,
        ),
        file_name=message.media_file_name,
        mime_type=message.media_mime_type,
        size_bytes=message.media_file_size,
        status=MediaObjectStatus.PENDING,
        stage=MediaStage.FETCH,
    )
    try:
        async with db.begin_nested():
            db.add(obj)
            await db.flush()
    except IntegrityError:
        obj = (
            await db.execute(
                select(MediaObject).where(MediaObject.message_id == message_id)
            )
        ).scalar_one()
    return obj


def media_preparation_needs_enqueue(
    message: TelegramMessage,
    media_object: MediaObject,
) -> bool:
    """Return true only when no durable dispatch or processing claim exists."""
    if media_object.status in {
        MediaObjectStatus.READY,
        MediaObjectStatus.READY_DOWNLOAD_ONLY,
        MediaObjectStatus.FETCHING,
        MediaObjectStatus.EXTRACTING,
        MediaObjectStatus.INDEXING,
        MediaObjectStatus.PROCESSING,
        MediaObjectStatus.RETRY_WAIT,
    }:
        return False
    return message.media_processing_status not in {
        MediaProcessingStatus.PENDING,
        MediaProcessingStatus.QUEUED,
        MediaProcessingStatus.PROCESSING,
    }


class _RedisLease:
    def __init__(self, client: aioredis.Redis, key: str):
        self.client = client
        self.key = key
        self.token = uuid4().hex
        self.ttl = settings.media_lock_ttl_seconds
        self._heartbeat: asyncio.Task | None = None
        self._lost = asyncio.Event()

    async def acquire(self) -> bool:
        acquired = bool(
            await self.client.set(self.key, self.token, nx=True, ex=self.ttl)
        )
        if acquired:
            self._heartbeat = asyncio.create_task(self._heartbeat_loop())
        return acquired

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(max(10, self.ttl // 3))
            try:
                refreshed = await self.client.eval(
                    """
                    if redis.call('get', KEYS[1]) == ARGV[1] then
                      return redis.call('expire', KEYS[1], ARGV[2])
                    end
                    return 0
                    """,
                    1,
                    self.key,
                    self.token,
                    self.ttl,
                )
            except Exception:
                self._lost.set()
                return
            if not refreshed:
                self._lost.set()
                return

    async def assert_owned(self) -> None:
        if self._lost.is_set():
            raise MediaCacheBusy("Media fetch lease was lost")
        current = await self.client.get(self.key)
        if current not in {self.token, self.token.encode()}:
            self._lost.set()
            raise MediaCacheBusy("Media fetch lease was lost")

    async def release(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat
        await self.client.eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
              return redis.call('del', KEYS[1])
            end
            return 0
            """,
            1,
            self.key,
            self.token,
        )


@asynccontextmanager
async def _media_fetch_lease(lock_key: str):
    client = aioredis.from_url(settings.redis_url)
    lease = _RedisLease(client, f"media:fetch:{lock_key}")
    try:
        if not await lease.acquire():
            raise MediaCacheBusy("Another worker is already fetching this media")
        yield lease
    finally:
        if lease._heartbeat is not None:
            await lease.release()
        await client.aclose()


def _hash_file(path: Path) -> Any:
    digest = hashlib.sha256()
    if not path.is_file():
        return digest
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            digest.update(block)
    return digest


async def _recover_completed_download(
    directory: Path,
    expected_size: int | None,
) -> tuple[Path, int, str] | None:
    """Adopt a completed original left by a crash before the DB checkpoint."""
    candidates = [
        path
        for path in directory.glob("original.*")
        if path.is_file() and path.name != "original.part"
    ]
    if len(candidates) != 1:
        return None
    path = candidates[0]
    size = path.stat().st_size
    if size <= 0 or (expected_size is not None and size != expected_size):
        return None
    digest = await asyncio.to_thread(_hash_file, path)
    return path, size, digest.hexdigest()


def _prepare_partial_download(part_path: Path, expected_size: int | None) -> int:
    """Return a safe resume offset, resetting a corrupt oversized partial."""
    if not part_path.is_file():
        return 0
    existing_size = part_path.stat().st_size
    if expected_size is not None and existing_size > expected_size:
        with part_path.open("wb") as destination:
            destination.flush()
            os.fsync(destination.fileno())
        return 0
    return existing_size


async def _save_progress(media_object_id: UUID, byte_offset: int) -> None:
    async with get_db_context() as db:
        obj = (
            await db.execute(
                select(MediaObject)
                .join(TelegramMessage, TelegramMessage.id == MediaObject.message_id)
                .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
                .join(User, User.id == TelegramChat.user_id)
                .where(
                    MediaObject.id == media_object_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if obj is not None:
            obj.byte_offset = byte_offset
            obj.status = MediaObjectStatus.FETCHING
            obj.error_code = None
            obj.error_detail = None


async def _stream_download(
    client,
    telegram_media,
    part_path: Path,
    media_object_id: UUID,
    *,
    assert_lease=None,
) -> tuple[int, str]:
    part_path.parent.mkdir(parents=True, exist_ok=True)
    offset = part_path.stat().st_size if part_path.is_file() else 0
    iterator = client.iter_download(
        telegram_media,
        offset=offset,
        request_size=settings.media_download_chunk_bytes,
        chunk_size=settings.media_download_chunk_bytes,
    ).__aiter__()
    checkpoint_at = offset + settings.media_progress_checkpoint_bytes
    try:
        with part_path.open("ab", buffering=1024 * 1024) as destination:
            while True:
                try:
                    async with asyncio.timeout(
                        settings.media_download_stall_timeout_seconds
                    ):
                        chunk = await anext(iterator)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise MediaDownloadStalled(
                        "Telegram media download made no progress for "
                        f"{settings.media_download_stall_timeout_seconds:g} seconds"
                    ) from exc
                if not chunk:
                    continue
                if assert_lease is not None:
                    await assert_lease()
                try:
                    destination.write(chunk)
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise MediaDiskFull("Media volume is full") from exc
                    raise
                offset += len(chunk)
                if offset >= checkpoint_at:
                    destination.flush()
                    await _save_progress(media_object_id, offset)
                    checkpoint_at = offset + settings.media_progress_checkpoint_bytes
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        await _save_progress(media_object_id, offset)
        raise
    await _save_progress(media_object_id, offset)
    digest = await asyncio.to_thread(_hash_file, part_path)
    return offset, digest.hexdigest()


async def _mark_cache_error(media_object_id: UUID, error: Exception) -> None:
    status = MediaObjectStatus.FAILED
    if isinstance(error, MediaDiskFull):
        status = MediaObjectStatus.DISK_FULL
    elif isinstance(error, MediaSourceDeleted):
        status = MediaObjectStatus.SOURCE_DELETED
    elif isinstance(error, (MediaDownloadStalled, FloodWaitError)):
        status = MediaObjectStatus.RETRY_WAIT
    async with get_db_context() as db:
        obj = (
            await db.execute(
                select(MediaObject)
                .join(TelegramMessage, TelegramMessage.id == MediaObject.message_id)
                .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
                .join(User, User.id == TelegramChat.user_id)
                .where(
                    MediaObject.id == media_object_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if obj is not None:
            obj.status = status
            obj.error_code = getattr(error, "code", type(error).__name__)
            obj.error_detail = str(error)[:1000]


async def fetch_media_to_cache(
    user_id: UUID,
    message_id: UUID,
    *,
    get_media_client,
) -> CachedMedia:
    """Fetch one Telegram object with resume and an owner-scoped Redis lease."""
    async with get_db_context() as db:
        obj = await get_or_create_media_object(db, user_id, message_id)
        message, chat = await _load_owned_message(db, user_id, message_id)
        if obj.relative_path and obj.sha256:
            snapshot = _snapshot(obj)
            if snapshot.path and snapshot.path.is_file():
                obj.last_accessed_at = datetime.now(UTC)
                await _record_cache_metric("hits")
                return snapshot
            raise MediaCacheError("Cached media file is missing from the media volume")
        cache_key = obj.cache_key
        media_object_id = obj.id
        initial_media_identity = obj.telegram_media_id
        lock_key = _fetch_lock_key(
            user_id,
            chat.telegram_chat_id,
            message.telegram_message_id,
        )

    try:
        async with _media_fetch_lease(lock_key) as lease:
            async with get_db_context() as db:
                obj = await db.get(MediaObject, media_object_id)
                if obj is None:
                    raise MediaCacheError("Media cache record disappeared")
                if obj.relative_path and obj.sha256:
                    snapshot = _snapshot(obj)
                    if snapshot.path and snapshot.path.is_file():
                        await _record_cache_metric("hits")
                        return snapshot
                await _record_cache_metric("misses")
                message, chat = await _load_owned_message(db, user_id, message_id)
                client = await get_media_client(user_id, db)
                peer = await _resolve_chat_entity(client, db, chat)
                obj.status = MediaObjectStatus.FETCHING
                obj.stage = MediaStage.FETCH
                obj.error_code = None
                obj.error_detail = None

            telegram_message = await client.get_messages(
                peer, ids=message.telegram_message_id
            )
            if telegram_message is None or not getattr(telegram_message, "media", None):
                raise MediaSourceDeleted("Telegram source media was deleted")
            info: MediaInfo | None = get_media_info(telegram_message)
            if info is None:
                raise MediaSourceDeleted("Telegram source has no downloadable media")
            media_identity = telegram_media_identity(telegram_message)
            async with get_db_context() as db:
                await db.execute(
                    select(TelegramMessage.id)
                    .where(TelegramMessage.id == message_id)
                    .with_for_update()
                )
                obj = (
                    await db.execute(
                        select(MediaObject)
                        .where(MediaObject.id == media_object_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if obj is None:
                    raise MediaCacheError("Media cache record disappeared")
                if (
                    obj.telegram_media_id != initial_media_identity
                    and obj.telegram_media_id != media_identity
                ):
                    raise MediaCacheBusy("Telegram media changed during fetch")
                obj.telegram_media_id = media_identity
                resolved_cache_key = _cache_key(
                    user_id,
                    chat.telegram_chat_id,
                    message.telegram_message_id,
                    media_identity,
                )
                if obj.cache_key != resolved_cache_key:
                    obj.cache_key = resolved_cache_key
                cache_key = resolved_cache_key

            expected_size = info.file_size or message.media_file_size
            media_root = _ensure_media_root()
            free_bytes = shutil.disk_usage(media_root).free
            part_relative = str(Path(cache_key[:2]) / cache_key / "original.part")
            part_path = _absolute_cache_path(part_relative)
            recovered = await _recover_completed_download(
                part_path.parent,
                expected_size,
            )
            if recovered is not None:
                final_path, size_bytes, sha256 = recovered
                final_relative = str(final_path.relative_to(media_root))
                async with get_db_context() as db:
                    await db.execute(
                        select(TelegramMessage.id)
                        .where(TelegramMessage.id == message_id)
                        .with_for_update()
                    )
                    obj = (
                        await db.execute(
                            select(MediaObject)
                            .where(MediaObject.id == media_object_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if obj is None:
                        raise MediaCacheError("Media cache record disappeared")
                    if (
                        obj.telegram_media_id != media_identity
                        or obj.cache_key != cache_key
                    ):
                        raise MediaCacheBusy("Telegram media changed during fetch")
                    obj.relative_path = final_relative
                    obj.file_name = media_download_filename(
                        info.file_name or message.media_file_name,
                        info.mime_type or message.media_mime_type,
                    )
                    obj.mime_type = (
                        info.mime_type
                        or message.media_mime_type
                        or "application/octet-stream"
                    )
                    obj.size_bytes = size_bytes
                    obj.byte_offset = size_bytes
                    obj.sha256 = sha256
                    obj.status = MediaObjectStatus.CACHED
                    obj.stage = MediaStage.EXTRACTION
                    obj.fetched_at = datetime.now(UTC)
                    obj.last_accessed_at = datetime.now(UTC)
                    obj.error_code = None
                    obj.error_detail = None
                    return _snapshot(obj)
            existing_size = _prepare_partial_download(part_path, expected_size)
            if expected_size is not None and expected_size - existing_size > free_bytes:
                raise MediaDiskFull(
                    f"Media volume needs {expected_size - existing_size} additional bytes"
                )

            size_bytes, sha256 = await _stream_download(
                client,
                telegram_message.media,
                part_path,
                media_object_id,
                assert_lease=lease.assert_owned,
            )
            if size_bytes <= 0:
                raise MediaCacheError("Telegram media download returned no bytes")
            if expected_size is not None and size_bytes != expected_size:
                raise MediaCacheError(
                    f"Telegram media size mismatch: expected {expected_size}, got {size_bytes}"
                )

            suffix = _safe_suffix(
                info.file_name or message.media_file_name,
                info.mime_type or message.media_mime_type,
            )
            final_relative = str(Path(cache_key[:2]) / cache_key / f"original{suffix}")
            final_path = _absolute_cache_path(final_relative)
            async with get_db_context() as db:
                await db.execute(
                    select(TelegramMessage.id)
                    .where(TelegramMessage.id == message_id)
                    .with_for_update()
                )
                obj = (
                    await db.execute(
                        select(MediaObject)
                        .where(MediaObject.id == media_object_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if obj is None:
                    raise MediaCacheError("Media cache record disappeared")
                if (
                    obj.telegram_media_id != media_identity
                    or obj.cache_key != cache_key
                ):
                    raise MediaCacheBusy("Telegram media changed during fetch")
                await lease.assert_owned()
                os.replace(part_path, final_path)
                obj.relative_path = final_relative
                obj.file_name = media_download_filename(
                    info.file_name or message.media_file_name,
                    info.mime_type or message.media_mime_type,
                )
                obj.mime_type = (
                    info.mime_type
                    or message.media_mime_type
                    or "application/octet-stream"
                )
                obj.size_bytes = size_bytes
                obj.byte_offset = size_bytes
                obj.sha256 = sha256
                obj.telegram_media_id = media_identity
                obj.status = MediaObjectStatus.CACHED
                obj.stage = MediaStage.EXTRACTION
                obj.fetched_at = datetime.now(UTC)
                obj.last_accessed_at = datetime.now(UTC)
                obj.error_code = None
                obj.error_detail = None
                await db.flush()
                return _snapshot(obj)
    except MediaCacheBusy:
        async with get_db_context() as db:
            obj = await db.get(MediaObject, media_object_id)
            if obj is None:
                raise
            return _snapshot(obj)
    except Exception as exc:
        await _mark_cache_error(media_object_id, exc)
        raise


async def get_cached_media_for_download(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    telegram_message_id: int,
) -> CachedMedia | None:
    obj = (
        await db.execute(
            select(MediaObject)
            .join(TelegramMessage, TelegramMessage.id == MediaObject.message_id)
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .join(User, User.id == MediaObject.user_id)
            .where(
                MediaObject.user_id == user_id,
                TelegramChat.user_id == user_id,
                TelegramMessage.chat_id == chat_id,
                TelegramMessage.telegram_message_id == telegram_message_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if obj is None or not obj.relative_path or not obj.sha256:
        return None
    snapshot = _snapshot(obj)
    if snapshot.path is None or not snapshot.path.is_file():
        raise MediaCacheError("Cached media file is missing from the media volume")
    obj.last_accessed_at = datetime.now(UTC)
    return snapshot
