#!/usr/bin/env bash
#
# FIMS mesh scheduler — runs ON THE PI (the always-on hub) from cron.
# Syncs every reachable spoke against the hub with last-write-wins; silently
# skips spokes that are powered off. Safe to run on a schedule: dbsync.py is
# idempotent, so a run with no new edits is a no-op.
#
# Install (on the Pi):
#   chmod +x /home/krioasns/fims/scripts/db/mesh_cron.sh
#   (crontab -l 2>/dev/null; echo '*/10 * * * * /home/krioasns/fims/scripts/db/mesh_cron.sh') | crontab -
#
set -uo pipefail

REPO=/home/krioasns/fims
PY=/usr/bin/python3
LOG="$REPO/scripts/db/mesh_sync.log"
SPOKES=(laptop pc)
declare -A IP=( [laptop]=100.123.23.84 [pc]=100.99.89.118 )

ts() { date '+%Y-%m-%d %H:%M:%S'; }

cd "$REPO" || { echo "[$(ts)] repo missing" >>"$LOG"; exit 1; }

for s in "${SPOKES[@]}"; do
    # quick TCP probe of the spoke's Postgres; skip if the box is off
    if timeout 5 bash -c "exec 3<>/dev/tcp/${IP[$s]}/5432" 2>/dev/null; then
        echo "[$(ts)] sync pi<->$s ..." >>"$LOG"
        "$PY" scripts/db/dbsync.py pi "$s" --apply >>"$LOG" 2>&1 \
            && echo "[$(ts)] pi<->$s ok" >>"$LOG" \
            || echo "[$(ts)] pi<->$s FAILED" >>"$LOG"
    else
        echo "[$(ts)] $s offline, skip" >>"$LOG"
    fi
done

# keep the log from growing unbounded (last 2000 lines)
if [ -f "$LOG" ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
fi
