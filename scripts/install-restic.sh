#!/bin/bash
set -euo pipefail

readonly RESTIC_VERSION="0.19.1"
readonly RELEASE_BASE="https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}"

[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
for command_name in curl bzip2 sha256sum install mktemp; do
    command -v "$command_name" >/dev/null || {
        echo "Missing required command: $command_name" >&2
        exit 1
    }
done

if [ -x /usr/local/bin/restic ] \
    && /usr/local/bin/restic version \
        | grep -Eq '^restic 0\.19\.1 compiled with go[^ ]+ on linux/(amd64|arm64)$'; then
    exit 0
fi

case "$(uname -m)" in
    x86_64)
        archive="restic_0.19.1_linux_amd64.bz2"
        checksum="f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c"
        ;;
    aarch64|arm64)
        archive="restic_0.19.1_linux_arm64.bz2"
        checksum="a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465"
        ;;
    *)
        echo "Unsupported architecture for pinned restic release: $(uname -m)" >&2
        exit 1
        ;;
esac

download_dir=$(mktemp -d /tmp/wai-restic-install.XXXXXX)
target_tmp=$(mktemp /usr/local/bin/.restic.XXXXXX)
cleanup() {
    case "$download_dir" in
        /tmp/wai-restic-install.*) rm -rf -- "$download_dir" ;;
        *) echo "Refusing to remove unexpected restic download path" >&2 ;;
    esac
    case "$target_tmp" in
        /usr/local/bin/.restic.*) rm -f -- "$target_tmp" ;;
        *) echo "Refusing to remove unexpected restic target path" >&2 ;;
    esac
}
trap cleanup EXIT

curl --fail --show-error --silent --location \
    "$RELEASE_BASE/$archive" --output "$download_dir/$archive"
printf '%s  %s\n' "$checksum" "$archive" > "$download_dir/SHA256SUMS"
(
    cd "$download_dir"
    sha256sum --check SHA256SUMS
)
bzip2 --decompress --stdout "$download_dir/$archive" > "$target_tmp"
chown root:root "$target_tmp"
chmod 0755 "$target_tmp"
"$target_tmp" version \
    | grep -Eq '^restic 0\.19\.1 compiled with go[^ ]+ on linux/(amd64|arm64)$'
mv -f "$target_tmp" /usr/local/bin/restic
/usr/local/bin/restic version \
    | grep -Eq '^restic 0\.19\.1 compiled with go[^ ]+ on linux/(amd64|arm64)$'
