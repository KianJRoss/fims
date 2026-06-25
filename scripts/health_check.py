from pathlib import Path
import argparse
import json
import shutil
import subprocess
import time
import urllib.request


NTFY_TOPIC = "fims-kianpotpi-4e7f4b852168"  # ntfy.sh topic - keep private, anyone who knows this string can read/post
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
STATE_FILE = Path("scripts/.health_check_state.json")
COOLDOWN_SECONDS = 60 * 60
QUEUE_NAMES = ("default", "imports", "reports")


def run_command(args, capture_stderr=False):
    result = subprocess.run(
        args,
        cwd=Path("."),
        capture_output=True,
        text=True,
    )
    if capture_stderr:
        output = (result.stdout or "") + (result.stderr or "")
    else:
        output = result.stdout or ""
    return result.returncode, output


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if isinstance(data, dict):
        alerts = data.get("last_alerts", {})
        if isinstance(alerts, dict):
            return alerts
    return {}


def save_state(alert_times):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_alerts": alert_times}
    STATE_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_disk_space():
    total, used, _free = shutil.disk_usage(".")
    percent_used = (used / total) * 100 if total else 0
    if percent_used >= 85:
        return [("disk", f"Disk: {percent_used:.0f}% used")]
    return []


def check_container_health():
    returncode, output = run_command(["docker", "compose", "ps", "--format", "json"])

    if returncode != 0:
        detail = output.strip() or "docker compose ps failed"
        return [("container:compose-ps", f"Container health: {detail}")]

    failures = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        entries = record if isinstance(record, list) else [record]
        for item in entries:
            if not isinstance(item, dict):
                continue

            name = item.get("Name") or item.get("Service") or "container"
            state = str(item.get("State", "")).strip().lower()
            health = item.get("Health")
            health_value = str(health).strip().lower() if health is not None else ""

            if state.startswith("exited") or state == "restarting":
                failures.append((f"container:{name}", f"Container {name}: {state}"))
            elif health_value == "unhealthy":
                failures.append((f"container:{name}", f"Container {name}: unhealthy"))

    return failures


def check_queue_backlog():
    failures = []
    for queue_name in QUEUE_NAMES:
        returncode, output = run_command(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "LLEN", queue_name]
        )
        if returncode != 0:
            detail = output.strip() or "queue length command failed"
            failures.append((f"queue:{queue_name}", f"Queue '{queue_name}': {detail}"))
            continue

        try:
            queue_length = int(output.strip() or "0")
        except ValueError:
            failures.append((f"queue:{queue_name}", f"Queue '{queue_name}': unable to parse length"))
            continue

        if queue_length >= 50:
            failures.append((f"queue:{queue_name}", f"Queue '{queue_name}': {queue_length} pending"))

    return failures


def check_recent_errors():
    returncode, output = run_command(
        ["docker", "compose", "logs", "--since", "10m"],
        capture_stderr=True,
    )
    error_lines = sum(1 for line in output.splitlines() if "ERROR" in line)
    if returncode != 0 and not output.strip():
        return [("logs", "Recent logs: docker compose logs failed")]
    if error_lines >= 20:
        return [("logs", f"{error_lines} ERROR lines in last 10 min")]
    return []


def gather_failures():
    failures = []
    failures.extend(check_disk_space())
    failures.extend(check_container_health())
    failures.extend(check_queue_backlog())
    failures.extend(check_recent_errors())
    return failures


def build_alert(failures):
    lines = [detail for _key, detail in failures]
    return "FIMS health check alert", "\n".join(lines)


def should_alert(failures, state):
    now = time.time()
    for key, _detail in failures:
        last_alert = state.get(key)
        if last_alert is None:
            return True
        try:
            if now - float(last_alert) >= COOLDOWN_SECONDS:
                return True
        except (TypeError, ValueError):
            return True
    return False


def send_alert(title, body):
    request = urllib.request.Request(
        NTFY_URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": "high",
        },
    )
    with urllib.request.urlopen(request, timeout=10):
        return


def main():
    parser = argparse.ArgumentParser(description="Run FIMS health checks for cron.")
    parser.add_argument("--dry-run", action="store_true", help="Print the alert that would be sent.")
    args = parser.parse_args()

    failures = gather_failures()
    if not failures:
        print("all checks passed")
        return 0

    state = load_state()
    if not should_alert(failures, state):
        return 0

    title, body = build_alert(failures)

    if args.dry_run:
        print(f"Title: {title}")
        print("Priority: high")
        print(body)
        return 0

    send_alert(title, body)
    try:
        request = urllib.request.Request(
            "http://localhost:8000/v1/monitoring/alert",
            data=json.dumps({"subject": title, "detail": body}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5):
            pass
    except Exception:
        pass
    now = time.time()
    for key, _detail in failures:
        state[key] = now
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
