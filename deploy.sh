#!/bin/bash
# WAI Telegram AI - Deployment Script
# Target: root@89.167.125.46
# Domain: telegram.waiwai.is

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Configuration
SERVER="root@89.167.125.46"
DEPLOY_DIR="/opt/wai-telegram"
DOMAIN="telegram.waiwai.is"
BACKUP_ROOT="/opt/wai-telegram-backups"

# Check if .env.production exists
if [ ! -f ".env.production" ]; then
    error ".env.production not found. Copy .env.production.example and fill in values."
fi

log "Starting deployment to ${SERVER}..."

# Step 1: Sync code to server
log "Syncing code to server..."
rsync -avz --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.next' \
    --exclude '*.pyc' \
    --exclude 'code/' \
    --exclude '.DS_Store' \
    --exclude '.env.production' \
    --exclude '.env' \
    ./ "${SERVER}:${DEPLOY_DIR}/"

# Step 2: Run remote setup commands
log "Running server setup..."
ssh "${SERVER}" << 'REMOTE_SCRIPT'
set -e

cd /opt/wai-telegram
export PATH="$HOME/.local/bin:$PATH"
BACKUP_ROOT="/opt/wai-telegram-backups"

# Install system dependencies if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker && systemctl start docker
fi

if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v node &> /dev/null; then
    echo "Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt install -y nodejs
fi

if ! command -v nginx &> /dev/null; then
    echo "Installing Nginx..."
    apt install -y nginx certbot python3-certbot-nginx
fi

# Create wai service user if not present
if ! id wai &>/dev/null; then
    echo "Creating wai service user..."
    useradd --system --home-dir /home/wai --create-home --shell /bin/bash wai
    su - wai -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# Backup current deployment (versioned and atomic)
if [ -d /opt/wai-telegram/packages ]; then
    mkdir -p "${BACKUP_ROOT}"
    TS=$(date +%Y%m%d%H%M%S)
    TMP_BACKUP="${BACKUP_ROOT}/${TS}.tmp"
    FINAL_BACKUP="${BACKUP_ROOT}/${TS}"
    cp -a /opt/wai-telegram "${TMP_BACKUP}"
    mv "${TMP_BACKUP}" "${FINAL_BACKUP}"
    ln -sfn "${FINAL_BACKUP}" /opt/wai-telegram-backup
    echo "Backup created at ${FINAL_BACKUP}"
    # Keep only the 5 most recent backups
    ls -dt /opt/wai-telegram-backups/*/ 2>/dev/null | tail -n +6 | xargs rm -rf
fi

# Fix ownership
chown -R wai:wai /opt/wai-telegram

# Start PostgreSQL and Redis
echo "Starting database services..."
set -a && source .env.production && set +a
docker compose -f docker-compose.prod.yml up -d

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
sleep 10

# Run database migrations
echo "Running database migrations..."
cd packages/backend
su - wai -c 'cd /opt/wai-telegram/packages/backend && /home/wai/.local/bin/uv sync'
su - wai -c 'cd /opt/wai-telegram/packages/mcp-server && /home/wai/.local/bin/uv sync'
su - wai -c 'cd /opt/wai-telegram/packages/backend && set -a && source /opt/wai-telegram/.env.production && set +a && /home/wai/.local/bin/uv run alembic upgrade head'
cd ../..

# Build frontend
echo "Building frontend..."
su - wai -c 'cd /opt/wai-telegram/packages/frontend && set -a && source /opt/wai-telegram/.env.production && set +a && if [ -z "${NEXT_SERVER_ACTIONS_ENCRYPTION_KEY:-}" ]; then echo "NEXT_SERVER_ACTIONS_ENCRYPTION_KEY is required for production builds"; exit 1; fi && npm ci --prefer-offline && npm run build'

# Install systemd services
echo "Installing systemd services..."
cp systemd/wai-backend.service /etc/systemd/system/
cp systemd/wai-celery.service /etc/systemd/system/
cp systemd/wai-celery-beat.service /etc/systemd/system/
cp systemd/wai-frontend.service /etc/systemd/system/
cp systemd/wai-listener.service /etc/systemd/system/
cp systemd/wai-mcp-sse.service /etc/systemd/system/

systemctl daemon-reload

# Start services
echo "Starting services..."
systemctl enable wai-backend wai-celery wai-celery-beat wai-frontend wai-listener wai-mcp-sse
systemctl restart wai-backend
sleep 5
systemctl restart wai-celery wai-celery-beat wai-frontend wai-listener wai-mcp-sse

# Setup Nginx
echo "Configuring Nginx..."
cp nginx/telegram-ai.conf /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/telegram-ai.conf /etc/nginx/sites-enabled/

if nginx -t 2>/dev/null; then
    systemctl reload nginx
else
    echo "Nginx config test failed - SSL certificate may be needed"
fi

# Service and endpoint verification
echo "Verifying service health..."
systemctl is-active --quiet wai-backend wai-celery wai-celery-beat wai-frontend wai-listener wai-mcp-sse
curl -sf --max-time 10 http://127.0.0.1:8000/health/live > /dev/null
curl -sf --max-time 10 http://127.0.0.1:8000/health/ready > /dev/null
curl -sf --max-time 10 https://telegram.waiwai.is/health/ready > /dev/null

echo "Deployment complete!"
REMOTE_SCRIPT

log "Deployment finished!"
echo ""
echo "Verify: curl https://${DOMAIN}/health/ready"
echo "Logs:   ssh ${SERVER} journalctl -u wai-backend -f"
echo ""
