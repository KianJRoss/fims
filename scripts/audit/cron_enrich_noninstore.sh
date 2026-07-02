#!/usr/bin/env bash
# Cron pass: gradually enrich in_store=false catalog products (new-product prefill
# corpus) via the layered scrape -> AI sentry -> gated-apply watcher.
#
# This is the "after this job / non-in-store" half of the enrichment plan. The
# in-store products are handled on-demand separately. Each cron tick does a
# bounded amount of work (PRODUCT_LIMIT products) so it never runs away.
#
# Deploy on KianPotPi (always-on FIMS host, repo at ~/fims). It reaches the PC's
# Ollama over Tailscale for the sentry. Suggested crontab (every 30 min):
#   */30 * * * * /home/krioasns/fims/scripts/audit/cron_enrich_noninstore.sh >> /home/krioasns/fims/scripts/audit/cron_enrich.log 2>&1
#
# DO NOT enable until the in-store on-demand pass is reviewed and signed off.

set -euo pipefail

REPO_ROOT="${FIMS_REPO_ROOT:-$HOME/fims}"
PRODUCT_LIMIT="${PRODUCT_LIMIT:-5}"          # products enriched per tick
SENTRY_BACKEND="${SENTRY_BACKEND:-ollama}"   # ollama | claude-cli | dry-run
OLLAMA_HOST="${OLLAMA_HOST:-http://100.99.89.118:11434}"  # PC over Tailscale
LOCK_FILE="${TMPDIR:-/tmp}/fims_enrich_noninstore.lock"

cd "$REPO_ROOT"

# Prevent overlapping runs: if a prior tick is still going, exit quietly.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Iseconds) another enrich tick is still running; skipping"
  exit 0
fi

PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

echo "$(date -Iseconds) starting non-instore enrich tick (limit=$PRODUCT_LIMIT backend=$SENTRY_BACKEND)"
PYTHONIOENCODING=utf-8 OLLAMA_HOST="$OLLAMA_HOST" "$PY" scripts/audit/enrich_layered_watch.py \
  --once \
  --non-instore \
  --product-limit "$PRODUCT_LIMIT" \
  --backend "$SENTRY_BACKEND" \
  --sleep 3
echo "$(date -Iseconds) tick complete"
