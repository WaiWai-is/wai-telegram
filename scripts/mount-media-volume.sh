#!/bin/bash
set -euo pipefail

readonly MOUNT_POINT="/srv/wai-telegram-media"

usage() {
    echo "Usage: $0 --device /dev/disk/by-id/... [--format-empty-volume]" >&2
    exit 2
}

device=""
format_empty=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --device) device="${2:-}"; shift 2 ;;
        --format-empty-volume) format_empty=true; shift ;;
        *) usage ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
[ -n "$device" ] || usage
[ -b "$device" ] || { echo "Not a block device: $device" >&2; exit 1; }
getent group wai-media >/dev/null || groupadd --system wai-media
if id wai >/dev/null 2>&1; then
    usermod -a -G wai-media wai
fi

filesystem=$(blkid -s TYPE -o value "$device" || true)
if [ -z "$filesystem" ]; then
    if [ "$format_empty" != true ]; then
        echo "Device has no filesystem; pass --format-empty-volume explicitly" >&2
        exit 1
    fi
    mkfs.ext4 -m 0 -L wai-telegram-media "$device"
    filesystem="ext4"
fi
[ "$filesystem" = "ext4" ] || {
    echo "Expected ext4, found: $filesystem" >&2
    exit 1
}

mkdir -p "$MOUNT_POINT"
uuid=$(blkid -s UUID -o value "$device")
[ -n "$uuid" ] || { echo "Could not resolve volume UUID" >&2; exit 1; }
fstab_entry="UUID=$uuid $MOUNT_POINT ext4 defaults,nofail,noatime 0 2"
uuid_target=$(awk -v needle="UUID=$uuid" '$1 == needle {print $2}' /etc/fstab)
if [ -n "$uuid_target" ] && [ "$uuid_target" != "$MOUNT_POINT" ]; then
    echo "Volume UUID is already assigned to $uuid_target" >&2
    exit 1
fi
target_uuid=$(awk -v target="$MOUNT_POINT" '$2 == target {print $1}' /etc/fstab)
if [ -n "$target_uuid" ] && [ "$target_uuid" != "UUID=$uuid" ]; then
    echo "Mount target is already assigned to $target_uuid" >&2
    exit 1
fi
if [ -z "$uuid_target" ] && [ -z "$target_uuid" ]; then
    printf '%s\n' "$fstab_entry" >> /etc/fstab
fi
if mountpoint -q "$MOUNT_POINT"; then
    current_uuid=$(findmnt -n -o UUID --target "$MOUNT_POINT")
    [ "$current_uuid" = "$uuid" ] || {
        echo "Mount target is occupied by UUID $current_uuid" >&2
        exit 1
    }
else
    mount "$MOUNT_POINT"
fi
mountpoint -q "$MOUNT_POINT"
mounted_uuid=$(findmnt -n -o UUID --target "$MOUNT_POINT")
[ "$mounted_uuid" = "$uuid" ] || {
    echo "Mounted volume UUID mismatch: expected $uuid, found $mounted_uuid" >&2
    exit 1
}
chown root:wai-media "$MOUNT_POINT"
chmod 0770 "$MOUNT_POINT"
df -h "$MOUNT_POINT"
