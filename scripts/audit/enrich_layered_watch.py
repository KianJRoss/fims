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
import json
import subprocess
import sys
import time
from pathlib import Path


AUDIT_DIR = Path(__file__).resolve().parent
SCRAPER = AUDIT_DIR / "scrape_enrich.py"
SENTRY = AUDIT_DIR / "ai_enrich_sentry.py"


def run_step(args: list[str]) -> tuple[int, str]:
    print("$ " + " ".join(args), flush=True)
    result = subprocess.run(
        args,
        cwd=str(AUDIT_DIR.parents[1]),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    return result.returncode, output


def parse_scrape_result(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        if not line.startswith("JSON_RESULT "):
            continue
        try:
            parsed = json.loads(line[len("JSON_RESULT ") :])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Layered scraper + AI sentry enrichment watcher")
    parser.add_argument("--product-limit", type=int, default=0, help="products per process run; 0 means unlimited")
    parser.add_argument("--sentry-limit", type=int, default=20, help="max field groups reviewed for each product")
    parser.add_argument("--backend", choices=("ollama", "claude-cli", "dry-run"), default="ollama")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--vision-steps", default="ocr,codes,vlm")
    parser.add_argument("--sleep", type=float, default=180.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--non-instore",
        action="store_true",
        help="enrich in_store=false catalog products (the cron prefill pass) instead of kiosk products",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    processed = 0
    while True:
        scrape_cmd = [
            sys.executable,
            "-u",
            str(SCRAPER),
            "--one",
            "--json-result",
            "--limit",
            "1",
        ]
        if args.non_instore:
            scrape_cmd.append("--non-instore")
        scrape_rc, scrape_output = run_step(scrape_cmd)
        scrape_result = parse_scrape_result(scrape_output)
        item_number = str(scrape_result.get("item_number", "")).strip() if scrape_result else ""
        product_id = str(scrape_result.get("product_id", "")).strip() if scrape_result else ""
        product_label = item_number or product_id
        if scrape_rc != 0 or not product_label:
            print(f"product transaction stopped with scrape_rc={scrape_rc}; no product result", flush=True)
            if args.once:
                return 1
            time.sleep(max(1.0, args.sleep))
            continue

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
        if item_number:
            sentry_cmd.extend(["--only-sku", item_number])
        if product_id:
            sentry_cmd.extend(["--only-product-id", product_id])
        if args.model:
            sentry_cmd.extend(["--model", args.model])
        if args.ollama_host:
            sentry_cmd.extend(["--ollama-host", args.ollama_host])
        if args.vision:
            sentry_cmd.append("--vision")
            sentry_cmd.extend(["--vision-steps", args.vision_steps])
        sentry_rc, _sentry_output = run_step(sentry_cmd)

        if scrape_rc != 0 or sentry_rc != 0:
            print(
                f"product transaction {product_label} finished with scrape_rc={scrape_rc} sentry_rc={sentry_rc}",
                flush=True,
            )
        processed += 1
        if args.once or (args.product_limit and processed >= args.product_limit):
            return 0 if scrape_rc == 0 and sentry_rc == 0 else 1
        time.sleep(max(1.0, args.sleep))


if __name__ == "__main__":
    raise SystemExit(main())
