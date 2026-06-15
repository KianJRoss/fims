#!/usr/bin/env bash
# Usage: ./scripts/restore.sh backups/fims_20250101_120000.sql.gz

set -euo pipefail

DUMP_FILE="${1:?Usage: restore.sh <dump.sql.gz>}"

echo "Restoring $DUMP_FILE into Docker postgres..."
gunzip -c "$DUMP_FILE" | docker compose exec -T postgres psql -U fims fims

echo "Restore complete."
