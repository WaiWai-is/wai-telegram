#!/bin/bash
set -euo pipefail

# Pinned official tdlib/telegram-bot-api master commit, verified 2026-08-06.
readonly BOT_API_COMMIT="adfd7f6a8e990272851777eeb3ae0def4216f161"
readonly BOT_API_REPOSITORY="https://github.com/tdlib/telegram-bot-api.git"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root" >&2
    exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential cmake git gperf libssl-dev zlib1g-dev

build_root=$(mktemp -d /tmp/wai-telegram-bot-api.XXXXXX)
cleanup() {
    case "$build_root" in
        /tmp/wai-telegram-bot-api.*) rm -rf -- "$build_root" ;;
        *) echo "Refusing to remove unexpected build path" >&2 ;;
    esac
}
trap cleanup EXIT

git clone --recursive "$BOT_API_REPOSITORY" "$build_root/source"
git -C "$build_root/source" checkout --detach "$BOT_API_COMMIT"
git -C "$build_root/source" submodule update --init --recursive
cmake -S "$build_root/source" -B "$build_root/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_root/build" --target telegram-bot-api --parallel "$(nproc)"
install -o root -g root -m 0755 \
    "$build_root/build/telegram-bot-api" \
    /usr/local/bin/telegram-bot-api
install -d -o root -g root -m 0755 /usr/local/share/wai-telegram
marker=$(mktemp /usr/local/share/wai-telegram/.telegram-bot-api.commit.XXXXXX)
printf '%s\n' "$BOT_API_COMMIT" > "$marker"
chown root:root "$marker"
chmod 0644 "$marker"
mv -f "$marker" /usr/local/share/wai-telegram/telegram-bot-api.commit
/usr/local/bin/telegram-bot-api --version
