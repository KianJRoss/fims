#!/usr/bin/env bash
#
# Nightly FIMS database backup — runs ON THE PI from cron.
# Dumps the whole DB (products, prices, SALES) to ~/fims/backups, keeps the
# last 14, and opportunistically copies the newest dump to the laptop and PC
# spokes when they're awake (same boxes the DB mesh uses).
#
# Install (on the Pi):
#   chmod +x /home/krioasns/fims/scripts/db/backup_db.sh
#   (crontab -l 2>/dev/null; echo '30 3 * * * /home/krioasns/fims/scripts/db/backup_db.sh') | crontab -
#
set -uo pipefail

REPO=/home/krioasns/fims
BACKUP_DIR="$REPO/backups"
KEEP=14
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/fims_${STAMP}.sql.gz"
LOG="$BACKUP_DIR/backup.log"

declare -A SPOKE=(
    [laptop]="batma@100.123.23.84:fims-backups"
    [pc]="batma@100.99.89.118:fims-backups"
)

mkdir -p "$BACKUP_DIR"

if docker exec fims-postgres-1 pg_dump -U fims fims | gzip > "$OUT"; then
    echo "[$(date '+%F %T')] ok $(du -h "$OUT" | cut -f1) $OUT" >> "$LOG"
else
    echo "[$(date '+%F %T')] FAILED pg_dump" >> "$LOG"
    rm -f "$OUT"
    exit 1
fi

# rotate: keep the newest $KEEP dumps
ls -t "$BACKUP_DIR"/fims_*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -f

# best-effort off-Pi copies; spokes are often asleep, that's fine
for dest in "${SPOKE[@]}"; do
    scp -o ConnectTimeout=5 -o BatchMode=yes "$OUT" "$dest/" >/dev/null 2>&1 \
        && echo "[$(date '+%F %T')] copied to $dest" >> "$LOG" \
        || echo "[$(date '+%F %T')] spoke offline: $dest" >> "$LOG"
done
