#!/usr/bin/env bash
# Usage: ./scripts/backup.sh
# Creates a timestamped pg_dump and tars media directory.

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
mkdir -p "$BACKUP_DIR"

echo "Dumping PostgreSQL..."
docker compose exec -T postgres pg_dump -U fims fims | gzip > "${BACKUP_DIR}/fims_${TIMESTAMP}.sql.gz"

echo "Archiving media..."
tar -czf "${BACKUP_DIR}/media_${TIMESTAMP}.tar.gz" ./media/

echo "Backup complete: ${BACKUP_DIR}/fims_${TIMESTAMP}.sql.gz"
