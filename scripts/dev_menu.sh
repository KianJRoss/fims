#!/usr/bin/env bash

set -u

# Resolve the repo root from this script's location so commands work from any cwd.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

compose() {
  (cd "$REPO_ROOT" && docker compose "$@")
}

while true; do
  clear
  echo "FIMS Dev Menu"
  echo
  echo "A) Start all services - compose up -d"
  echo "B) Restart API only - compose restart api"
  echo "C) Run Alembic migrations - compose exec api alembic upgrade head"
  echo "D) Tail API logs - compose logs -f api"
  echo "E) Show running containers - compose ps"
  echo "F) Exit"
  echo
  read -r -n 1 -p "Choose an option: " choice
  echo

  case "${choice^^}" in
    A)
      compose up -d
      ;;
    B)
      compose restart api
      ;;
    C)
      compose exec api alembic upgrade head
      ;;
    D)
      compose logs -f api
      ;;
    E)
      compose ps
      ;;
    F)
      exit 0
      ;;
    *)
      echo "Invalid option: $choice"
      ;;
  esac

  echo
  read -r -p "Press enter to continue"
done
