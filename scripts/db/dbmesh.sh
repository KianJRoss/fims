#!/usr/bin/env bash
#
# FIMS DB mesh tool — snapshot / clone / restore a node's Postgres from anywhere.
#
# Layer 0 of the database-mesh plan: the safe foundation (backups, full clones,
# and hotswap-with-safety-net). The bidirectional last-write-wins SYNC lives in a
# separate tool (scripts/db/dbsync.py) and is built on top of this. You want a
# working restore button before you ever turn on sync.
#
# It runs from ANY machine (laptop/PC/Pi) with Docker installed and needs no local
# psql/pg_dump: it shells out to a throwaway `postgres:17` container that connects
# to each node's published 5432 over Tailscale.
#
# Nodes (each publishes 5432; see docker-compose.yml `ports: 5432:5432`):
#   pi      100.73.208.99   (the always-on primary / hub)
#   pc      100.99.89.118   (secondary dev box, often offline)
#   laptop  100.123.23.84   (primary dev box)
#   local   host.docker.internal  (whatever machine you're running this on)
#
# Usage:
#   scripts/db/dbmesh.sh snapshot [node]            # dump node -> backups/  (default: pi)
#   scripts/db/dbmesh.sh clone <src> <dst>          # copy src's DB onto dst (snapshots dst first)
#   scripts/db/dbmesh.sh restore <file.sql.gz> <dst>   # restore a dump onto dst (snapshots dst first)
#   scripts/db/dbmesh.sh list                        # list local backups
#
# Examples:
#   scripts/db/dbmesh.sh snapshot pi                 # nightly-style backup of the Pi
#   scripts/db/dbmesh.sh clone pi local              # pull a fresh full copy of the Pi to this machine
#   scripts/db/dbmesh.sh restore backups/fims_pi_20260625.sql.gz pi   # hotswap a copy onto the Pi
#
set -euo pipefail

PG_IMAGE="${FIMS_PG_IMAGE:-postgres:17-alpine}"
DB_USER="${FIMS_DB_USER:-fims}"
DB_NAME="${FIMS_DB_NAME:-fims}"
DB_PASS="${FIMS_DB_PASS:-fims}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${FIMS_BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

node_host() {
  case "$1" in
    pi)     echo "100.73.208.99 5432" ;;
    pc)     echo "100.99.89.118 5432" ;;
    laptop) echo "100.123.23.84 5432" ;;
    local)  echo "host.docker.internal 5432" ;;
    *)      echo "" ;;
  esac
}

die() { echo "ERROR: $*" >&2; exit 1; }

resolve() {  # node -> "host port", validates
  local hp; hp="$(node_host "$1")"
  [ -n "$hp" ] || die "unknown node '$1' (use: pi | pc | laptop | local)"
  echo "$hp"
}

ping_node() {  # node -> ok/fail, prints version
  local host port; read -r host port <<<"$(resolve "$1")"
  docker run --rm -e PGPASSWORD="$DB_PASS" "$PG_IMAGE" \
    psql -h "$host" -p "$port" -U "$DB_USER" -d "$DB_NAME" -tAc "select 1" >/dev/null 2>&1
}

dump_node() {  # node -> gzip stream on stdout
  local host port; read -r host port <<<"$(resolve "$1")"
  # --clean --if-exists so a restore drops/recreates objects cleanly (full replace).
  docker run --rm -e PGPASSWORD="$DB_PASS" "$PG_IMAGE" \
    pg_dump -h "$host" -p "$port" -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | gzip
}

restore_into() {  # file node
  local file="$1" node="$2" host port
  read -r host port <<<"$(resolve "$node")"
  [ -f "$file" ] || die "dump file not found: $file"
  local decomp="cat"
  case "$file" in *.gz) decomp="gzip -dc";; esac
  $decomp "$file" | docker run --rm -i -e PGPASSWORD="$DB_PASS" "$PG_IMAGE" \
    psql -h "$host" -p "$port" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q
}

snapshot() {  # node -> path
  local node="${1:-pi}" ts file
  ping_node "$node" || die "node '$node' is not reachable (offline? Tailscale down? stack not up?)"
  ts="$(date +%Y%m%d_%H%M%S)"
  file="$BACKUP_DIR/fims_${node}_${ts}.sql.gz"
  echo ">> snapshotting '$node' -> $file" >&2
  dump_node "$node" > "$file"
  echo ">> done ($(du -h "$file" | cut -f1))" >&2
  echo "$file"
}

cmd_snapshot() { snapshot "${1:-pi}"; }

cmd_clone() {
  local src="${1:?usage: clone <src> <dst>}" dst="${2:?usage: clone <src> <dst>}"
  [ "$src" != "$dst" ] || die "src and dst are the same node"
  ping_node "$src" || die "source '$src' not reachable"
  ping_node "$dst" || die "dest '$dst' not reachable"
  echo ">> safety snapshot of dest '$dst' before overwrite..." >&2
  local safety; safety="$(snapshot "$dst")"
  echo ">> cloning '$src' -> '$dst' ..." >&2
  local tmp; tmp="$(snapshot "$src")"   # also keeps a copy of src
  restore_into "$tmp" "$dst"
  echo ">> clone complete. '$dst' now mirrors '$src'." >&2
  echo ">> rollback if needed: scripts/db/dbmesh.sh restore '$safety' '$dst'" >&2
}

cmd_restore() {
  local file="${1:?usage: restore <file.sql.gz> <dst>}" dst="${2:?usage: restore <file> <dst>}"
  ping_node "$dst" || die "dest '$dst' not reachable"
  echo ">> safety snapshot of '$dst' before restore..." >&2
  local safety; safety="$(snapshot "$dst")"
  echo ">> restoring $file -> '$dst' ..." >&2
  restore_into "$file" "$dst"
  echo ">> restore complete." >&2
  echo ">> rollback if needed: scripts/db/dbmesh.sh restore '$safety' '$dst'" >&2
}

cmd_list() { ls -lh "$BACKUP_DIR"/*.sql.gz 2>/dev/null || echo "no backups in $BACKUP_DIR"; }

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    snapshot) cmd_snapshot "$@" ;;
    clone)    cmd_clone "$@" ;;
    restore)  cmd_restore "$@" ;;
    list)     cmd_list "$@" ;;
    *) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
  esac
}

main "$@"
