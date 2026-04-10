# AGENTS.md

## Scope
Production runbook for `wai-telegram`. Keep this file short; put repo structure and dev context in `CLAUDE.md`.

## Runtime
- systemd: `wai-backend`, `wai-frontend`, `wai-celery`, `wai-celery-beat`, `wai-listener`, `wai-mcp-sse`
- docker: `wai-telegram-db`, `wai-telegram-redis`
- backend health: `http://127.0.0.1:8000/health/live`, `http://127.0.0.1:8000/health/ready`
- edge health: `https://telegram.waiwai.is/health/ready`
- production env: `/opt/wai-telegram/.env.production`

## Fast Triage
1. `systemctl is-active wai-backend wai-frontend wai-celery wai-celery-beat wai-listener wai-mcp-sse`
2. `curl -sf http://127.0.0.1:8000/health/live && curl -sf http://127.0.0.1:8000/health/ready`
3. `curl -sf https://telegram.waiwai.is/health/ready`
4. `journalctl -u wai-backend -u wai-frontend -u wai-celery -u wai-celery-beat -u wai-listener -u wai-mcp-sse -n 200 --no-pager`
5. `docker ps --format '{{.Names}} {{.Status}}'`
6. `cd /opt/wai-telegram/packages/backend && /opt/wai-telegram/.venv/bin/celery -A app.tasks.celery_app:celery_app inspect ping`

## Observability
- Sentry project: `waiwai-diy / wai-telegram-backend`
- required env: `SENTRY_DSN`, `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`, `SENTRY_ENABLE_LOGS`, `SENTRY_DEBUG`
- Sentry is initialized in backend app startup, Celery worker/beat startup, and realtime listener startup
- never log or attach raw passwords, tokens, cookies, email addresses, phone numbers, Telegram session strings, request bodies, or full webhook payloads

## Deploy
1. Create a timestamped backup in `/opt/wai-telegram-backups` and update `/opt/wai-telegram-backup`.
2. Confirm `.env.production` and frontend build env include at least `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY`, `NEXT_PUBLIC_API_URL`, and `SENTRY_DSN`.
3. Restart: `systemctl restart wai-backend wai-frontend wai-celery wai-celery-beat wai-listener wai-mcp-sse`
4. Verify the health checks above and `celery inspect ping`.

## Rollback
Rollback after one restart cycle if backend is still not ready, any worker/listener service is inactive, core auth/sync endpoints still return 5xx, or frontend remains unavailable.

1. Stop app services.
2. Restore `/opt/wai-telegram-backup` or the newest verified backup from `/opt/wai-telegram-backups`.
3. Restore systemd and nginx config if they changed.
4. Start services and rerun the triage checks.

## Workflow
- Commit after each completed functional block.
- After pushing to `main`, verify that the latest GitHub Actions `CI / Deploy` run completed with `success` before treating the deploy as done.
- Check with: `gh run list -R WaiWai-is/wai-telegram --workflow 'CI / Deploy' --limit 1` and, if needed, `gh run view <run-id> -R WaiWai-is/wai-telegram`
- Prefer tests first, then implementation, then refactor.
- Backend: `cd packages/backend && uv run pytest tests -q`
- Frontend: `cd packages/frontend && npm run test`
