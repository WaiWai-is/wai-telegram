#!/usr/bin/env bash
set -euo pipefail

release_root=${WAI_TELEGRAM_RELEASE_ROOT:-/opt/wai-telegram-releases}
current_link=${WAI_TELEGRAM_CURRENT_LINK:-/opt/wai-telegram}

[ -d "$release_root" ] || {
    echo "Release root does not exist: $release_root" >&2
    exit 1
}
[ -L "$current_link" ] || {
    echo "Current release link is not a symlink: $current_link" >&2
    exit 1
}

release_root=$(cd "$release_root" && pwd -P)
case "$(basename "$release_root")" in
    *releases*) ;;
    *)
        echo "Refusing unexpected release root: $release_root" >&2
        exit 1
        ;;
esac
current_release=$(cd "$current_link" && pwd -P)
[ "$(dirname "$current_release")" = "$release_root" ] || {
    echo "Current release is outside $release_root: $current_release" >&2
    exit 1
}
case "$(basename "$current_release")" in
    release-*) ;;
    *)
        echo "Current target is not an immutable release: $current_release" >&2
        exit 1
        ;;
esac

shopt -s nullglob

# A deploy that dies before cutover renames its directory to failed-* and leaves
# it there. Nothing else removes them, and two of them are enough to push the
# volume under the free-space floor the next deploy's preflight enforces.
for failed in "$release_root"/failed-*; do
    [ -d "$failed" ] || continue
    [ ! -L "$failed" ] || continue
    [ "$(dirname "$failed")" = "$release_root" ] || continue
    rm -rf -- "$failed"
    printf 'removed failed release: %s\n' "$failed"
done

candidates=("$release_root"/release-*)
rollback_kept=0
while IFS= read -r release; do
    [ -n "$release" ] || continue
    [ -d "$release" ] || continue
    [ ! -L "$release" ] || continue
    [ "$(dirname "$release")" = "$release_root" ] || {
        echo "Refusing release outside root: $release" >&2
        exit 1
    }
    if [ "$release" = "$current_release" ]; then
        continue
    fi
    if [ "$rollback_kept" -eq 0 ]; then
        rollback_kept=1
        continue
    fi
    rm -rf -- "$release"
    printf 'removed old release: %s\n' "$release"
done < <(
    if [ "${#candidates[@]}" -gt 0 ]; then
        ls -1dt "${candidates[@]}"
    fi
)
