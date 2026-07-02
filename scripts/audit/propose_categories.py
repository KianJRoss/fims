#!/usr/bin/env python3
"""Propose category_id for in-store products that have none (report-first).

Category in FIMS is a semantic/format judgement (e.g. "200 Gram Cakes" vs
"500 Gram Cakes" vs "Fountains"), not derivable from shot/packing numbers alone.
The reliable signal is the source's own form+gram wording. This tool classifies
each uncategorised in-store product from the strongest available signal:

  1. No Name retailer page URL slug already captured in the evidence ledger
     (e.g. ".../slice-of-pie-16-shot-200-gram-multi-shot-aerial-...") -> gram+form
     with exact-SKU identity (the product was matched by SKU when scraped).
  2. The product's own name + description + packing keywords (fallback).

It writes a Markdown + JSON report only. Nothing is written to the DB; apply is a
separate, reviewed step. Ambiguous cases are flagged rather than guessed.

Usage:
  python scripts/audit/propose_categories.py            # report all uncategorised in-store
  python scripts/audit/propose_categories.py --all      # include non-in-store too
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import psycopg

AUDIT_DIR = Path(__file__).resolve().parent
LEDGER_PATH = AUDIT_DIR / "evidence_ledger.json"
REPORT_JSON = AUDIT_DIR / "category_proposals.json"
REPORT_MD = AUDIT_DIR / "category_proposals.md"
DSN = "postgresql://fims:fims@100.73.208.99:5432/fims"

# FIMS category names -> id (from product_categories). Resolved live at runtime,
# but kept here as the canonical target set the classifier maps onto.
TARGET_NAMES = (
    "200 Gram Cakes", "500 Gram Cakes", "3-Inch 500 Gram Cakes", "500 Gram Fountains",
    "Cakes", "Z Cakes", "Fountains", "Artillery Shells", "Roman Candles", "Rockets",
    "Missiles", "Saturn Missiles", "Firecrackers", "Sparklers", "Smoke", "Novelties",
    "Parachutes", "Assortments", "Show To Go Cartons", "Mortars", "Misc",
)


def classify(slug: str, name: str, desc: str, packing: str) -> tuple[str | None, float, str]:
    """Return (category_name, confidence, reason). None if too ambiguous to propose."""
    hay = " ".join(x for x in (slug, name, desc, packing) if x).lower()
    gram = None
    m = re.search(r"(\d{2,4})[\s-]*gram", hay)  # matches "200 gram" and URL "200-gram"
    if m:
        gram = int(m.group(1))

    # Strong form keywords first (form wins over gram).
    if re.search(r"festival ball|reloadable|canister shell|cannister shell|artillery|\bshell", hay):
        return "Artillery Shells", 0.9, "form: artillery/shell"
    if re.search(r"roman candle", hay):
        return "Roman Candles", 0.9, "form: roman candle"
    if re.search(r"saturn missile", hay):
        return "Saturn Missiles", 0.9, "form: saturn missile"
    if re.search(r"\bmissile", hay):
        return "Missiles", 0.85, "form: missile"
    if re.search(r"bottle rocket|\brocket", hay):
        return "Rockets", 0.85, "form: rocket"
    if re.search(r"firecracker", hay):
        return "Firecrackers", 0.9, "form: firecracker"
    if re.search(r"sparkler|morning glory", hay):
        return "Sparklers", 0.9, "form: sparkler"
    # \bsmoke\b avoids matching product names like "SMOKED" (a 200g aerial cake).
    if re.search(r"smoke ball|color smoke|\bsmoke\b(?!d)", hay):
        return "Smoke", 0.85, "form: smoke"
    if re.search(r"parachute", hay):
        return "Parachutes", 0.9, "form: parachute"
    if re.search(r"\bsnake|spinner|wing item|ground bloom|novelty|novelties|tank\b", hay):
        return "Novelties", 0.75, "form: novelty"
    if re.search(r"fountain", hay):
        if gram and gram >= 400:
            return "500 Gram Fountains", 0.85, "form: fountain + >=400g"
        return "Fountains", 0.8, "form: fountain"
    if re.search(r"assortment|family pack|\bassorted\b", hay):
        return "Assortments", 0.7, "form: assortment"

    # Cake-type (multi-shot aerial / finale / cake) routed by gram size.
    cakey = re.search(r"multi[\s-]?shot|aerial|finale|\bcake\b|\bshot", hay)
    if cakey:
        if gram is not None:
            if gram <= 250:
                return "200 Gram Cakes", 0.85, f"cake + {gram}g"
            if 250 < gram <= 600:
                return "500 Gram Cakes", 0.85, f"cake + {gram}g"
            if gram > 600:
                return "Cakes", 0.6, f"cake + {gram}g (>500g, generic)"
        # cake form but no gram size -> can't split 200 vs 500
        return None, 0.0, "cake form but no gram size (ambiguous 200 vs 500)"

    return None, 0.0, "no decisive form/gram signal"


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose categories (report only by default)")
    parser.add_argument("--all", action="store_true", help="include non-in-store products too")
    parser.add_argument("--apply", action="store_true", help="write proposals to DB (empty category only)")
    parser.add_argument("--exact-only", action="store_true",
                        help="with --apply, only write exact-SKU (retailer URL) proposals")
    parser.add_argument("--min-confidence", type=float, default=0.85,
                        help="with --apply, minimum confidence to write (default 0.85)")
    parser.add_argument("--only-sku", default="", help="comma-separated SKUs to restrict --apply")
    args = parser.parse_args()

    # Candidate retailer URLs per SKU from the ledger. No Name "assorted" pages
    # list several SKUs, so a SKU can match both its own page and an assortment
    # parent; pick the URL whose slug best overlaps the product name to avoid
    # inheriting the assortment's category.
    urls_by_sku: dict[str, list[str]] = {}
    if LEDGER_PATH.exists():
        led = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        for rec in led:
            sku = str(rec.get("item_number") or "").strip()
            url = str(rec.get("url") or "")
            if sku and url and "nonamefireworks" in url:
                urls_by_sku.setdefault(sku, [])
                if url not in urls_by_sku[sku]:
                    urls_by_sku[sku].append(url)

    def best_slug(sku: str, name: str) -> str:
        cands = urls_by_sku.get(sku, [])
        if not cands:
            return ""
        if len(cands) == 1:
            return cands[0]
        name_tokens = set(re.findall(r"[a-z0-9]+", (name or "").lower()))
        # Penalise generic assortment slugs unless the name itself is an assortment.
        def score(u: str) -> tuple[int, int]:
            slug_tokens = set(re.findall(r"[a-z0-9]+", u.lower().split("/")[-1]))
            overlap = len(name_tokens & slug_tokens)
            assorted = -1 if ("assorted" in slug_tokens and "assorted" not in name_tokens) else 0
            return (overlap, assorted)
        return max(cands, key=score)

    with psycopg.connect(DSN) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SELECT name, id FROM product_categories")
            name_to_id = {n: i for n, i in cur.fetchall()}
            where = "category_id IS NULL" + ("" if args.all else " AND in_store=true")
            cur.execute(
                f"SELECT id, item_number, name, COALESCE(description,''), COALESCE(packing,'') "
                f"FROM products WHERE {where} ORDER BY in_store DESC, item_number"
            )
            rows = cur.fetchall()

    proposals: list[dict[str, Any]] = []
    for pid, sku, name, desc, packing in rows:
        sku_s = str(sku or "").strip()
        slug = best_slug(sku_s, name or "")
        cat, conf, reason = classify(slug, name or "", desc, packing)
        proposals.append({
            "product_id": str(pid),
            "item_number": sku_s,
            "name": name,
            "proposed_category": cat,
            "category_id": name_to_id.get(cat) if cat else None,
            "confidence": conf,
            "reason": reason,
            "identity": "exact SKU (retailer URL)" if slug else "name/desc keywords",
            "signal_url": slug,
        })

    decided = [p for p in proposals if p["proposed_category"]]
    flagged = [p for p in proposals if not p["proposed_category"]]
    REPORT_JSON.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Category proposals ({len(proposals)} products, {len(decided)} decided, {len(flagged)} flagged)\n"]
    lines.append("## Decided (review before apply)\n")
    lines.append("| SKU | Name | -> Category | conf | identity | reason |")
    lines.append("|-----|------|-------------|------|----------|--------|")
    for p in sorted(decided, key=lambda x: (-x["confidence"], x["proposed_category"])):
        lines.append(f"| {p['item_number'] or '-'} | {p['name']} | {p['proposed_category']} "
                     f"| {p['confidence']:.2f} | {p['identity']} | {p['reason']} |")
    lines.append("\n## Flagged (no confident proposal — needs human/extra signal)\n")
    lines.append("| SKU | Name | reason |")
    lines.append("|-----|------|--------|")
    for p in flagged:
        lines.append(f"| {p['item_number'] or '-'} | {p['name']} | {p['reason']} |")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(proposals)} uncategorised products: {len(decided)} decided, {len(flagged)} flagged")
    print(f"report -> {REPORT_MD}")

    if args.apply:
        only = {s.strip() for s in args.only_sku.split(",") if s.strip()}
        to_write = [
            p for p in decided
            if p["category_id"] is not None
            and p["confidence"] >= args.min_confidence
            and (not args.exact_only or p["signal_url"])
            and (not only or p["item_number"] in only)
        ]
        if not to_write:
            print("nothing matches the --apply filters")
            return 0
        backup_path = AUDIT_DIR / "category_apply_backup.json"
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                # Re-check the field is still empty (never overwrite) and back up.
                backup = []
                written = 0
                for p in to_write:
                    cur.execute("SELECT category_id FROM products WHERE id=%s", (p["product_id"],))
                    row = cur.fetchone()
                    if not row or row[0] is not None:
                        continue  # categorised since report; skip
                    backup.append({"product_id": p["product_id"], "item_number": p["item_number"],
                                   "old_category_id": None, "new_category_id": p["category_id"],
                                   "category": p["proposed_category"]})
                    cur.execute("UPDATE products SET category_id=%s WHERE id=%s",
                                (p["category_id"], p["product_id"]))
                    written += 1
                    print(f"  APPLY {p['item_number'] or p['product_id']} -> {p['proposed_category']} "
                          f"({p['confidence']:.2f}, {p['identity']})")
                backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
                conn.commit()
        print(f"applied {written} category writes (backup -> {backup_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
