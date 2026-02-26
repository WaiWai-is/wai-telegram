import asyncio
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import redis
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.sync_job import SyncJob, SyncStatus
from app.services.rate_limiter import check_budget
from app.services.sync_service import create_sync_job, sync_messages

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis client for distributed locks and progress keys.
redis_client = redis.from_url(settings.redis_url)

# Lock and progress configuration
LOCK_TTL = 180
LOCK_REFRESH_INTERVAL = 30
SYNC_PROGRESS_TTL = 3600  # 1h Redis key TTL for single-chat sync progress
BULK_SYNC_TTL = 86400  # 24h Redis key TTL for bulk progress
JOB_HEARTBEAT_TTL = 600
STALE_JOB_THRESHOLD = timedelta(minutes=15)


def _single_heartbeat_key(job_id: UUID) -> str:
    return f"sync:{job_id}:heartbeat"


def _bulk_heartbeat_key(job_id: UUID) -> str:
    return f"bulk:{job_id}:heartbeat"


def _touch_single_heartbeat(job_id: UUID) -> None:
    redis_client.setex(_single_heartbeat_key(job_id), JOB_HEARTBEAT_TTL, "1")


def _touch_bulk_heartbeat(job_id: UUID) -> None:
    redis_client.setex(_bulk_heartbeat_key(job_id), JOB_HEARTBEAT_TTL, "1")


def _cleanup_single_progress(job_id: UUID) -> None:
    redis_client.delete(
        f"sync:{job_id}:total",
        f"sync:{job_id}:seen",
        _single_heartbeat_key(job_id),
    )


def _cleanup_bulk_progress(job_id: UUID) -> None:
    redis_client.delete(
        f"bulk:{job_id}:total",
        f"bulk:{job_id}:completed",
        f"bulk:{job_id}:current_chat",
        _bulk_heartbeat_key(job_id),
    )


def _release_lock_if_owned(user_id: UUID, expected_owner: str) -> None:
    lock_key = f"sync:{user_id}:lock"
    redis_client.eval(
        """
        local value = redis.call('get', KEYS[1])
        if not value then
            return 0
        end
        local ok, decoded = pcall(cjson.decode, value)
        if not ok then
            return 0
        end
        if decoded['owner'] == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """,
        1,
        lock_key,
        expected_owner,
    )


