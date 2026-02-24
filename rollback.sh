#!/bin/bash
# WAI Telegram AI - Rollback Script
# Restores the previous deployment from backup

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

SERVER="root@178.62.255.184"
DEPLOY_DIR="/opt/wai-telegram"
BACKUP_DIR="/opt/wai-telegram-backup"
DOMAIN="telegram.waiwai.is"

log "Starting rollback on ${SERVER}..."

ssh "${SERVER}" << 'REMOTE_SCRIPT'
set -e

DEPLOY_DIR="/opt/wai-telegram"
BACKUP_DIR="/opt/wai-telegram-backup"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: No backup found at $BACKUP_DIR"
    exit 1
fi

echo "Stopping services..."
systemctl stop wai-backend wai-celery wai-celery-beat wai-frontend || true

echo "Restoring from backup..."
# Preserve .env.production (not in backup)
rm -rf "${DEPLOY_DIR}.failed"
mv "$DEPLOY_DIR" "${DEPLOY_DIR}.failed"
cp -a "$BACKUP_DIR" "$DEPLOY_DIR"

# Copy env file back if it was preserved in failed dir
if [ -f "${DEPLOY_DIR}.failed/.env.production" ]; then
    cp "${DEPLOY_DIR}.failed/.env.production" "$DEPLOY_DIR/.env.production"
fi

# Fix ownership
chown -R wai:wai "$DEPLOY_DIR"

echo "Reinstalling systemd services from backup..."
cp "$DEPLOY_DIR/systemd/wai-backend.service" /etc/systemd/system/
cp "$DEPLOY_DIR/systemd/wai-celery.service" /etc/systemd/system/
cp "$DEPLOY_DIR/systemd/wai-celery-beat.service" /etc/systemd/system/
cp "$DEPLOY_DIR/systemd/wai-frontend.service" /etc/systemd/system/
systemctl daemon-reload

echo "Restarting services..."
systemctl start wai-backend
sleep 3
systemctl start wai-celery wai-celery-beat wai-frontend

# Restore nginx config
cp "$DEPLOY_DIR/nginx/telegram-ai.conf" /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/telegram-ai.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "Rollback complete!"
REMOTE_SCRIPT

log "Rollback finished!"
echo ""
echo "Verify: curl https://${DOMAIN}/health"
echo "Logs:   ssh ${SERVER} journalctl -u wai-backend -f"
echo ""
