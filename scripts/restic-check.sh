#!/bin/bash
set -euo pipefail

readonly RESTIC_ENV_FILE="/etc/wai-telegram/restic.env"
[ -r "$RESTIC_ENV_FILE" ] || { echo "Missing $RESTIC_ENV_FILE" >&2; exit 1; }
set -a
source "$RESTIC_ENV_FILE"
set +a
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"
restic --retry-lock 30m check --read-data-subset=10%
