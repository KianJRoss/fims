#!/usr/bin/env python3
"""Layered enrichment watcher.

Cycle:
  1. scraper adds candidate evidence only
  2. AI sentry reviews ledger groups
  3. ledger applies only verified + sentry-approved facts

This keeps scraping, AI arbitration, and DB writes separated.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


AUDIT_DIR = Path(__file__).resolve().parent
SCRAPER = AUDIT_DIR / "scrape_enrich.py"
SENTRY = AUDIT_DIR / "ai_enrich_sentry.py"


def run_step(args: list[str]) -> int:
    print("$ " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=str(AUDIT_DIR.parents[1]), text=True)
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Layered scraper + AI sentry enrichment watcher")
    parser.add_argument("--scrape-limit", type=int, default=10)
    parser.add_argument("--sentry-limit", type=int, default=20)
    parser.add_argument("--backend", choices=("ollama", "claude-cli", "dry-run"), default="ollama")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--sleep", type=float, default=180.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    while True:
        scrape_cmd = [
            sys.executable,
            "-u",
            str(SCRAPER),
            "--limit",
            str(args.scrape_limit),
        ]
        scrape_rc = run_step(scrape_cmd)

        sentry_cmd = [
            sys.executable,
            "-u",
            str(SENTRY),
            "--backend",
            args.backend,
            "--limit",
            str(args.sentry_limit),
            "--apply",
        ]
        if args.model:
            sentry_cmd.extend(["--model", args.model])
        if args.ollama_host:
            sentry_cmd.extend(["--ollama-host", args.ollama_host])
        sentry_rc = run_step(sentry_cmd)

        if scrape_rc != 0 or sentry_rc != 0:
            print(f"cycle finished with scrape_rc={scrape_rc} sentry_rc={sentry_rc}", flush=True)
        if args.once:
            return 0 if scrape_rc == 0 and sentry_rc == 0 else 1
        time.sleep(max(1.0, args.sleep))


if __name__ == "__main__":
    raise SystemExit(main())
