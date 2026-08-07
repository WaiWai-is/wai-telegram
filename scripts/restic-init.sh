#!/bin/bash
set -euo pipefail

readonly RESTIC_ENV_FILE="/etc/wai-telegram/restic.env"
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
[ -r "$RESTIC_ENV_FILE" ] || { echo "Missing $RESTIC_ENV_FILE" >&2; exit 1; }
set -a
source "$RESTIC_ENV_FILE"
set +a
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
[ -r "$RESTIC_PASSWORD_FILE" ] || {
    echo "Missing RESTIC_PASSWORD_FILE: $RESTIC_PASSWORD_FILE" >&2
    exit 1
}

if restic --retry-lock 30m snapshots --json >/dev/null 2>&1; then
    echo "Restic repository already initialized"
else
    restic init
fi
restic --retry-lock 30m snapshots --json >/dev/null
