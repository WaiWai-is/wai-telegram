from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "wai_telegram",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.sync_tasks", "app.tasks.digest_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Beat schedule
celery_app.conf.beat_schedule = {
    "generate-daily-digests": {
        "task": "app.tasks.digest_tasks.generate_all_digests",
        "schedule": 3600,  # Every hour — per-user hour matching inside task
    },
    "listener-health-check": {
        "task": "app.tasks.sync_tasks.listener_health_check",
        "schedule": 300,  # Every 5 minutes
    },
    "reap-stale-sync-jobs": {
        "task": "app.tasks.sync_tasks.reap_stale_sync_jobs",
        "schedule": 120,  # Every 2 minutes
    },
}
