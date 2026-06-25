#!/usr/bin/env bash
#
# FIMS Video Pi deploy — copy the FLAT staged videos onto the Video Pi's USB.
# Run this when the Video Pi is plugged in and reachable. The DB was already
# updated by stage_videos.sh, so once the files land in the flat videos dir the
# kiosk matches and plays them automatically (idle loop + scan-to-play).
#
# Video Pi (see CLAUDE.md Hardware Reference):
#   LAN 192.168.0.198, SSH pi@192.168.0.198, flat videos dir below.
#
#   scripts/videopi/deploy_to_videopi.sh           # copy only missing files
#   scripts/videopi/deploy_to_videopi.sh --check    # just report counts, copy nothing
#
# Only copies files the Video Pi is missing (filename set difference), so it is
# cheap to re-run after staging more videos.
set -uo pipefail

VPI_SSH="pi@192.168.0.198"
VPI_DIR="/media/pi/VIDEOS/videos"
STAGING="media/videopi_staging"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

[ -d "$STAGING" ] || { echo "no staging dir ($STAGING); run stage_videos.sh first" >&2; exit 1; }

echo "Probing Video Pi at $VPI_SSH ..."
if ! ssh -o ConnectTimeout=8 "$VPI_SSH" "test -d '$VPI_DIR' || mkdir -p '$VPI_DIR'" 2>/dev/null; then
    echo "Video Pi not reachable / USB not mounted at $VPI_DIR." >&2
    echo "Plug it in, confirm the USB is mounted, then re-run." >&2
    exit 1
fi

staged=$(ls -1 "$STAGING" 2>/dev/null | grep -i '\.mp4$' | sort)
onpi=$(ssh -o ConnectTimeout=8 "$VPI_SSH" "ls -1 '$VPI_DIR' 2>/dev/null" | sort)
missing=$(comm -23 <(printf '%s\n' "$staged") <(printf '%s\n' "$onpi"))
ns=$(printf '%s' "$staged"  | grep -c . || true)
nm=$(printf '%s' "$missing" | grep -c . || true)

echo "  staged locally : $ns"
echo "  already on Pi  : $(printf '%s' "$onpi" | grep -c . || true)"
echo "  to copy        : $nm"

if [ "$CHECK" -eq 1 ]; then echo "(--check: nothing copied)"; exit 0; fi
[ "$nm" -eq 0 ] && { echo "Video Pi already has every staged file."; exit 0; }

# stream only the missing files via tar over ssh. Prefix each name with "./" so
# YouTube IDs that start with '-' (e.g. -GlVylTKTWA.mp4) aren't parsed as tar options.
( cd "$STAGING" && printf '%s\n' "$missing" | sed 's#^#./#' | tar -T - -cf - ) \
    | ssh -o ConnectTimeout=8 "$VPI_SSH" "tar -C '$VPI_DIR' -xf -"

echo "Copied $nm file(s) to $VPI_DIR on the Video Pi."
echo "Reload the idle playlist from FIMS (Videos > Remote, or POST /api/v1/video-library/idle/sync)."
