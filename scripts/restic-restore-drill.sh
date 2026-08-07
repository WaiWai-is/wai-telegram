#!/bin/bash
set -euo pipefail

readonly RESTIC_ENV_FILE="/etc/wai-telegram/restic.env"
readonly DATABASE_CONTAINER="wai-telegram-db"
readonly DATABASE_USER="telegram"
[ -r "$RESTIC_ENV_FILE" ] || { echo "Missing $RESTIC_ENV_FILE" >&2; exit 1; }
set -a
source "$RESTIC_ENV_FILE"
set +a
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"

restore_root=$(mktemp -d /tmp/wai-telegram-restore-drill.XXXXXX)
drill_database="wai_restore_drill_$(date -u +%Y%m%d%H%M%S)_$$"
cleanup() {
    case "$drill_database" in
        wai_restore_drill_*)
            docker exec "$DATABASE_CONTAINER" dropdb \
                --username "$DATABASE_USER" --if-exists --force "$drill_database" \
                >/dev/null 2>&1 || true
            ;;
        *) echo "Refusing to drop unexpected restore database" >&2 ;;
    esac
    case "$restore_root" in
        /tmp/wai-telegram-restore-drill.*) rm -rf -- "$restore_root" ;;
        *) echo "Refusing to remove unexpected restore path" >&2 ;;
    esac
}
trap cleanup EXIT

restic --retry-lock 30m restore latest \
    --tag wai-telegram \
    --target "$restore_root" \
    --include '/tmp/wai-telegram-backup.*/telegram-ai.dump' \
    --include '/tmp/wai-telegram-backup.*/restore-canary.txt'

database_dump=$(find "$restore_root" -type f -name telegram-ai.dump -print -quit)
canary=$(find "$restore_root" -type f -name restore-canary.txt -print -quit)
test -n "$database_dump"
test -n "$canary"
docker exec -i "$DATABASE_CONTAINER" pg_restore --list < "$database_dump" \
    >/dev/null
grep -Fx 'wai-telegram restore canary' "$canary" >/dev/null

docker exec "$DATABASE_CONTAINER" createdb \
    --username "$DATABASE_USER" --template template0 "$drill_database"
docker exec -i "$DATABASE_CONTAINER" pg_restore \
    --username "$DATABASE_USER" \
    --dbname "$drill_database" \
    --no-owner \
    --no-acl < "$database_dump"
table_count=$(docker exec "$DATABASE_CONTAINER" psql \
    --username "$DATABASE_USER" \
    --dbname "$drill_database" \
    --tuples-only \
    --no-align \
    --command "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
[ "$table_count" -gt 0 ] || { echo "Restored database has no public tables" >&2; exit 1; }
