# WAI Telegram AI Message Manager

## Project Overview
Telegram message syncing and AI-powered search/digest platform. Syncs Telegram chats to PostgreSQL, generates embeddings for semantic search, and provides AI digests via MCP server.

## Architecture
- **Backend**: FastAPI + SQLAlchemy + asyncpg (Python 3.12)
- **Frontend**: Next.js 15 + React 19 + TailwindCSS
- **Database**: PostgreSQL 16 with pgvector extension
- **Queue**: Celery + Redis
- **MCP Server**: `packages/mcp-server/` — exposes search/digest tools for Claude

## Infrastructure
- **Server**: DigitalOcean (Ubuntu 24.04, 2GB RAM) — IP and SSH configured via `DEPLOY_HOST` env var
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
- `wai-backend` — FastAPI on port 8000 (2 workers)
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

## GitHub Secrets (for Actions deploy)
- `DEPLOY_SSH_KEY` — ED25519 private key
- `DEPLOY_HOST` — Server IP
- `DEPLOY_USER` — SSH user (root)
- `DEPLOY_KNOWN_HOSTS` — Server host key fingerprint
