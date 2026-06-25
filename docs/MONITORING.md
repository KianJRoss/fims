# FIMS Monitoring

Two-tier monitoring for the KianPotPi deployment: a dumb cron health check that
always runs, and an optional AI layer that turns raw alerts into plain-English
guidance for the store owner.

```
cron (*/5 min)
  └─ scripts/health_check.py
        ├─ checks: disk, containers, queue backlog, error-log rate
        ├─ on failure → ntfy.sh push (high priority)        [Tier 1, always on]
        └─ POST /v1/monitoring/alert  ─┐
                                       ▼
        Celery task analyze_and_notify  (queue: imports)     [Tier 2, opt-in]
            ├─ loads AiMonitorConfig (must be enabled)
            ├─ asks Claude "what's happening / what to do"
            └─ ntfy.sh push titled "FIMS AI Insight"
```

## Tier 1 — cron health check (always on)

`scripts/health_check.py`, run every 5 minutes by cron. No dependencies beyond
stdlib + the `docker` CLI.

Checks:
- **Disk** ≥ 85% used
- **Containers** any `docker compose` service exited / restarting / unhealthy
- **Queue backlog** Redis `LLEN` ≥ 50 on `default`, `imports`, `reports`
- **Error rate** ≥ 20 `ERROR` lines across `docker compose logs --since 10m`

Anti-spam: each distinct failure key has a 1-hour cooldown, persisted in
`scripts/.health_check_state.json` (gitignored).

Alerts go to **ntfy.sh** topic `fims-kianpotpi-4e7f4b852168`. Subscribe on a
phone with the ntfy app (it's a shared secret — anyone with the topic string can
read/post, so keep it private).

### Test / install

```bash
# See what would fire, without sending anything
python3 scripts/health_check.py --dry-run

# Install the cron job (idempotent-ish; check `crontab -l` first)
(crontab -l 2>/dev/null; cat scripts/health_check_crontab.txt) | crontab -
```

Already installed on KianPotPi (`crontab -l` to confirm).

## Tier 2 — AI insight layer

When an alert fires, `health_check.py` hands it to an AI backend selected by the
`FIMS_AI_MONITOR` env var (default `cli`):

| `FIMS_AI_MONITOR` | Behavior |
|-------------------|----------|
| `cli` (default)   | Host-side `claude` CLI investigator (recommended) |
| `api`             | Containerized Celery → Anthropic API summarizer (fallback) |
| `both`            | Run both |
| `none`            | Tier 1 only — no AI |

### Backend `cli` — host-side investigator (recommended)

Runs the `claude` CLI **on the Pi host** (where it has real access), gives it a
**read-only** shell whitelist, and lets it actually investigate the failure —
tail container logs, check `docker compose ps`, read queue depths — then pushes a
plain-English root-cause to ntfy titled "FIMS AI Insight".

This is strictly more useful than the API summarizer: a one-shot API call only
sees the alert text, while the host agent can read logs and find the real cause.
It also bills against your **Claude subscription** (CLI login), not the API.

- Allowed tools (hard boundary — anything else is auto-denied in `--print` mode):
  `docker compose logs/ps`, `docker compose exec -T redis redis-cli`,
  `docker ps`, `df`, `free`, `uptime`. It cannot restart, edit, or change
  anything.
- Env: `FIMS_CLAUDE_BIN` overrides the CLI path. The script also probes
  `which claude`, `/usr/local/bin`, `/usr/bin`, `~/.npm-global/bin`,
  `~/.local/bin`. If it can't find `claude` it skips silently (Tier 1 still works).

**Install + auth on the Pi (one-time, as the cron user):**

```bash
npm i -g @anthropic-ai/claude-code   # Node already present on KianPotPi
claude                               # log in once (subscription OAuth); creds persist in ~/.claude
which claude                         # note the path
```

**cron caveat:** cron runs with a minimal `PATH`, so it may not find `claude`
even after install. Either add `PATH=...` to the crontab, or set
`FIMS_CLAUDE_BIN=/full/path/to/claude` in the crontab line, e.g.:

```cron
*/5 * * * * cd /home/krioasns/fims && FIMS_CLAUDE_BIN=$(npm prefix -g)/bin/claude /usr/bin/python3 scripts/health_check.py >/dev/null 2>&1
```

### Backend `api` — containerized summarizer (fallback)

Disabled by default; configure on the **Settings** page. Paste an Anthropic key
(stored encrypted as `encrypted_api_key`) to call `claude-sonnet-4-6` from the
worker. The Settings "CLI" option here runs `claude -p` *inside the worker
container*, which has no CLI installed — so it will fail; prefer API-key mode for
this backend, or use the host `cli` backend above instead.

Flow: `/v1/monitoring/alert` (`backend/app/api/v1/endpoints/monitoring.py`)
queues `analyze_and_notify` (`backend/app/worker/tasks/monitoring.py`), which
reads `AiMonitorConfig`, calls `app/services/ai_monitor.py`, and pushes the
result to ntfy. If config is missing or `enabled = false`, the task is a no-op,
so Tier 1 alerts still arrive raw. Use the **Test** button in Settings to verify
connectivity (sends "Reply with exactly: OK"); result is stored in
`last_test_status` / `last_test_message`.

## Files

| Concern | Path |
|---------|------|
| Cron script | `scripts/health_check.py` |
| Cron entry | `scripts/health_check_crontab.txt` |
| API endpoint | `backend/app/api/v1/endpoints/monitoring.py` |
| Celery task | `backend/app/worker/tasks/monitoring.py` |
| AI backend | `backend/app/services/ai_monitor.py` |
| DB model | `backend/app/models/monitoring.py` (`ai_monitor_configs`) |
| Migration | `backend/alembic/versions/d1f2e3c4b5a6_add_ai_monitor_config.py` |
| Settings UI | `frontend/src/pages/Settings.tsx` (AI Monitoring section) |

## Deploy to KianPotPi

The AI layer (Tier 2) requires the backend changes + migration. After pulling:

```bash
cd ~/fims
git pull
docker compose build api worker   # picks up new task/service/model code
docker compose up -d
docker compose exec api alembic upgrade head   # creates ai_monitor_configs
```

Then enable + configure on the Settings page. Tier 1 cron needs no rebuild — it
runs on the host against the running stack.

## Tuning

Thresholds are constants at the top of `health_check.py`
(`COOLDOWN_SECONDS`, queue/disk/error limits, `QUEUE_NAMES`). The ntfy topic is
defined in both `health_check.py` and `worker/tasks/monitoring.py` — keep them in
sync if you rotate it.
