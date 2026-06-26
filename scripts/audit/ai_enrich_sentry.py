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
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

from evidence_ledger import DSN
from evidence_ledger import apply as apply_ledger
from evidence_ledger import db_field_empty, fetch_db_state, load_ledger, save_ledger, verify

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


AUDIT_DIR = Path(__file__).resolve().parent
SENTRY_LOG_PATH = AUDIT_DIR / "ai_enrich_sentry_log.jsonl"
DEFAULT_OLLAMA_HOST = "http://100.99.89.118:11434"
DEFAULT_MODEL = os.getenv("AI_SENTRY_MODEL", "qwen2.5:14b")
DEFAULT_MEDIA_ROOT = REPO_ROOT / "media"

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

EFFECT_SIGNAL_RE = re.compile(
    r"\b("
    r"brocade|chrysanthemum|chrys\.?|crackle|crackling|dahlia|glitter|strobe|willow|"
    r"pearl|pearls|palm|peony|comet|tail|tails|mine|mines|bouquet|wave|spinner|"
    r"whistle|whistles|report|reports|titanium|dragon|crossette|horsetail|fish|"
    r"red|green|blue|purple|yellow|gold|silver|white|orange|lemon"
    r")\b",
    re.I,
)

EFFECT_JUNK_RE = re.compile(
    r"\b("
    r"effects?\s+holders?|holder|add to cart|quick fuse|privacy|shipping|loyalty|"
    r"contains a bundle|ultimate .* experience|facebook|iframe|plugin"
    r")\b",
    re.I,
)


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
    if field == "effects":
        if EFFECT_JUNK_RE.search(text):
            return "generic/marketing text, not product effects"
        if not EFFECT_SIGNAL_RE.search(text):
            return "no recognizable fireworks effect/color terms"
        words = re.findall(r"[A-Za-z0-9]+", text)
        if len(words) > 28 and text.count(",") < 2:
            return "description-like prose, not effects list"
    return None


def normalize_for_compare(field: str, value: Any) -> str:
    text = norm_text(value, FIELD_VALUE_LIMITS.get(field, 800)).lower()
    if field in {"shot_count", "duration_seconds"}:
        try:
            return str(int(str(value).strip()))
        except (TypeError, ValueError):
            return text
    if field == "packing":
        match = re.search(r"\d+\s*/\s*\d+", text)
        return match.group(0).replace(" ", "") if match else text
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def values_equivalent(field: str, left: Any, right: Any) -> bool:
    return bool(normalize_for_compare(field, left)) and normalize_for_compare(field, left) == normalize_for_compare(field, right)


def candidate_groups(
    ledger: list[dict[str, Any]],
    limit: int | None,
    only_skus: set[str] | None = None,
    only_product_ids: set[str] | None = None,
    include_filled: bool = False,
) -> list[dict[str, Any]]:
    db = fetch_db_state()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    current_values: dict[tuple[str, str], Any] = {}
    for index, rec in enumerate(ledger):
        if rec.get("status") in {"applied", "rejected"}:
            continue
        if rec.get("sentry_status") in {
            "approved",
            "rejected",
            "replace_recommended",
            "merge_recommended",
            "keep_current",
        }:
            continue
        item = str(rec.get("item_number") or "")
        product_id = str(rec.get("product_id") or "")
        product_key = item or product_id
        field = str(rec.get("field") or "")
        if not product_key or not field:
            continue
        if only_skus or only_product_ids:
            sku_match = bool(item and only_skus and item.upper() in only_skus)
            product_id_match = bool(product_id and only_product_ids and product_id in only_product_ids)
            if not (sku_match or product_id_match):
                continue
        cur = db.get(product_key)
        if not cur:
            continue
        current_value = cur.get(field)
        if not include_filled and not db_field_empty(current_value):
            continue
        if include_filled and db_field_empty(current_value):
            continue
        current_values[(product_key, field)] = current_value
        grouped[(product_key, field)].append({**rec, "_ledger_index": index})

    out: list[dict[str, Any]] = []
    for (product_key, field), records in grouped.items():
        first = records[0]
        item = str(first.get("item_number") or "")
        product_id = str(first.get("product_id") or "")
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
                "product_id": product_id,
                "product_key": product_key,
                "name": first.get("name", ""),
                "field": field,
                "current_value": current_values.get((product_key, field)),
                "current_is_empty": db_field_empty(current_values.get((product_key, field))),
                "candidates": candidates,
            }
        )
    return out[:limit] if limit else out


