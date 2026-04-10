# CLAUDE.md

## Repo
Monorepo for the Telegram product, frontend, backend, and MCP server.

- backend: `packages/backend`
- frontend: `packages/frontend`
- MCP server: `packages/mcp-server`
- infra: `systemd/`, `nginx/`, `docker-compose.yml`, `docker-compose.prod.yml`, `deploy.sh`, `rollback.sh`

Use `AGENTS.md` for production incident handling and rollback steps.

## Backend
- app entrypoint: `packages/backend/app/main.py`
- Celery app: `packages/backend/app/tasks/celery_app.py`
- realtime listener: `packages/backend/app/listener/run.py`
- settings: `packages/backend/app/core/config.py`
- migrations: `packages/backend/alembic/`
- tests: `packages/backend/tests/`

## Frontend
- app code: `packages/frontend/src`
- tests: `packages/frontend` via Vitest

## Local Commands
```bash
# Backend
cd packages/backend
uv run uvicorn app.main:app --reload --port 8000
uv run alembic upgrade head
uv run pytest tests -q
uv run pytest tests --cov=app --cov-report=term-missing:skip-covered -q
uv run ruff check app tests

# Frontend
cd packages/frontend
npm run dev
npm run lint
npm run test
npm run test:coverage
```

## Production Runtime
- domain: `https://telegram.waiwai.is`
- env file: `/opt/wai-telegram/.env.production`
- systemd units: `wai-backend`, `wai-frontend`, `wai-celery`, `wai-celery-beat`, `wai-listener`, `wai-mcp-sse`
- backend health: `/health/live`, `/health/ready`
- local infra containers: `wai-telegram-db`, `wai-telegram-redis`

## Observability
- Sentry project: `waiwai-diy / wai-telegram-backend`
- config lives in `packages/backend/app/core/observability.py`
- initialized from backend startup, Celery worker/beat startup, and listener startup
- env: `SENTRY_DSN`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`, `SENTRY_ENABLE_LOGS`, `SENTRY_DEBUG`
- PII must stay out of logs and Sentry events; do not log raw passwords, tokens, emails, phones, request bodies, Telegram IDs, or session strings

## Workflow
- Commit after each completed functional block.
- Prefer failing tests first, then the minimal implementation, then refactor.
- Keep this file small. If a line becomes stale, fix it or delete it.
