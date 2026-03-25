import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select, text

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.limiter import limiter
from app.models.sync_job import SyncJob, SyncStatus

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize Sentry for error tracking
if settings.sentry_dsn and sentry_sdk:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        environment=settings.environment,
        release="wai-telegram@0.2.0",
        send_default_pii=False,
    )
    logger.info("Sentry initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: mark orphaned IN_PROGRESS jobs as FAILED
    try:
        import redis as redis_lib

        redis_client = redis_lib.from_url(settings.redis_url)
        updated_jobs = 0
        async with async_session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(hours=2)
            result = await db.execute(
                select(SyncJob).where(
                    SyncJob.status == SyncStatus.IN_PROGRESS,
                    SyncJob.updated_at < cutoff,
                )
            )
            jobs = result.scalars().all()
            for job in jobs:
                heartbeat_key = (
                    f"bulk:{job.id}:heartbeat"
                    if job.chat_id is None
                    else f"sync:{job.id}:heartbeat"
                )
                if redis_client.get(heartbeat_key):
                    continue
                job.status = SyncStatus.FAILED
                job.error_message = (
                    "Marked as failed: job was orphaned (worker crash or timeout)"
                )
                updated_jobs += 1
            if updated_jobs > 0:
                logger.warning(f"Marked {updated_jobs} orphaned sync jobs as FAILED")
                await db.commit()
        redis_client.close()
    except Exception as e:
        logger.error(f"Failed to clean up orphaned jobs on startup: {e}")

    yield

    # Shutdown: disconnect temporary auth clients
    try:
        from app.api.v1.telegram import _auth_clients

        for key, (client, _) in list(_auth_clients.items()):
            try:
                await client.disconnect()
            except Exception:
                pass
        _auth_clients.clear()
    except Exception:
        pass


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — restrict origins based on environment
if settings.environment == "production":
    cors_origins = ["https://telegram.waiwai.is"]
else:
    cors_origins = [
        "http://localhost:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3010",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(api_router, prefix="/api/v1")


async def _check_dependencies() -> None:
    """Validate dependencies required for handling requests."""
    import redis as redis_lib

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    r = redis_lib.from_url(settings.redis_url)
    r.ping()
    r.close()


@app.api_route("/health/live", methods=["GET", "HEAD"])
async def liveness_check():
    """Liveness probe: process is up."""
    return {"status": "alive"}


@app.api_route("/health/ready", methods=["GET", "HEAD"])
async def readiness_check():
    """Readiness probe: dependencies are reachable."""
    await _check_dependencies()
    return {"status": "ready"}


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    """Backward-compatible health endpoint."""
    await _check_dependencies()
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    """Agent metrics endpoint — usage, performance, costs."""
    from app.services.agent.metrics import get_metrics

    return get_metrics()
