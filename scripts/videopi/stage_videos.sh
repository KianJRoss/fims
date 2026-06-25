#!/usr/bin/env bash
#
# FIMS Video Pi staging — download the confirmed product demo videos and stage
# them FLAT, ready to copy onto the Video Pi's USB (/media/pi/VIDEOS/videos/).
#
# The kiosk (backend/app/api/v1/endpoints/video_library.py) plays a product's
# video by using product_videos.video_filename verbatim as the on-disk name
# under /media/pi/VIDEOS/videos/, and builds the idle loop by substring-matching
# video_filename against the files actually present on the Video Pi. So each
# staged file is named "{youtube_id}.mp4" and we set video_filename to match.
# youtube_id is used (not item_number) because item numbers contain '/' and
# spaces that are illegal in filenames; youtube_ids are unique and filesystem-safe.
#
# Run on the LAPTOP (has yt-dlp + ffprobe + disk space). The Pi hub DB stays the
# source of truth and is updated here. The actual copy to the Video Pi happens
# later, when the device is plugged in -- see scripts/videopi/deploy_to_videopi.sh.
#
#   scripts/videopi/stage_videos.sh            # stage everything outstanding
#   scripts/videopi/stage_videos.sh --limit 3  # test on a few first
#   scripts/videopi/stage_videos.sh --redownload  # ignore existing staged files
#
# Idempotent + resumable: a file already in the staging dir is not re-downloaded,
# just re-probed and its DB row reconciled. Safe to re-run after an interruption.
set -uo pipefail

PI_HOST=100.73.208.99
PGIMG=postgres:17-alpine
STAGING=media/videopi_staging
LIMIT=0
REDOWNLOAD=0
MAXH=720          # cap resolution -- store TV + USB size

while [ $# -gt 0 ]; do
    case "$1" in
        --limit) shift; LIMIT="$1" ;;
        --redownload) REDOWNLOAD=1 ;;
        --maxh) shift; MAXH="$1" ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

mkdir -p "$STAGING"

psql_pi() { docker run --rm -i -e PGPASSWORD=fims "$PGIMG" \
    psql -h "$PI_HOST" -p 5432 -U fims -d fims "$@"; }

echo "Fetching confirmed videos with a youtube_id from the Pi hub ..."
# id|youtube_id  for every confirmed row that has a youtube id
ROWS=$(psql_pi -t -A -F'|' -c \
  "SELECT id, youtube_id FROM product_videos
    WHERE confirmed AND youtube_id IS NOT NULL AND youtube_id <> ''
    ORDER BY id")

total=$(printf '%s\n' "$ROWS" | grep -c . || true)
[ "$LIMIT" -gt 0 ] && echo "(limiting to first $LIMIT of $total)"
echo "Found $total confirmed video(s) to stage into $STAGING/"

ok=0; skip=0; fail=0; done_count=0
SQLBUF=""
flush() {
    [ -z "$SQLBUF" ] && return 0
    printf '%s\n' "$SQLBUF" | psql_pi -q >/dev/null 2>&1 \
        && echo "  [db] flushed batch" || echo "  [db] flush FAILED"
    SQLBUF=""
}

i=0
while IFS='|' read -r id yid; do
    [ -z "$id" ] && continue
    i=$((i+1))
    [ "$LIMIT" -gt 0 ] && [ "$i" -gt "$LIMIT" ] && break
    fname="${yid}.mp4"
    fpath="$STAGING/$fname"

    if [ "$REDOWNLOAD" -eq 0 ] && [ -s "$fpath" ]; then
        echo "[$i/$total] $yid  already staged, reconciling DB"
        skip=$((skip+1))
    else
        echo "[$i/$total] $yid  downloading (<=${MAXH}p) ..."
        if yt-dlp --no-progress --quiet --no-warnings \
            -f "bestvideo[height<=${MAXH}][ext=mp4]+bestaudio[ext=m4a]/best[height<=${MAXH}][ext=mp4]/best[ext=mp4]/best" \
            --merge-output-format mp4 \
            -o "$fpath" -- "$yid" 2>/dev/null && [ -s "$fpath" ]; then
            ok=$((ok+1))
        else
            echo "    FAILED: $yid"
            fail=$((fail+1))
            continue
        fi
    fi

    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$fpath" 2>/dev/null \
          | awk '{printf "%d", $1}')
    [ -z "$dur" ] && dur="NULL"

    SQLBUF="${SQLBUF}UPDATE product_videos SET video_filename='${fname}', file_path='videos/${fname}', download_status='done', duration_seconds=${dur} WHERE id=${id};
"
    done_count=$((done_count+1))
    [ $((done_count % 20)) -eq 0 ] && flush
done <<< "$ROWS"

flush

echo
echo "==== staging complete ===="
echo "  downloaded : $ok"
echo "  already had: $skip"
echo "  failed     : $fail"
echo "  DB rows set: $done_count  (video_filename + download_status=done)"
echo "  staged in  : $STAGING/   (flat, {youtube_id}.mp4)"
echo "Next: when the Video Pi is plugged in, run scripts/videopi/deploy_to_videopi.sh"
