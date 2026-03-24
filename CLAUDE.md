# WAI Telegram — AI Partner in Telegram

## Project Overview
**Wai** (@waicomputer_bot) — a personal AI partner in Telegram. Syncs messages, transcribes voice, tracks commitments, searches by meaning, analyzes photos, and responds in 13 languages. Built overnight hackathon (March 24-25, 2026) — 502 tests, 19 agent modules.

## Architecture
- **Backend**: FastAPI + SQLAlchemy + asyncpg (Python 3.12)
- **Frontend**: Next.js 15 + React 19 + TailwindCSS
- **Database**: PostgreSQL 16 with pgvector extension
- **Queue**: Celery + Redis
- **MCP Server**: `packages/mcp-server/` — exposes search/digest tools for Claude

## Infrastructure
- **Server**: Hetzner (Ubuntu 24.04, 4GB RAM) — IP and SSH configured via `DEPLOY_HOST` env var
- **Domain**: `telegram.waiwai.is`
- **SSL**: Let's Encrypt (auto-renew via certbot)
- **Deploy**: GitHub Actions → SSH → rsync + restart services (auto on push to main)
- **GitHub**: `https://github.com/WaiWai-is/wai-telegram`

## Server Access
```bash
# SSH to server
ssh $DEPLOY_USER@$DEPLOY_HOST

# Check service status
ssh $DEPLOY_USER@$DEPLOY_HOST systemctl status wai-backend wai-frontend wai-celery wai-celery-beat

# View logs
ssh $DEPLOY_USER@$DEPLOY_HOST journalctl -u wai-backend -f
ssh $DEPLOY_USER@$DEPLOY_HOST journalctl -u wai-celery -f

# Docker containers (PostgreSQL + Redis)
ssh $DEPLOY_USER@$DEPLOY_HOST docker ps

# Restart all services
ssh $DEPLOY_USER@$DEPLOY_HOST 'systemctl restart wai-backend wai-celery wai-celery-beat wai-frontend'
```

## Key Paths
```
packages/backend/          # FastAPI backend
packages/backend/app/      # App code (api/, core/, services/, tasks/)
packages/backend/alembic/  # DB migrations
packages/frontend/         # Next.js frontend
packages/mcp-server/       # MCP server for Claude integration
systemd/                   # Systemd service files
nginx/                     # Nginx config
docker-compose.prod.yml    # PostgreSQL + Redis containers
deploy.sh                  # Manual deploy script
.github/workflows/         # GitHub Actions CI/CD
```

## Server Services
- `wai-backend` — FastAPI on port 8000 (1 worker)
- `wai-frontend` — Next.js on port 3000
- `wai-celery` — Celery worker (1 concurrency)
- `wai-celery-beat` — Celery scheduler
- PostgreSQL via Docker on 127.0.0.1:5432
- Redis via Docker on 127.0.0.1:6379

## Development Commands
```bash
# Backend
cd packages/backend && uv run uvicorn app.main:app --reload --port 8000

# Frontend
cd packages/frontend && npm run dev

# Migrations
cd packages/backend && uv run alembic upgrade head

# Deploy (manual)
./deploy.sh

# Server logs
ssh $DEPLOY_USER@$DEPLOY_HOST journalctl -u wai-backend -f
```

## Agent System (`packages/backend/app/services/agent/`)
The core AI agent with 19 modules:
- `router.py` — Intent classification (30+ patterns EN/RU + Haiku LLM fallback)
- `soul.py` — 5-layer system prompt with 11 native language instructions
- `loop.py` — Agent execution loop with 7 tools + Claude tool_use
- `metrics.py` — Counters + histograms at /metrics endpoint
- `commitments.py` — Bi-directional promise tracking (EN+RU) + DB persistence
- `entities.py` — Extract people, amounts, dates, decisions from text
- `language.py` — 13-language detection without LLM calls
- `voice_summary.py` — Voice → transcript + AI summary + entities + commitments
- `briefing.py` — Proactive morning briefing with [no_message] pattern
- `inline.py` — Viral inline search in any Telegram chat
- `forward_processor.py` — Forward anything → parse + remember (second brain)
- `user_resolver.py` — Telegram user ID → internal UUID + auto-create
- `status.py` — User stats + system health dashboard
- `typing.py` — "Wai is typing..." indicator for Claude response times
- `conversation.py` — Session memory (last 20 messages per user)
- `media_processor.py` — Photo description (Claude Vision) + document text extraction
- `rate_limit.py` — Per-user sliding window (30/min, 200/hr)
- `bot_webhook.py` — Telegram webhook with 12 commands + voice/photo/doc/forward

## Bot Commands
`/start` `/help` `/search` `/summarize` `/web` `/digest` `/commitments` `/entities` `/briefing` `/status` `/clear` `/feedback` + voice + photo + document + forward + inline

## Testing
```bash
cd packages/backend
PYTHONPATH=. python -m pytest tests/ -q         # 502 tests
PYTHONPATH=. python -m pytest tests/ --cov=app   # 61% coverage
```

## GitHub Secrets (for Actions deploy)
- `DEPLOY_SSH_KEY` — ED25519 private key
- `DEPLOY_HOST` — Server IP (89.167.125.46)
- `DEPLOY_USER` — SSH user (root)
- `DEPLOY_KNOWN_HOSTS` — Server host key fingerprint

## Bot Configuration
- Token: stored in systemd override `/etc/systemd/system/wai-backend.service.d/env.conf`
- Also in `/opt/wai-telegram/.env` and `.env.production`
- Webhook: `https://telegram.waiwai.is/api/v1/bot/webhook/{secret}`
