# AGENTS.md

## Purpose
Operational playbook for agents working on `wai-telegram` in production and incident conditions.

## Critical Services
- `wai-backend` (FastAPI, port `8000`)
- `wai-celery` (worker)
- `wai-celery-beat` (scheduler)
- `wai-frontend` (Next.js, port `3000`)
- Docker containers: `wai-telegram-db`, `wai-telegram-redis`

## Incident Triage Order
1. Confirm service state:
   `systemctl is-active wai-backend wai-celery wai-celery-beat wai-frontend`
2. Check backend readiness:
   `curl -sf http://127.0.0.1:8000/health/live && curl -sf http://127.0.0.1:8000/health/ready`
3. Check edge readiness:
   `curl -sf https://telegram.waiwai.is/health/ready`
4. Review last errors:
   `journalctl -u wai-backend -n 200 --no-pager`
   `journalctl -u wai-celery -n 200 --no-pager`
   `journalctl -u wai-celery-beat -n 200 --no-pager`
   `journalctl -u wai-frontend -n 200 --no-pager`

## Known Error Signatures
- SlowAPI startup crash:
  `No "request" or "websocket" argument on function`
- Next.js action mismatch:
  `Failed to find Server Action "x"`
- Systemd directive misplacement:
  `Unknown key name 'StartLimitIntervalSec' in section 'Service'`
- Runtime package mutation permissions:
  `failed to write to file ... uv.lock: Permission denied`

## Deployment Safety Checklist
1. Build-time env includes:
   - `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY`
   - `NEXT_PUBLIC_API_URL`
2. Backup strategy:
   - Create timestamped backup in `/opt/wai-telegram-backups`
   - Update symlink `/opt/wai-telegram-backup` to latest verified backup
3. Restart services:
   - `systemctl restart wai-backend wai-celery wai-celery-beat wai-frontend`
4. Verify:
   - `systemctl is-active ...`
   - `curl /health/live` and `/health/ready` locally and via domain
   - `celery inspect ping`

## Rollback Criteria
Rollback immediately when any of the following remain unresolved after one restart cycle:
- Backend not ready on `/health/ready`
- Worker or beat not active
- Persistent 5xx on auth/sync/digest endpoints
- Frontend unavailable or hard errors on core pages

## Rollback Steps
1. Stop app services.
2. Restore from `/opt/wai-telegram-backup` (or newest in `/opt/wai-telegram-backups`).
3. Restore systemd units and nginx config from backup.
4. Start services and verify readiness endpoints.

## Multi-Agent Analysis Protocol
For major incidents or broad refactors:
1. Run at least 6 analyzers in parallel:
   - sync pipeline
   - auth/session
   - digest/search
   - MCP layer
   - infra/deploy
   - frontend integration
2. Consolidate findings by severity with file references.
3. Fix critical/high issues before medium/low.

## MCP Research Protocol
For architecture or security changes in MCP:
1. Run at least 10 EXA calls.
2. Prioritize official docs and primary sources.
3. Record actionable constraints (input bounds, error handling, transport behavior).
4. Implement validation and failure-safe formatting before feature additions.

