import asyncio
import logging
import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.sync_job import SyncJob, SyncStatus
from app.services.rate_limiter import check_budget
from app.services.sync_service import sync_messages, create_sync_job

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis client for distributed locks
redis_client = redis.from_url(settings.redis_url)

# Lock configuration
LOCK_TTL = 300  # 5 minutes
LOCK_REFRESH_INTERVAL = 60  # Refresh every minute


class DistributedLock:
    """Distributed lock with automatic heartbeat refresh."""

    def __init__(self, user_id: UUID, ttl: int = LOCK_TTL):
        self.user_id = user_id
        self.lock_key = f"sync:{user_id}:lock"
        self.token = str(uuid4())
        self.ttl = ttl
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """Acquire the lock atomically."""
        acquired = bool(
            redis_client.set(self.lock_key, self.token, nx=True, ex=self.ttl)
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
        """Refresh the lock TTL only when we still own the lock."""
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
                self.token,
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
            self.token,
        )

    def _start_heartbeat(self) -> None:
        """Start background thread to refresh lock TTL."""
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Periodically refresh the lock TTL."""
        while not self._stop_heartbeat.wait(timeout=LOCK_REFRESH_INTERVAL):
            try:
                if not self.refresh():
                    logger.warning(
                        f"Lost sync lock ownership for user {self.user_id}, stopping heartbeat"
                    )
                    self._stop_heartbeat.set()
                    break
                logger.debug(f"Refreshed lock for user {self.user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh lock: {e}")


def acquire_lock(user_id: UUID, ttl: int = LOCK_TTL) -> bool:
    """Acquire a distributed lock for sync operations (legacy function)."""
    lock_key = f"sync:{user_id}:lock"
    return bool(redis_client.set(lock_key, "1", nx=True, ex=ttl))


def release_lock(user_id: UUID) -> None:
    """Release the sync lock (legacy function)."""
    lock_key = f"sync:{user_id}:lock"
    redis_client.delete(lock_key)


def refresh_lock(user_id: UUID, ttl: int = LOCK_TTL) -> None:
    """Refresh the lock TTL (legacy function)."""
    lock_key = f"sync:{user_id}:lock"
    redis_client.expire(lock_key, ttl)


@shared_task(bind=True, max_retries=3)
def sync_chat_task(
    self, user_id: str, chat_id: str, job_id: str | None = None, limit: int | None = None
):
    """Celery task to sync messages for a chat."""
    from telethon.errors import FloodWaitError

    user_uuid = UUID(user_id)
    chat_uuid = UUID(chat_id)
    job_uuid = UUID(job_id) if job_id else None

    # Check rate budget before proceeding
    if not check_budget():
        logger.warning(f"Rate budget exhausted, deferring sync for chat {chat_id}")
        raise self.retry(exc=Exception("Rate budget exhausted"), countdown=300)

    # Acquire lock atomically at task start with heartbeat
    lock = DistributedLock(user_uuid)
    if not lock.acquire():
        logger.info(f"Sync already in progress for user {user_id}")
        return {"status": "skipped", "reason": "sync_in_progress"}

    try:
        result = asyncio.run(
            _run_sync(user_uuid, chat_uuid, limit, job_uuid)
        )
        return result
    except FloodWaitError as e:
        # Use Telegram's actual wait time + buffer for retry
        countdown = max(1, int(e.seconds * settings.flood_wait_multiplier))
        asyncio.run(
            _mark_job_state(
                job_uuid,
                SyncStatus.PENDING,
                f"rate_limited: retry_after_seconds={countdown}",
            )
        )
        logger.warning(f"FloodWait for chat {chat_id}: retrying in {countdown}s")
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
        # Exponential backoff: 60s, 180s, 540s
        backoff = 60 * (3 ** self.request.retries)
        asyncio.run(
            _mark_job_state(
                job_uuid,
                SyncStatus.FAILED,
                str(e),
            )
        )
        logger.error(f"Sync failed for chat {chat_id}: {e}, retrying in {backoff}s")
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
    finally:
        lock.release()


async def _run_sync(
    user_id: UUID, chat_id: UUID, limit: int | None, job_id: UUID | None = None
) -> dict:
    """Run the actual sync operation."""
    async with get_db_context() as db:
        # Use existing job or create new one
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

        count = await sync_messages(db, user_id, chat_id, job.id, limit)

        job.status = SyncStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.messages_processed = count
        await db.commit()

        return {
            "status": "completed",
            "job_id": str(job.id),
            "messages_synced": count,
        }


BULK_SYNC_TTL = 86400  # 24h Redis key TTL


@shared_task(bind=True, max_retries=0)
def sync_all_chats_task(self, user_id: str, job_id: str, limit_per_chat: int = 500):
    """Bulk sync: sequentially sync messages for all user chats."""
    user_uuid = UUID(user_id)
    job_uuid = UUID(job_id)

    lock = DistributedLock(user_uuid, ttl=3600)  # 1h TTL for bulk sync
    if not lock.acquire():
        logger.info(f"Bulk sync skipped — another sync in progress for user {user_id}")
        asyncio.run(_mark_job_state(job_uuid, SyncStatus.FAILED, "Another sync is already in progress"))
        return {"status": "skipped", "reason": "sync_in_progress"}

    try:
        asyncio.run(_run_bulk_sync(user_uuid, job_uuid, limit_per_chat))
        return {"status": "completed", "job_id": job_id}
    except Exception as e:
        asyncio.run(_mark_job_state(job_uuid, SyncStatus.FAILED, str(e)))
        logger.error(f"Bulk sync failed for user {user_id}: {e}")
        raise
    finally:
        lock.release()
        redis_client.delete(f"bulk:{job_id}:total")
        redis_client.delete(f"bulk:{job_id}:completed")
        redis_client.delete(f"bulk:{job_id}:current_chat")


async def _run_bulk_sync(user_id: UUID, job_id: UUID, limit_per_chat: int) -> None:
    """Run bulk sync for all user chats sequentially."""
    from app.models.chat import TelegramChat

    async with get_db_context() as db:
        # Set job IN_PROGRESS
        result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one()
        job.status = SyncStatus.IN_PROGRESS
        await db.commit()

        # Get all chats for user — unsynced first
        result = await db.execute(
            select(TelegramChat)
            .where(TelegramChat.user_id == user_id)
            .order_by(TelegramChat.last_sync_at.asc().nulls_first())
        )
        chats = result.scalars().all()
        total = len(chats)

        # Store progress counters in Redis
        redis_client.setex(f"bulk:{job_id}:total", BULK_SYNC_TTL, total)
        redis_client.setex(f"bulk:{job_id}:completed", BULK_SYNC_TTL, 0)

        effective_limit = limit_per_chat if limit_per_chat > 0 else None
        total_messages = 0

        for i, chat in enumerate(chats):
            redis_client.setex(f"bulk:{job_id}:current_chat", BULK_SYNC_TTL, chat.title[:80])

            sub_job = None
            try:
                sub_job = await create_sync_job(db, user_id, chat.id)
                sub_job.status = SyncStatus.IN_PROGRESS
                await db.commit()

                count = await sync_messages(db, user_id, chat.id, sub_job.id, effective_limit)

                sub_job.status = SyncStatus.COMPLETED
                sub_job.completed_at = datetime.now(UTC)
                sub_job.messages_processed = count
                await db.commit()

                total_messages += count
                logger.info(f"Bulk sync: chat {i+1}/{total} '{chat.title[:40]}': {count} messages")

            except Exception as e:
                logger.error(f"Bulk sync: failed chat {chat.id} ({chat.title[:40]}): {e}")
                if sub_job is not None:
                    try:
                        sub_job.status = SyncStatus.FAILED
                        sub_job.error_message = str(e)[:500]
                        await db.commit()
                    except Exception as commit_err:
                        logger.error(f"Bulk sync: failed to mark sub-job for chat {chat.id}: {commit_err}")

            finally:
                redis_client.setex(f"bulk:{job_id}:completed", BULK_SYNC_TTL, i + 1)

            # Update parent job message count
            job.messages_processed = total_messages
            await db.commit()

        # Complete parent job
        job.status = SyncStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.messages_processed = total_messages
        await db.commit()


async def _mark_job_state(
    job_id: UUID | None,
    status: SyncStatus,
    error_message: str | None = None,
) -> None:
    """Update sync job status in a standalone transaction."""
    if not job_id:
        return

    async with get_db_context() as db:
        result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        job.status = status
        job.error_message = error_message
        if status == SyncStatus.COMPLETED:
            job.completed_at = datetime.now(UTC)
        await db.commit()
