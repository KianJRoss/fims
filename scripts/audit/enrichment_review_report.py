#!/usr/bin/env python3
"""Print exact enrichment candidates that were denied, pending, or conflicted.

This is an audit/viewer tool only. It never writes to the ledger or database.
Use it when the sentry may be too strict and a human needs to see the exact
candidate value, source URL, identity check, confidence, and rejection reason.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


AUDIT_DIR = Path(__file__).resolve().parent
LEDGER_PATH = AUDIT_DIR / "evidence_ledger.json"
SENTRY_LOG_PATH = AUDIT_DIR / "ai_enrich_sentry_log.jsonl"


def load_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def load_sentry_logs() -> list[dict[str, Any]]:
    if not SENTRY_LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in SENTRY_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def norm(value: Any) -> str:
    return str(value or "").strip()


def product_label(rec: dict[str, Any]) -> str:
    item = norm(rec.get("item_number"))
    pid = norm(rec.get("product_id"))
    name = norm(rec.get("name"))
    bits = []
    if item:
        bits.append(item)
    elif pid:
        bits.append(pid)
    if name:
        bits.append(name)
    return " - ".join(bits) or "(unknown product)"


def selected(rec: dict[str, Any], mode: str) -> bool:
    status = norm(rec.get("status"))
    sentry_status = norm(rec.get("sentry_status"))
    value = norm(rec.get("value"))
    if mode == "denied":
        return sentry_status == "rejected" or status == "rejected"
    if mode == "sentry-rejected":
        return sentry_status == "rejected"
    if mode == "auto-rejected":
        return status == "rejected" and sentry_status != "rejected"
    if mode == "pending":
        return status == "pending"
    if mode == "conflict":
        return status == "conflict"
    if mode == "no-candidates":
        return status == "rejected" and value.startswith("NO_CANDIDATES:")
    return True


def enrich_with_log_reason(records: list[dict[str, Any]], logs: list[dict[str, Any]]) -> None:
    by_index: dict[int, dict[str, Any]] = {}
    for log in logs:
        decision = log.get("decision") if isinstance(log.get("decision"), dict) else {}
        for candidate in log.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            index = candidate.get("ledger_index")
            if not isinstance(index, int):
                continue
            by_index[index] = {
                "reviewed_at": log.get("reviewed_at"),
                "decision": decision,
            }
    for index, rec in enumerate(records):
        if index in by_index:
            rec["_sentry_log"] = by_index[index]


def compact(value: Any, limit: int) -> str:
    text = " ".join(norm(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def print_text(records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if not records:
        print("No matching enrichment candidates.")
        return
    for index, rec in enumerate(records, start=1):
        log = rec.get("_sentry_log") if isinstance(rec.get("_sentry_log"), dict) else {}
        decision = log.get("decision") if isinstance(log.get("decision"), dict) else {}
        reason = (
            rec.get("sentry_reason")
            or decision.get("reason")
            or rec.get("rejected_reason")
            or rec.get("status")
            or ""
        )
        print(f"\n[{index}] {product_label(rec)}")
        print(f"field: {rec.get('field', '')}")
        print(f"value: {compact(rec.get('value'), args.value_limit)}")
        print(f"status: {rec.get('status', '')}  sentry_status: {rec.get('sentry_status', '')}")
        print(f"reason: {compact(reason, args.value_limit)}")
        print(f"confidence: {rec.get('confidence', '')}")
        print(f"identity_check: {compact(rec.get('identity_check'), args.value_limit)}")
        print(f"source: {rec.get('source', '')}")
        print(f"url: {rec.get('url', '')}")
        if rec.get("quick_reject_reason"):
            print(f"quick_reject_reason: {rec.get('quick_reject_reason')}")
        if log:
            print(f"sentry_reviewed_at: {log.get('reviewed_at', '')}")


def print_summary(records: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for rec in records:
        key = f"{rec.get('status', '')}/{rec.get('sentry_status', '')}"
        counts[key] = counts.get(key, 0) + 1
        reason = norm(rec.get("sentry_reason") or rec.get("rejected_reason") or "(no reason)")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    print("status counts:")
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:4}  {key}")
    print("\nreason counts:")
    for reason, count in sorted(by_reason.items(), key=lambda item: (-item[1], item[0]))[:30]:
        print(f"  {count:4}  {compact(reason, 120)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit exact enrichment candidates and denial reasons")
    parser.add_argument(
        "--mode",
        choices=("denied", "sentry-rejected", "auto-rejected", "pending", "conflict", "no-candidates", "all"),
        default="denied",
    )
    parser.add_argument("--sku", default="", help="filter by exact item number/SKU")
    parser.add_argument("--product-id", default="", help="filter by exact product UUID")
    parser.add_argument("--field", default="", help="filter by field name")
    parser.add_argument("--contains", default="", help="case-insensitive search across product/value/source/url/reason")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--value-limit", type=int, default=500)
    parser.add_argument("--summary", action="store_true", help="print counts instead of detailed rows")
    parser.add_argument("--json", action="store_true", help="emit matching rows as JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_ledger()
    enrich_with_log_reason(records, load_sentry_logs())
    needle = args.contains.lower().strip()
    matches: list[dict[str, Any]] = []
    for rec in records:
        if not selected(rec, args.mode):
            continue
        if args.sku and norm(rec.get("item_number")).upper() != args.sku.upper():
            continue
        if args.product_id and norm(rec.get("product_id")) != args.product_id:
            continue
        if args.field and norm(rec.get("field")) != args.field:
            continue
        if needle:
            haystack = json.dumps(rec, ensure_ascii=False).lower()
            if needle not in haystack:
                continue
        matches.append(rec)
    if args.summary:
        print_summary(matches)
        return
    limited = matches[: args.limit] if args.limit else matches
    if args.json:
        print(json.dumps(limited, ensure_ascii=False, indent=2))
    else:
        print_text(limited, args)
        if args.limit and len(matches) > args.limit:
            print(f"\nShowing {args.limit} of {len(matches)} matches. Use --limit 0 for all.")


if __name__ == "__main__":
    main()