class DistributedLock:
    """Distributed lock with automatic heartbeat refresh."""

    def __init__(self, user_id: UUID, owner: str, ttl: int = LOCK_TTL):
        self.user_id = user_id
        self.lock_key = f"sync:{user_id}:lock"
        self.token = str(uuid4())
        self.owner = owner
        self.ttl = ttl
        self.payload = json.dumps(
            {"owner": self.owner, "token": self.token},
            separators=(",", ":"),
            sort_keys=True,
        )
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """Acquire the lock atomically."""
        acquired = bool(
            redis_client.set(self.lock_key, self.payload, nx=True, ex=self.ttl)
        )
        if acquired:
            self._start_heartbeat()
        return acquired

    def release(self) -> None:
        """Release the lock and stop heartbeat."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        self._release_if_owner()

    def refresh(self) -> bool:
        """Refresh lock TTL only while still owning the lock."""
        return bool(
            redis_client.eval(
                """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('expire', KEYS[1], ARGV[2])
                end
                return 0
                """,
                1,
                self.lock_key,
                self.payload,
                self.ttl,
            )
        )

    def _release_if_owner(self) -> None:
        redis_client.eval(
            """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
            """,
            1,
            self.lock_key,
            self.payload,
        )

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_heartbeat.wait(timeout=LOCK_REFRESH_INTERVAL):
            try:
                if not self.refresh():
                    logger.warning(
                        "Lost sync lock ownership for user %s, stopping heartbeat",
                        self.user_id,
                    )
                    self._stop_heartbeat.set()
                    break
            except Exception as e:
                logger.error("Failed to refresh lock: %s", e)


@shared_task(bind=True, max_retries=3)
def sync_chat_task(
    self,
    user_id: str,
    chat_id: str,
    job_id: str | None = None,
    limit: int | None = None,
):
    """Celery task to sync messages for a chat."""
    from telethon.errors import FloodWaitError

    user_uuid = UUID(user_id)
    chat_uuid = UUID(chat_id)
    job_uuid = UUID(job_id) if job_id else None

    if not check_budget():
        logger.warning("Rate budget exhausted, deferring sync for chat %s", chat_id)
        raise self.retry(exc=Exception("Rate budget exhausted"), countdown=300)

    lock_owner = f"chat:{job_uuid}" if job_uuid else f"chat:{chat_uuid}"
    lock = DistributedLock(user_uuid, owner=lock_owner)
    if not lock.acquire():
        logger.info("Sync already in progress for user %s", user_id)
        if job_uuid:
            asyncio.run(
                _mark_job_state(
                    job_uuid,
                    SyncStatus.FAILED,
                    "Another sync is already in progress",
                )
            )
        return {"status": "skipped", "reason": "sync_in_progress"}

    try:
        result = asyncio.run(_run_sync(user_uuid, chat_uuid, limit, job_uuid))
        return result
    except FloodWaitError as e:
        countdown = max(1, int(e.seconds * settings.flood_wait_multiplier))
        asyncio.run(
            _mark_job_state(
                job_uuid,
                SyncStatus.PENDING,
                f"rate_limited: retry_after_seconds={countdown}",
            )
        )
        logger.warning("FloodWait for chat %s: retrying in %ss", chat_id, countdown)
        try:
            raise self.retry(exc=e, countdown=countdown)
        except MaxRetriesExceededError:
            asyncio.run(
                _mark_job_state(
                    job_uuid,
                    SyncStatus.FAILED,
                    "Exceeded max retries after repeated FloodWait responses",
                )
            )
            raise
    except Exception as e:
        backoff = 60 * (3**self.request.retries)
        will_retry = self.request.retries < self.max_retries
        asyncio.run(
            _mark_job_state(
                job_uuid,
                SyncStatus.PENDING if will_retry else SyncStatus.FAILED,
                f"sync_error: {e}"
                + (f" retry_after_seconds={backoff}" if will_retry else ""),
            )
        )
        if will_retry:
            logger.error(
                "Sync failed for chat %s: %s, retrying in %ss", chat_id, e, backoff
            )
            try:
                raise self.retry(exc=e, countdown=backoff)
            except MaxRetriesExceededError:
                asyncio.run(
                    _mark_job_state(
                        job_uuid,
                        SyncStatus.FAILED,
                        f"Exceeded max retries: {e}",
                    )
                )
                raise
        raise
    finally:
        lock.release()
        if job_uuid:
            _cleanup_single_progress(job_uuid)


async def _run_sync(
    user_id: UUID,
    chat_id: UUID,
    limit: int | None,
    job_id: UUID | None = None,
) -> dict:
    """Run single chat sync operation."""
    async with get_db_context() as db:
        if job_id:
            result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                raise ValueError(f"Sync job {job_id} not found")
        else:
            job = await create_sync_job(db, user_id, chat_id)

        job.status = SyncStatus.IN_PROGRESS
        job.error_message = None
        job.completed_at = None
        await db.commit()

        if limit:
            redis_client.setex(f"sync:{job.id}:total", SYNC_PROGRESS_TTL, limit)
        _touch_single_heartbeat(job.id)

        def _on_progress(seen: int) -> None:
            redis_client.setex(f"sync:{job.id}:seen", SYNC_PROGRESS_TTL, seen)
            _touch_single_heartbeat(job.id)

        count = await sync_messages(
            db, user_id, chat_id, job.id, limit, on_progress=_on_progress
        )

        job.status = SyncStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.messages_processed = count
        await db.commit()

        return {
            "status": "completed",
            "job_id": str(job.id),
            "messages_synced": count,
        }


@shared_task(bind=True, max_retries=0)
def sync_all_chats_task(self, user_id: str, job_id: str, limit_per_chat: int = 500):
    """Bulk sync: sequentially sync messages for all user chats."""
    user_uuid = UUID(user_id)
    job_uuid = UUID(job_id)

    lock = DistributedLock(user_uuid, owner=f"bulk:{job_uuid}")
    if not lock.acquire():
        logger.info("Bulk sync skipped — another sync in progress for user %s", user_id)
        asyncio.run(
            _mark_job_state(
                job_uuid, SyncStatus.FAILED, "Another sync is already in progress"
            )
        )
        return {"status": "skipped", "reason": "sync_in_progress"}

    try:
        asyncio.run(_run_bulk_sync(user_uuid, job_uuid, limit_per_chat))
        return {"status": "completed", "job_id": job_id}
    except Exception as e:
        asyncio.run(_mark_job_state(job_uuid, SyncStatus.FAILED, str(e)))
        logger.error("Bulk sync failed for user %s: %s", user_id, e)
        raise
    finally:
        lock.release()
        _cleanup_bulk_progress(job_uuid)


async def _run_bulk_sync(user_id: UUID, job_id: UUID, limit_per_chat: int) -> None:
    """Run bulk sync for all user chats sequentially."""
    from app.models.chat import TelegramChat

    async with get_db_context() as db:
        result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one()
        job.status = SyncStatus.IN_PROGRESS
        job.error_message = None
        job.completed_at = None
        await db.commit()

        result = await db.execute(
            select(TelegramChat)
            .where(TelegramChat.user_id == user_id)
            .order_by(TelegramChat.last_sync_at.asc().nulls_first())
        )
        chats = result.scalars().all()
        total = len(chats)

        redis_client.setex(f"bulk:{job_id}:total", BULK_SYNC_TTL, total)
        redis_client.setex(f"bulk:{job_id}:completed", BULK_SYNC_TTL, 0)
        _touch_bulk_heartbeat(job_id)

        effective_limit = limit_per_chat if limit_per_chat > 0 else None
        total_messages = 0

        for i, chat in enumerate(chats):
            redis_client.setex(
                f"bulk:{job_id}:current_chat", BULK_SYNC_TTL, chat.title[:80]
            )
            _touch_bulk_heartbeat(job_id)

            sub_job = None
            try:
                sub_job = await create_sync_job(db, user_id, chat.id)
                sub_job.status = SyncStatus.IN_PROGRESS
                await db.commit()
                if effective_limit is not None:
                    redis_client.setex(
                        f"sync:{sub_job.id}:total", SYNC_PROGRESS_TTL, effective_limit
                    )
                _touch_single_heartbeat(sub_job.id)

                def _on_sub_progress(
                    seen: int, current_sub_job_id: UUID = sub_job.id
                ) -> None:
                    redis_client.setex(
                        f"sync:{current_sub_job_id}:seen", SYNC_PROGRESS_TTL, seen
                    )
                    _touch_single_heartbeat(current_sub_job_id)
                    _touch_bulk_heartbeat(job_id)

                count = await sync_messages(
                    db,
                    user_id,
                    chat.id,
                    sub_job.id,
                    effective_limit,
                    on_progress=_on_sub_progress,
                )

                sub_job.status = SyncStatus.COMPLETED
                sub_job.completed_at = datetime.now(UTC)
                sub_job.messages_processed = count
                await db.commit()

                total_messages += count
                logger.info(
                    "Bulk sync: chat %s/%s '%s': %s messages",
                    i + 1,
                    total,
                    chat.title[:40],
                    count,
                )
            except Exception as e:
                logger.error(
                    "Bulk sync: failed chat %s (%s): %s", chat.id, chat.title[:40], e
                )
                if sub_job is not None:
                    try:
                        sub_job.status = SyncStatus.FAILED
                        sub_job.error_message = str(e)[:500]
                        await db.commit()
                    except Exception as commit_err:
                        logger.error(
                            "Bulk sync: failed to mark sub-job for chat %s: %s",
                            chat.id,
                            commit_err,
                        )
            finally:
                redis_client.setex(f"bulk:{job_id}:completed", BULK_SYNC_TTL, i + 1)
                if sub_job is not None:
                    _cleanup_single_progress(sub_job.id)

            job.messages_processed = total_messages
            await db.commit()
            _touch_bulk_heartbeat(job_id)

        job.status = SyncStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.messages_processed = total_messages
        await db.commit()


@shared_task
def listener_health_check():
    """Check listener health for users with realtime sync enabled."""
    return asyncio.run(_listener_health_check())


async def _listener_health_check() -> dict:
    """Ensure listener heartbeats exist for users with realtime sync enabled."""
    from app.models.settings import UserSettings

    checked = 0
    restarted = 0

    async with get_db_context() as db:
        result = await db.execute(
            select(UserSettings).where(UserSettings.realtime_sync_enabled == True)
        )
        for user_settings in result.scalars().all():
            user_id = user_settings.user_id
            checked += 1

            if not redis_client.get(f"listener:active:{user_id}"):
                redis_client.publish(
                    "listener:cmd:global",
                    json.dumps({"command": "start_user", "user_id": str(user_id)}),
                )
                restarted += 1
                logger.warning(
                    "Listener inactive for user %s, sent start command", user_id
                )

    return {"checked": checked, "restarted": restarted}


@shared_task
def reap_stale_sync_jobs() -> dict:
    """Mark stale IN_PROGRESS jobs as FAILED when heartbeat is missing."""
    return asyncio.run(_reap_stale_sync_jobs())


async def _reap_stale_sync_jobs() -> dict:
    stale_cutoff = datetime.now(UTC) - STALE_JOB_THRESHOLD
    scanned = 0
    expired = 0

    async with get_db_context() as db:
        result = await db.execute(
            select(SyncJob).where(
                SyncJob.status == SyncStatus.IN_PROGRESS,
                SyncJob.updated_at < stale_cutoff,
            )
        )
        jobs = result.scalars().all()
        scanned = len(jobs)

        for job in jobs:
            heartbeat_key = (
                _bulk_heartbeat_key(job.id)
                if job.chat_id is None
                else _single_heartbeat_key(job.id)
            )
            if redis_client.get(heartbeat_key):
                continue

            job.status = SyncStatus.FAILED
            job.error_message = "Automatically expired: stale sync heartbeat"
            expired += 1

            if job.chat_id is None:
                _cleanup_bulk_progress(job.id)
                _release_lock_if_owned(job.user_id, f"bulk:{job.id}")
            else:
                _cleanup_single_progress(job.id)
                _release_lock_if_owned(job.user_id, f"chat:{job.id}")

        if expired:
            await db.commit()

    if expired:
        logger.warning("Expired %s stale sync jobs (scanned=%s)", expired, scanned)

    return {"scanned": scanned, "expired": expired}


async def _mark_job_state(
    job_id: UUID | None,
    status: SyncStatus,
    error_message: str | None = None,
) -> None:
    """Update sync job status in a standalone transaction."""
    if not job_id:
        return

    terminal = {SyncStatus.COMPLETED, SyncStatus.FAILED, SyncStatus.CANCELLED}

    async with get_db_context() as db:
        result = await db.execute(
            select(SyncJob).where(SyncJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return

        # Do not downgrade terminal states.
        if job.status in terminal and status not in terminal:
            return

        job.status = status
        job.error_message = error_message
        if status == SyncStatus.COMPLETED:
            job.completed_at = datetime.now(UTC)
        elif status != SyncStatus.COMPLETED:
            job.completed_at = None

        await db.commit()
