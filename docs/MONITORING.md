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

## Tier 2 — AI insight layer (opt-in)

Disabled by default. Configure it on the **Settings** page in the web UI.

- **Backend = API key (recommended):** paste an Anthropic key. Stored encrypted
  (`encrypted_api_key`), used to call `claude-sonnet-4-6` directly from the
  worker. This is the only backend that works inside the containerized worker.
- **Backend = CLI:** runs `claude -p` as a subprocess. ⚠️ Only works if the
  `claude` CLI is installed *inside the Celery worker container* — by default it
  is not, so this mode will fail there. Use API-key mode unless you've baked the
  CLI into the worker image.

Flow: `/v1/monitoring/alert` (`backend/app/api/v1/endpoints/monitoring.py`)
queues `analyze_and_notify` (`backend/app/worker/tasks/monitoring.py`), which
reads `AiMonitorConfig`, calls `app/services/ai_monitor.py`, and pushes the
result to ntfy. If config is missing or `enabled = false`, the task is a no-op,
so Tier 1 alerts still arrive raw.

Use the **Test** button in Settings to verify connectivity (sends "Reply with
exactly: OK"). Result is stored in `last_test_status` / `last_test_message`.

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
