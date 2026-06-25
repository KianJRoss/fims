#!/usr/bin/env bash
#
# FIMS media sync — mirror product images across mesh nodes.
#
# dbsync.py syncs DB rows only; the actual image files in
# media/product_images/*.webp are NOT in the DB, so they must be mirrored
# separately. There is no rsync on the laptop's git-bash, so this uses
# tar-over-ssh and transfers ONLY the files the local node is missing
# (set difference on filename), making repeat runs cheap.
#
# Default direction is PULL from the Pi hub (the source of truth) into the
# local clone. Run from the repo root on the machine you want to fill in.
#
#   scripts/db/media_sync.sh                 # pull missing images from Pi
#   scripts/db/media_sync.sh --push          # push local-only images TO the Pi
#   scripts/db/media_sync.sh --dir documents # sync media/documents instead
#
# Safe + idempotent: never overwrites an existing local file, only adds
# missing ones. A second run with nothing new transfers zero bytes.
set -uo pipefail

PI_SSH="krioasns@100.73.208.99"
PI_REPO="~/fims"
SUBDIR="product_images"      # under media/
DIRECTION="pull"

while [ $# -gt 0 ]; do
    case "$1" in
        --push) DIRECTION="push" ;;
        --pull) DIRECTION="pull" ;;
        --dir)  shift; SUBDIR="$1" ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

LOCAL_DIR="media/$SUBDIR"
REMOTE_DIR="$PI_REPO/media/$SUBDIR"
mkdir -p "$LOCAL_DIR"

remote_list() { ssh -o ConnectTimeout=10 "$PI_SSH" "ls -1 $REMOTE_DIR 2>/dev/null"; }
local_list()  { ls -1 "$LOCAL_DIR" 2>/dev/null; }

if [ "$DIRECTION" = "pull" ]; then
    echo "Pull $SUBDIR: Pi -> local"
    # files on the Pi that are not present locally
    missing=$(comm -23 <(remote_list | sort) <(local_list | sort))
    n=$(printf '%s' "$missing" | grep -c . || true)
    echo "  missing locally: $n"
    [ "$n" -eq 0 ] && { echo "  up to date."; exit 0; }
    # tar just those files on the Pi, stream over ssh, extract here
    printf '%s\n' "$missing" \
        | ssh -o ConnectTimeout=10 "$PI_SSH" "cd $REMOTE_DIR && tar -T - -cf -" \
        | tar -C "$LOCAL_DIR" -xf -
    echo "  pulled $n file(s) into $LOCAL_DIR"
else
    echo "Push $SUBDIR: local -> Pi"
    extra=$(comm -13 <(remote_list | sort) <(local_list | sort))
    n=$(printf '%s' "$extra" | grep -c . || true)
    echo "  missing on Pi: $n"
    [ "$n" -eq 0 ] && { echo "  Pi up to date."; exit 0; }
    printf '%s\n' "$extra" \
        | tar -C "$LOCAL_DIR" -T - -cf - \
        | ssh -o ConnectTimeout=10 "$PI_SSH" "mkdir -p $REMOTE_DIR && tar -C $REMOTE_DIR -xf -"
    echo "  pushed $n file(s) to the Pi"
fi
