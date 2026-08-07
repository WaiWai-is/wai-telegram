#!/bin/bash
set -euo pipefail

cat >&2 <<'EOF'
Automatic rollback is intentionally disabled after the single-user cutover.

Restoring old code or downgrading migration 019 would reopen registration and
could reactivate archived access. Follow PRODUCTION_CUTOVER.md: preserve the
failed release, inspect the incident, and restore the verified encrypted dump
only with an explicit owner/access decision.
EOF
exit 1
