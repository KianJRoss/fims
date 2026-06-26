#!/usr/bin/env python3
"""AI sentry for product enrichment evidence.

This is the gate between scraper evidence and DB writes. It groups candidate
facts from evidence_ledger.json, asks a local/cloud model to arbitrate identity
and value quality, then annotates ledger records with sentry_status. The ledger
applier only writes records marked sentry_status=approved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from evidence_ledger import apply as apply_ledger
from evidence_ledger import db_field_empty, fetch_db_state, load_ledger, save_ledger, verify


AUDIT_DIR = Path(__file__).resolve().parent
SENTRY_LOG_PATH = AUDIT_DIR / "ai_enrich_sentry_log.jsonl"
DEFAULT_OLLAMA_HOST = "http://100.99.89.118:11434"
DEFAULT_MODEL = os.getenv("AI_SENTRY_MODEL", "qwen2.5:14b")

FIELD_VALUE_LIMITS = {
    "effects": 500,
    "description": 800,
    "packing": 40,
    "shot_count": 20,
    "duration_seconds": 20,
}

BAD_VALUE_PATTERNS = [
    re.compile(r"<[^>]+>"),
    re.compile(r"\bfacebook\.com/plugins\b", re.I),
    re.compile(r"\b(add to cart|home page|privacy policy|terms of service)\b", re.I),
    re.compile(r"^effects?$", re.I),
    re.compile(r"^colors?$", re.I),
    re.compile(r"^performance$", re.I),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def norm_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def value_is_structurally_bad(field: str, value: Any) -> str | None:
    text = norm_text(value, FIELD_VALUE_LIMITS.get(field, 500))
    if not text:
        return "empty value"
    if field in {"shot_count", "duration_seconds"}:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return "not an integer"
        if parsed <= 0:
            return "non-positive integer"
        if field == "shot_count" and parsed >= 2000:
            return "implausible shot count"
        if field == "duration_seconds" and parsed > 600:
            return "implausible duration"
    if field == "packing" and not re.fullmatch(r"\d+/\d+", text):
        return "packing is not N/N"
    if field in {"effects", "description"}:
        for pattern in BAD_VALUE_PATTERNS:
            if pattern.search(text):
                return "junk/html/placeholder text"
    return None


def candidate_groups(ledger: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    db = fetch_db_state()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, rec in enumerate(ledger):
        if rec.get("status") in {"applied", "rejected"}:
            continue
        if rec.get("sentry_status") in {"approved", "rejected"}:
            continue
        item = str(rec.get("item_number") or "")
        field = str(rec.get("field") or "")
        if not item or not field:
            continue
        cur = db.get(item)
        if not cur or not db_field_empty(cur.get(field)):
            continue
        rec["_ledger_index"] = index
        grouped[(item, field)].append(rec)

    out: list[dict[str, Any]] = []
    for (item, field), records in grouped.items():
        first = records[0]
        candidates = []
        for rec in records:
            reason = value_is_structurally_bad(field, rec.get("value"))
            candidates.append(
                {
                    "ledger_index": rec["_ledger_index"],
                    "value": rec.get("value"),
                    "source": rec.get("source", ""),
                    "url": rec.get("url", ""),
                    "confidence": rec.get("confidence", 0),
                    "identity_check": rec.get("identity_check", ""),
                    "status": rec.get("status", "pending"),
                    "quick_reject_reason": reason,
                }
            )
        out.append(
            {
                "item_number": item,
                "name": first.get("name", ""),
                "field": field,
                "candidates": candidates,
            }
        )
    return out[:limit] if limit else out


def ollama_json(prompt: str, model: str, host: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }
    req = Request(
        host.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=180) as resp:
        raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = raw.get("response", "") if isinstance(raw, dict) else ""
    return parse_jsonish(text)


def claude_json(prompt: str) -> dict[str, Any]:
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or f"claude exited {result.returncode}")
    return parse_jsonish(result.stdout)


def parse_jsonish(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model did not return JSON")
    parsed = json.loads(match.group(0))
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def prompt_for_group(group: dict[str, Any]) -> str:
    payload = {
        "product": {
            "item_number": group["item_number"],
            "name": group["name"],
        },
        "field": group["field"],
        "candidates": [
            {
                "index": i,
                "value": norm_text(candidate["value"], FIELD_VALUE_LIMITS.get(group["field"], 500)),
                "source": candidate["source"],
                "url": candidate["url"],
                "confidence": candidate["confidence"],
                "identity_check": candidate["identity_check"],
                "quick_reject_reason": candidate["quick_reject_reason"],
            }
            for i, candidate in enumerate(group["candidates"])
        ],
    }
    return (
        "You are the safety sentry for a fireworks-store product database. "
        "Approve exactly one candidate only if it is clearly information about the exact product. "
        "Reject HTML snippets, generic web page text, social embeds, placeholder labels, unrelated part numbers, "
        "weak name collisions, and anything not specific to this consumer fireworks item. "
        "If unsure, approve false. Return JSON only with keys: "
        "approved (boolean), candidate_index (integer or null), reason (short string).\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def dry_decision(group: dict[str, Any]) -> dict[str, Any]:
    for index, candidate in enumerate(group["candidates"]):
        if candidate["quick_reject_reason"]:
            continue
        if candidate["status"] == "verified":
            return {
                "approved": False,
                "candidate_index": None,
                "reason": "dry-run backend does not approve writes",
            }
    return {"approved": False, "candidate_index": None, "reason": "no structurally clean verified candidate"}


def decide(group: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if all(candidate["quick_reject_reason"] for candidate in group["candidates"]):
        return {"approved": False, "candidate_index": None, "reason": "all candidates failed deterministic checks"}
    prompt = prompt_for_group(group)
    if args.backend == "dry-run":
        return dry_decision(group)
    if args.backend == "ollama":
        return ollama_json(prompt, args.model, args.ollama_host)
    if args.backend == "claude-cli":
        return claude_json(prompt)
    raise ValueError(f"unsupported backend: {args.backend}")


def apply_decision(ledger: list[dict[str, Any]], group: dict[str, Any], decision: dict[str, Any], model_label: str) -> None:
    approved = bool(decision.get("approved"))
    try:
        chosen = int(decision.get("candidate_index"))
    except (TypeError, ValueError):
        chosen = None
    reason = norm_text(decision.get("reason"), 300)
    for index, candidate in enumerate(group["candidates"]):
        rec = ledger[candidate["ledger_index"]]
        rec["sentry_at"] = now_iso()
        rec["sentry_model"] = model_label
        rec["sentry_reason"] = reason
        if approved and index == chosen:
            rec["sentry_status"] = "approved"
        else:
            rec["sentry_status"] = "rejected"
            if candidate["quick_reject_reason"]:
                rec["status"] = "rejected"
                rec["rejected_reason"] = candidate["quick_reject_reason"]


def run_once(args: argparse.Namespace) -> int:
    ledger = verify(load_ledger())
    groups = candidate_groups(ledger, args.limit)
    model_label = args.backend if args.backend != "ollama" else f"ollama:{args.model}"
    reviewed = 0
    approved = 0
    for group in groups:
        try:
            decision = decide(group, args)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            decision = {"approved": False, "candidate_index": None, "reason": f"sentry error: {exc}"}
        apply_decision(ledger, group, decision, model_label)
        reviewed += 1
        if decision.get("approved"):
            approved += 1
        append_jsonl(
            SENTRY_LOG_PATH,
            {
                "reviewed_at": now_iso(),
                "product": {"item_number": group["item_number"], "name": group["name"]},
                "field": group["field"],
                "backend": args.backend,
                "model": args.model if args.backend == "ollama" else args.backend,
                "decision": decision,
            },
        )
        print(
            f"SENTRY {group['item_number']} {group['field']}: "
            f"{'APPROVE' if decision.get('approved') else 'reject'} - {norm_text(decision.get('reason'), 120)}"
        )
        time.sleep(max(0.0, args.sleep))
    save_ledger(ledger)
    if args.apply:
        apply_ledger(verify(load_ledger()))
    print(f"reviewed={reviewed} approved={approved}")
    return reviewed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI sentry gate for enrichment evidence")
    parser.add_argument("--backend", choices=("ollama", "claude-cli", "dry-run"), default="ollama")
    parser.add_argument("--ollama-host", default=os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--apply", action="store_true", help="apply AI-approved verified facts after review")
    parser.add_argument("--watch", action="store_true", help="keep reviewing new evidence until stopped")
    parser.add_argument("--watch-sleep", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    while True:
        reviewed = run_once(args)
        if not args.watch:
            break
        time.sleep(max(1.0, args.watch_sleep if reviewed == 0 else args.sleep))


if __name__ == "__main__":
    main()
