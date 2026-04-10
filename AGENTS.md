# Wai Telegram

Monorepo for the Telegram product: backend, frontend, and MCP server.

## Structure

- `packages/backend/` — FastAPI app, Celery tasks, realtime listener, Alembic migrations
- `packages/frontend/` — Next.js frontend (Vitest)
- `packages/mcp-server/` — MCP server
- Infra: `systemd/`, `nginx/`, `docker-compose.yml`, `deploy.sh`, `rollback.sh`

## Commands

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
npm run dev / npm run lint / npm run test / npm run test:coverage
```

## Production

- Domain: https://telegram.waiwai.is
- Env: `/opt/wai-telegram/.env.production`
- systemd: `wai-backend`, `wai-frontend`, `wai-celery`, `wai-celery-beat`, `wai-listener`, `wai-mcp-sse`
- Docker: `wai-telegram-db`, `wai-telegram-redis`
- Health: `/health/live`, `/health/ready`

## Fast Triage

1. `systemctl is-active wai-backend wai-frontend wai-celery wai-celery-beat wai-listener wai-mcp-sse`
2. `curl -sf http://127.0.0.1:8000/health/live && curl -sf http://127.0.0.1:8000/health/ready`
3. `curl -sf https://telegram.waiwai.is/health/ready`
4. `journalctl -u wai-backend -u wai-celery -n 200 --no-pager`

## Deploy

1. Timestamped backup in `/opt/wai-telegram-backups`
2. Confirm `.env.production` includes `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY`, `NEXT_PUBLIC_API_URL`, `SENTRY_DSN`
3. `systemctl restart wai-backend wai-frontend wai-celery wai-celery-beat wai-listener wai-mcp-sse`
4. Verify health checks + `celery inspect ping`

## Rollback

If backend not ready after one restart cycle: stop services → restore from `/opt/wai-telegram-backups` → restore systemd/nginx if changed → start services → triage.

## Observability

- Sentry: `waiwai-diy / wai-telegram-backend`
- PII must stay out of logs/Sentry: no passwords, tokens, emails, phones, Telegram session strings, request bodies