def fetch_product_context(product_keys: set[str]) -> dict[str, dict[str, Any]]:
    if not product_keys:
        return {}
    keys = list(product_keys)
    with psycopg.connect(DSN) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id::text,
                    p.item_number::text,
                    p.name,
                    COALESCE(b.name, '') AS brand_name,
                    COALESCE(c.name, '') AS category_name,
                    p.image_path
                FROM products p
                LEFT JOIN product_brands b ON b.id = p.brand_id
                LEFT JOIN product_categories c ON c.id = p.category_id
                WHERE p.item_number::text = ANY(%s) OR p.id::text = ANY(%s)
                """,
                (keys, keys),
            )
            out: dict[str, dict[str, Any]] = {}
            for row in cur.fetchall():
                context = {
                    "product_id": row[0],
                    "item_number": row[1],
                    "name": row[2],
                    "brand_name": row[3],
                    "category_name": row[4],
                    "image_path": row[5],
                }
                if row[0]:
                    out[str(row[0])] = context
                if row[1]:
                    out[str(row[1])] = context
            return out


def add_context(groups: list[dict[str, Any]], args: argparse.Namespace) -> None:
    context = fetch_product_context({group["product_key"] for group in groups})
    for group in groups:
        group["db_context"] = context.get(group["product_key"], {})
        if args.vision:
            group["vision_context"] = analyze_product_image(group["db_context"], args)


def analyze_product_image(db_context: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    image_path = db_context.get("image_path")
    if not image_path:
        return None
    full_path = Path(args.media_root) / str(image_path)
    if not full_path.is_file() or full_path.stat().st_size <= 0:
        return {"error": "image missing", "image_path": str(image_path)}
    try:
        from scripts.vision.pipeline import analyze_image

        analysis = analyze_image(full_path, steps=tuple(args.vision_steps.split(",")))
    except Exception as exc:  # noqa: BLE001 - sentry context should not abort review
        return {"error": str(exc), "image_path": str(image_path)}
    return {
        "image_path": str(image_path),
        "ocr_text": " | ".join(analysis.texts)[:600],
        "codes": analysis.codes[:10],
        "vlm": analysis.vlm,
        "errors": analysis.meta.get("errors", {}),
    }


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
            "product_id": group.get("product_id", ""),
            "item_number": group["item_number"],
            "name": group["name"],
            "brand": group.get("db_context", {}).get("brand_name", ""),
            "category": group.get("db_context", {}).get("category_name", ""),
        },
        "field": group["field"],
        "current_database_value": group.get("current_value"),
        "current_is_empty": group.get("current_is_empty", True),
        "vision_context": group.get("vision_context"),
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
        "If current_database_value is not empty, compare the candidate to the existing value. "
        "Use recommended_action='keep_current' when the existing value is better or equally good, "
        "recommended_action='replace' when the candidate is clearly better/correcter, and "
        "recommended_action='merge' when the candidate adds useful missing detail without invalidating the current value. "
        "Exact SKU/barcode identity is strongest. When a SKU is missing or questionable, a candidate may still be "
        "approved only if the evidence shows strong product identity from product name + brand + at least one known "
        "fact such as shot count, duration, category, effects, package text, OCR, or barcode context. "
        "Reject HTML snippets, generic web page text, social embeds, placeholder labels, unrelated part numbers, "
        "weak name collisions, and anything not specific to this consumer fireworks item. "
        "For field=effects, approve only actual visual/audio effect content such as colors, mines, tails, "
        "willows, strobes, brocades, crackle, palms, peonies, comets, reports, whistles, etc. "
        "Reject marketing descriptions, fuse/package descriptions, and generic labels like Effects Holders. "
        "Use vision_context only as supporting identity evidence; do not invent missing facts from it. "
        "If unsure, approve false and recommended_action='reject'. Return JSON only with keys: "
        "approved (boolean), candidate_index (integer or null), recommended_action "
        "('fill_empty', 'replace', 'merge', 'keep_current', or 'reject'), reason (short string).\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def dry_decision(group: dict[str, Any]) -> dict[str, Any]:
    for index, candidate in enumerate(group["candidates"]):
        if candidate["quick_reject_reason"]:
            continue
        if not group.get("current_is_empty", True) and values_equivalent(
            group["field"], group.get("current_value"), candidate.get("value")
        ):
            return {
                "approved": False,
                "candidate_index": None,
                "recommended_action": "keep_current",
                "reason": "candidate matches current database value",
            }
        if candidate["status"] == "verified":
            return {
                "approved": False,
                "candidate_index": None,
                "recommended_action": "reject",
                "reason": "dry-run backend does not approve writes",
            }
    return {
        "approved": False,
        "candidate_index": None,
        "recommended_action": "reject",
        "reason": "no structurally clean verified candidate",
    }


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


def normalize_decision(group: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    approved = bool(decision.get("approved"))
    action = norm_text(decision.get("recommended_action"), 40).lower().replace("-", "_").replace(" ", "_")
    if action not in {"fill_empty", "replace", "merge", "keep_current", "reject"}:
        action = "fill_empty" if approved and group.get("current_is_empty", True) else "reject"
    try:
        chosen = int(decision.get("candidate_index"))
    except (TypeError, ValueError):
        chosen = None
    reason = norm_text(decision.get("reason"), 300)
    if approved and (chosen is None or chosen < 0 or chosen >= len(group["candidates"])):
        approved = False
        reason = "model approved without a valid candidate index"
    if approved:
        chosen_candidate = group["candidates"][chosen]
        if chosen_candidate["quick_reject_reason"]:
            approved = False
            reason = f"chosen candidate failed deterministic check: {chosen_candidate['quick_reject_reason']}"
        elif chosen_candidate.get("status") != "verified":
            approved = False
            reason = "chosen candidate is not ledger-verified yet"
        elif not re.search(
            r"\b(exact SKU|barcode|strong product identity)\b",
            str(chosen_candidate.get("identity_check", "")),
            re.I,
        ):
            approved = False
            reason = "chosen candidate lacks exact SKU/barcode or strong non-SKU identity"
        elif not group.get("current_is_empty", True) and values_equivalent(
            group["field"], group.get("current_value"), chosen_candidate.get("value")
        ):
            approved = False
            action = "keep_current"
            reason = "candidate matches current database value"
    if approved and not group.get("current_is_empty", True) and action == "fill_empty":
        action = "replace"
    if not approved and action not in {"keep_current", "reject"}:
        action = "reject"
    if approved and group.get("current_is_empty", True) and action in {"replace", "merge"}:
        action = "fill_empty"
    return {
        "approved": approved,
        "candidate_index": chosen if approved else None,
        "recommended_action": action,
        "reason": reason,
    }


def apply_decision(ledger: list[dict[str, Any]], group: dict[str, Any], decision: dict[str, Any], model_label: str) -> None:
    decision = normalize_decision(group, decision)
    approved = bool(decision.get("approved"))
    chosen = decision.get("candidate_index")
    reason = norm_text(decision.get("reason"), 300)
    for index, candidate in enumerate(group["candidates"]):
        rec = ledger[candidate["ledger_index"]]
        rec["sentry_at"] = now_iso()
        rec["sentry_model"] = model_label
        rec["sentry_reason"] = reason
        if not group.get("current_is_empty", True):
            rec["current_value"] = group.get("current_value")
        if approved and index == chosen:
            if not group.get("current_is_empty", True) and decision.get("recommended_action") == "replace":
                rec["sentry_status"] = "replace_recommended"
            elif not group.get("current_is_empty", True) and decision.get("recommended_action") == "merge":
                rec["sentry_status"] = "merge_recommended"
            elif not group.get("current_is_empty", True):
                rec["sentry_status"] = "keep_current"
            else:
                rec["sentry_status"] = "approved"
        else:
            if (
                decision.get("recommended_action") == "keep_current"
                and not group.get("current_is_empty", True)
                and values_equivalent(group["field"], group.get("current_value"), candidate.get("value"))
            ):
                rec["sentry_status"] = "keep_current"
            else:
                rec["sentry_status"] = "rejected"
            if candidate["quick_reject_reason"]:
                rec["status"] = "rejected"
                rec["rejected_reason"] = candidate["quick_reject_reason"]


def parse_csv(value: str, *, upper: bool = False) -> set[str] | None:
    parsed = {
        (part.strip().upper() if upper else part.strip())
        for part in value.split(",")
        if part.strip()
    }
    return parsed or None


def run_once(args: argparse.Namespace) -> int:
    ledger = verify(load_ledger(), save=not args.preview)
    groups = candidate_groups(
        ledger,
        args.limit,
        parse_csv(args.only_sku, upper=True),
        parse_csv(args.only_product_id),
        args.review_filled,
    )
    add_context(groups, args)
    model_label = args.backend if args.backend != "ollama" else f"ollama:{args.model}"
    reviewed = 0
    approved = 0
    for group in groups:
        try:
            decision = decide(group, args)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            decision = {"approved": False, "candidate_index": None, "reason": f"sentry error: {exc}"}
        decision = normalize_decision(group, decision)
        if not args.preview:
            apply_decision(ledger, group, decision, model_label)
        reviewed += 1
        if decision.get("approved"):
            approved += 1
        if not args.preview:
            append_jsonl(
                SENTRY_LOG_PATH,
                {
                    "reviewed_at": now_iso(),
                    "product": {
                        "product_id": group.get("product_id", ""),
                        "item_number": group["item_number"],
                        "name": group["name"],
                    },
                    "field": group["field"],
                    "current_value": group.get("current_value"),
                    "current_is_empty": group.get("current_is_empty", True),
                    "candidates": [
                        {
                            "value": candidate.get("value"),
                            "source": candidate.get("source", ""),
                            "url": candidate.get("url", ""),
                            "confidence": candidate.get("confidence", 0),
                            "identity_check": candidate.get("identity_check", ""),
                            "quick_reject_reason": candidate.get("quick_reject_reason"),
                            "ledger_index": candidate.get("ledger_index"),
                        }
                        for candidate in group["candidates"]
                    ],
                    "backend": args.backend,
                    "model": args.model if args.backend == "ollama" else args.backend,
                    "decision": decision,
                },
            )
        print(
            f"SENTRY {group.get('item_number') or group.get('product_id')} {group['field']}: "
            f"{'APPROVE' if decision.get('approved') else 'reject'} "
            f"[{decision.get('recommended_action', 'reject')}] - {norm_text(decision.get('reason'), 120)}"
        )
        time.sleep(max(0.0, args.sleep))
    if not args.preview:
        save_ledger(ledger)
    if args.apply and not args.preview:
        apply_ledger(verify(load_ledger()))
    print(f"reviewed={reviewed} approved={approved}")
    return reviewed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI sentry gate for enrichment evidence")
    parser.add_argument("--backend", choices=("ollama", "claude-cli", "dry-run"), default="ollama")
    parser.add_argument("--ollama-host", default=os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--only-sku", default="", help="comma-separated SKUs to review")
    parser.add_argument("--only-product-id", default="", help="comma-separated product UUIDs to review")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--vision", action="store_true", help="include local OCR/barcode/VLM product image context")
    parser.add_argument("--vision-steps", default="ocr,codes,vlm")
    parser.add_argument("--media-root", default=str(DEFAULT_MEDIA_ROOT))
    parser.add_argument("--apply", action="store_true", help="apply AI-approved verified facts after review")
    parser.add_argument(
        "--review-filled",
        action="store_true",
        help="review candidates against already-filled DB fields and log keep/replace/merge recommendations only",
    )
    parser.add_argument("--preview", action="store_true", help="print decisions without changing ledger or DB")
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
