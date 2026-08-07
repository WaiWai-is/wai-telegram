#!/bin/bash
set -euo pipefail

cat >&2 <<'EOF'
Direct SSH deployment is disabled for WAI Telegram.

Use the manual "CI / Deploy" GitHub Actions workflow on main and approve the
protected production environment. The workflow enforces tests, encrypted DB
backup verification, OWNER_USER_ID evidence, media-volume checks, and the
explicit single-user cutover confirmation.
EOF
exit 1
