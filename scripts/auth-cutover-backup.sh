#!/bin/bash
set -euo pipefail
umask 077

readonly BACKUP_ROOT="/opt/wai-telegram-backups"
readonly DATABASE_CONTAINER="wai-telegram-db"
readonly PASSPHRASE_FILE="/etc/wai-telegram/auth-backup-passphrase"

[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
[ -r "$PASSPHRASE_FILE" ] || { echo "Missing $PASSPHRASE_FILE" >&2; exit 1; }
[ -s "$PASSPHRASE_FILE" ] || { echo "Empty $PASSPHRASE_FILE" >&2; exit 1; }
[ "$(stat -c '%u:%a' "$PASSPHRASE_FILE")" = "0:600" ] || {
    echo "$PASSPHRASE_FILE must be owned by root with mode 0600" >&2
    exit 1
}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="$BACKUP_ROOT/auth-cutover-$timestamp"
mkdir -p "$destination"
work_dir=$(mktemp -d /tmp/wai-auth-cutover.XXXXXX)
cleanup() {
    case "$work_dir" in
        /tmp/wai-auth-cutover.*) rm -rf -- "$work_dir" ;;
        *) echo "Refusing to remove unexpected backup path" >&2 ;;
    esac
}
trap cleanup EXIT

plain_dump="$work_dir/database.dump"
verification_dump="$work_dir/database-verify.dump"
encrypted_dump="$destination/database.dump.gpg"

docker exec "$DATABASE_CONTAINER" pg_dump \
    --username telegram \
    --dbname telegram_ai \
    --format custom \
    --no-owner \
    --no-acl > "$plain_dump"
docker exec -i "$DATABASE_CONTAINER" pg_restore --list \
    < "$plain_dump" > "$destination/database.restore-list.txt"
gpg --batch --yes --pinentry-mode loopback --cipher-algo AES256 --force-mdc \
    --s2k-digest-algo SHA512 --s2k-count 65011712 \
    --passphrase-file "$PASSPHRASE_FILE" \
    --symmetric --output "$encrypted_dump" "$plain_dump"
gpg --batch --yes --pinentry-mode loopback \
    --passphrase-file "$PASSPHRASE_FILE" \
    --decrypt --output "$verification_dump" "$encrypted_dump"
docker exec -i "$DATABASE_CONTAINER" pg_restore --list < "$verification_dump" \
    >/dev/null
sha256sum "$encrypted_dump" > "$destination/SHA256SUMS"
chmod 0600 "$encrypted_dump" "$destination/SHA256SUMS" \
    "$destination/database.restore-list.txt"
echo "$destination"
