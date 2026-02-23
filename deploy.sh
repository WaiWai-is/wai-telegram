#!/bin/bash
# WAI Telegram AI - Deployment Script
# Target: root@178.62.255.184
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
SERVER="root@178.62.255.184"
DEPLOY_DIR="/opt/wai-telegram"
DOMAIN="telegram.waiwai.is"

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
    ./ "${SERVER}:${DEPLOY_DIR}/"

# Step 2: Run remote setup commands
log "Running server setup..."
ssh "${SERVER}" << 'REMOTE_SCRIPT'
set -e

cd /opt/wai-telegram
export PATH="$HOME/.local/bin:$PATH"

# Install system dependencies if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    apt update && apt install -y docker.io docker-compose
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

# Start PostgreSQL and Redis
echo "Starting database services..."
set -a && source .env.production && set +a
docker-compose -f docker-compose.prod.yml up -d

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
sleep 10

# Run database migrations
echo "Running database migrations..."
cd packages/backend
uv sync
uv run alembic upgrade head
cd ../..

# Build frontend
echo "Building frontend..."
cd packages/frontend
npm ci
npm run build
cd ../..

# Install systemd services
echo "Installing systemd services..."
cp systemd/wai-backend.service /etc/systemd/system/
cp systemd/wai-celery.service /etc/systemd/system/
cp systemd/wai-celery-beat.service /etc/systemd/system/
cp systemd/wai-frontend.service /etc/systemd/system/

systemctl daemon-reload

# Start services
echo "Starting services..."
systemctl enable wai-backend wai-celery wai-celery-beat wai-frontend
systemctl restart wai-backend
sleep 5
systemctl restart wai-celery wai-celery-beat wai-frontend

# Setup Nginx
echo "Configuring Nginx..."
cp nginx/telegram-ai.conf /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/telegram-ai.conf /etc/nginx/sites-enabled/

if nginx -t 2>/dev/null; then
    systemctl reload nginx
else
    echo "Nginx config test failed - SSL certificate may be needed"
fi

echo "Deployment complete!"
REMOTE_SCRIPT

log "Deployment finished!"
echo ""
echo "Verify: curl https://${DOMAIN}/health"
echo "Logs:   ssh ${SERVER} journalctl -u wai-backend -f"
echo ""
