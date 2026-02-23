import asyncio
import logging
import threading
from uuid import UUID

import redis
from celery import shared_task

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.sync_job import SyncStatus
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
        self.ttl = ttl
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """Acquire the lock atomically."""
        acquired = bool(redis_client.set(self.lock_key, "1", nx=True, ex=self.ttl))
        if acquired:
            self._start_heartbeat()
        return acquired

    def release(self) -> None:
        """Release the lock and stop heartbeat."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        redis_client.delete(self.lock_key)

    def refresh(self) -> None:
        """Refresh the lock TTL."""
        redis_client.expire(self.lock_key, self.ttl)

    def _start_heartbeat(self) -> None:
        """Start background thread to refresh lock TTL."""
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Periodically refresh the lock TTL."""
        while not self._stop_heartbeat.wait(timeout=LOCK_REFRESH_INTERVAL):
            try:
                self.refresh()
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
        # Run async sync in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _run_sync(user_uuid, chat_uuid, limit, job_uuid)
            )
            return result
        finally:
            loop.close()
    except FloodWaitError as e:
        # Use Telegram's actual wait time + buffer for retry
        countdown = int(e.seconds * settings.flood_wait_multiplier)
        logger.warning(f"FloodWait for chat {chat_id}: retrying in {countdown}s")
        raise self.retry(exc=e, countdown=countdown)
    except Exception as e:
        # Exponential backoff: 60s, 180s, 540s
        backoff = 60 * (3 ** self.request.retries)
        logger.error(f"Sync failed for chat {chat_id}: {e}, retrying in {backoff}s")
        raise self.retry(exc=e, countdown=backoff)
    finally:
        lock.release()


async def _run_sync(
    user_id: UUID, chat_id: UUID, limit: int | None, job_id: UUID | None = None
) -> dict:
    """Run the actual sync operation."""
    async with get_db_context() as db:
        # Use existing job or create new one
        if job_id:
            from sqlalchemy import select
            from app.models.sync_job import SyncJob

            result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                raise ValueError(f"Sync job {job_id} not found")
        else:
            job = await create_sync_job(db, user_id, chat_id)
        job.status = SyncStatus.IN_PROGRESS
        await db.commit()

        try:
            count = await sync_messages(db, user_id, chat_id, job.id, limit)
            return {
                "status": "completed",
                "job_id": str(job.id),
                "messages_synced": count,
            }
        except Exception as e:
            job.status = SyncStatus.FAILED
            job.error_message = str(e)
            await db.commit()
            raise
