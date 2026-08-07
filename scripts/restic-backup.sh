#!/bin/bash
set -euo pipefail

readonly RESTIC_ENV_FILE="/etc/wai-telegram/restic.env"
readonly MEDIA_ROOT="/srv/wai-telegram-media"
readonly CUTOVER_BACKUP_ROOT="/opt/wai-telegram-backups"
readonly DATABASE_CONTAINER="wai-telegram-db"
readonly DATABASE_USER="telegram"
readonly DATABASE_NAME="telegram_ai"

if [ ! -r "$RESTIC_ENV_FILE" ]; then
    echo "Missing $RESTIC_ENV_FILE" >&2
    exit 1
fi
set -a
source "$RESTIC_ENV_FILE"
set +a
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"

mountpoint -q "$MEDIA_ROOT"
backup_work=$(mktemp -d /tmp/wai-telegram-backup.XXXXXX)
cleanup() {
    case "$backup_work" in
        /tmp/wai-telegram-backup.*) rm -rf -- "$backup_work" ;;
        *) echo "Refusing to remove unexpected backup path" >&2 ;;
    esac
}
trap cleanup EXIT

database_dump="$backup_work/telegram-ai.dump"
docker exec "$DATABASE_CONTAINER" pg_dump \
    --username "$DATABASE_USER" \
    --dbname "$DATABASE_NAME" \
    --format custom \
    --no-owner \
    --no-acl > "$database_dump"
docker exec -i "$DATABASE_CONTAINER" pg_restore --list < "$database_dump" \
    >/dev/null
printf 'wai-telegram restore canary\n' > "$backup_work/restore-canary.txt"

mkdir -p "$CUTOVER_BACKUP_ROOT"
restic --retry-lock 30m backup \
    --tag wai-telegram \
    --host "$(hostname)" \
    "$MEDIA_ROOT" "$backup_work" "$CUTOVER_BACKUP_ROOT"
restic --retry-lock 30m forget \
    --tag wai-telegram \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --prune
