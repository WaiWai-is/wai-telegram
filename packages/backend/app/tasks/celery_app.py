import logging

from celery import Celery, signals

from app.core.config import get_settings
from app.core.observability import (
    build_runtime_summary,
    configure_logging,
    init_observability,
    log_event,
)

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery(
    "wai_telegram",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.sync_tasks", "app.tasks.digest_tasks", "app.tasks.agent_tasks"],
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


@signals.celeryd_init.connect
def configure_celery_worker_observability(**_kwargs):
    init_observability(
        settings,
        "wai-telegram-celery-worker",
        enable_celery_monitoring=True,
    )
    log_event(
        logger,
        logging.INFO,
        "Celery worker observability initialized",
        event_name="celery.worker.bootstrap",
        **build_runtime_summary(
            service_name="wai-telegram-celery-worker",
            settings=settings,
        ),
    )


@signals.beat_init.connect
def configure_celery_beat_observability(**_kwargs):
    init_observability(
        settings,
        "wai-telegram-celery-beat",
        enable_celery_monitoring=True,
    )
    log_event(
        logger,
        logging.INFO,
        "Celery beat observability initialized",
        event_name="celery.beat.bootstrap",
        **build_runtime_summary(
            service_name="wai-telegram-celery-beat",
            settings=settings,
        ),
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
    "run-due-agents": {
        "task": "app.tasks.agent_tasks.run_due_agents",
        "schedule": 60,  # Every minute
    },
}
