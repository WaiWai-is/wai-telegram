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
encrypted_dump="$destination/database.dump.gpg"
plain_list="$destination/database.restore-list.txt"
decrypted_list="$destination/database.decrypted-restore-list.txt"

docker exec "$DATABASE_CONTAINER" pg_dump \
    --username telegram \
    --dbname telegram_ai \
    --format custom \
    --no-owner \
    --no-acl \
    | tee >(docker exec -i "$DATABASE_CONTAINER" pg_restore --list > "$plain_list") \
    | gpg --batch --yes --pinentry-mode loopback --cipher-algo AES256 --force-mdc \
    --s2k-digest-algo SHA512 --s2k-count 65011712 \
    --passphrase-file "$PASSPHRASE_FILE" \
    --symmetric --output "$encrypted_dump"
wait
[ -s "$plain_list" ] || { echo "Plain backup verification produced no manifest" >&2; exit 1; }
gpg --batch --yes --pinentry-mode loopback \
    --passphrase-file "$PASSPHRASE_FILE" \
    --decrypt "$encrypted_dump" \
    | docker exec -i "$DATABASE_CONTAINER" pg_restore --list > "$decrypted_list"
cmp --silent "$plain_list" "$decrypted_list" || {
    echo "Plain and decrypted backup manifests differ" >&2
    exit 1
}
sha256sum "$encrypted_dump" > "$destination/SHA256SUMS"
chmod 0600 "$encrypted_dump" "$destination/SHA256SUMS" \
    "$plain_list" "$decrypted_list"
echo "$destination"
