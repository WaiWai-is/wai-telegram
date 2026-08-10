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
incomplete_destination="$BACKUP_ROOT/.auth-cutover-$timestamp.incomplete"
mkdir -p "$incomplete_destination"
encrypted_dump="$incomplete_destination/database.dump.gpg"
restore_list="$incomplete_destination/database.restore-list.txt"
checksum_file="$incomplete_destination/SHA256SUMS"

cleanup() {
    rm -f -- "$encrypted_dump" "$restore_list" "$checksum_file"
    rmdir -- "$incomplete_destination" 2>/dev/null || true
}
trap cleanup EXIT

docker exec "$DATABASE_CONTAINER" pg_dump \
    --username telegram \
    --dbname telegram_ai \
    --format custom \
    --no-owner \
    --no-acl \
    | gpg --batch --yes --pinentry-mode loopback --cipher-algo AES256 --force-mdc \
    --s2k-digest-algo SHA512 --s2k-count 65011712 \
    --passphrase-file "$PASSPHRASE_FILE" \
    --symmetric --output "$encrypted_dump"

# Consume the entire authenticated stream first. pg_restore --list only needs the
# custom archive TOC and may close stdin early, so it cannot be the integrity check.
gpg --batch --yes --pinentry-mode loopback \
    --passphrase-file "$PASSPHRASE_FILE" \
    --decrypt "$encrypted_dump" >/dev/null

set +o pipefail
gpg --batch --yes --pinentry-mode loopback \
    --passphrase-file "$PASSPHRASE_FILE" \
    --decrypt "$encrypted_dump" \
    | docker exec -i "$DATABASE_CONTAINER" pg_restore --list > "$restore_list"
restore_status="${PIPESTATUS[1]}"
set -o pipefail
[ "$restore_status" -eq 0 ] || {
    echo "pg_restore could not read the encrypted backup" >&2
    exit 1
}
[ -s "$restore_list" ] || { echo "Backup verification produced no manifest" >&2; exit 1; }

(
    cd "$incomplete_destination"
    sha256sum database.dump.gpg > SHA256SUMS
    sha256sum --check SHA256SUMS
)
chmod 0600 "$encrypted_dump" "$checksum_file" "$restore_list"
mv "$incomplete_destination" "$destination"
trap - EXIT
echo "$destination"
