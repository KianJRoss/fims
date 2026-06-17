#!/usr/bin/env python3
"""
Decode real barcodes from Jake's 2026 catalog page images and update the DB.

Match rule: barcode[7:11] (0-indexed, 4 chars) == item_number[-4:]
This works because Jake's UPC/EAN barcodes embed the last 4 digits of
the item number at that fixed position.

Scans every page, collects barcodes, matches to products by page+last4,
then rewrites product_barcodes with the correct real values.

Usage:
    python scripts/fix_barcodes_from_images.py [--dry-run] [--pages 1-177]
    python scripts/fix_barcodes_from_images.py --dry-run --pages 20-30
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    from PIL import Image
except ImportError:
    sys.exit("pip install pyzbar pillow")

PAGES_DIR = Path(__file__).parent / "catalogs" / "jakes" / "2026" / "pages"

PI_HOST = "krioasns@192.168.0.105"
PSQL = "sudo docker exec fims-postgres-1 psql -U fims -d fims"


# ── DB helpers via SSH ────────────────────────────────────────────────────────

def psql_query(sql: str) -> list[dict]:
    """Run a read-only SQL query on the Pi and return rows as dicts."""
    cmd = f'{PSQL} -t -A -F"|" -c "{sql}"'
    result = subprocess.run(
        ["ssh", PI_HOST, cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql_query failed (rc={result.returncode}):\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
    rows = []
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return rows
    # First line is header when using -A without -t but with -F, skip if no header
    # With -t flag (tuples only) there's no header — just data rows
    for line in lines:
        parts = line.split("|")
        rows.append(parts)
    return rows


def load_products() -> list[dict]:
    """Load all Jake's products that have a catalog_page assigned."""
    sql = (
        "SELECT id, name, item_number, catalog_page "
        "FROM products "
        "WHERE catalog_page IS NOT NULL AND is_active = TRUE "
        "ORDER BY catalog_page, item_number"
    )
    rows = psql_query(sql)
    products = []
    for row in rows:
        if len(row) < 4:
            continue
        products.append({
            "id": row[0].strip(),
            "name": row[1].strip(),
            "item_number": row[2].strip(),
            "catalog_page": int(row[3].strip()),
        })
    return products


def apply_updates(updates: list[tuple[str, str]], dry_run: bool) -> None:
    """
    updates: list of (product_id, barcode)
    Writes SQL to a temp file on the Pi then executes it via psql.
    """
    if not updates:
        print("Nothing to update.")
        return

    lines = ["BEGIN;"]
    for product_id, barcode in updates:
        lines.append(
            f"DELETE FROM product_barcodes WHERE product_id = '{product_id}';"
        )
        lines.append(
            f"INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary) "
            f"VALUES ('{product_id}', '{barcode}', 'EAN', TRUE) ON CONFLICT DO NOTHING;"
        )
    lines.append("COMMIT;")
    sql_block = "\n".join(lines)

    if dry_run:
        print(f"\n[DRY RUN] {len(updates)} updates — first 5:\n")
        for pid, bc in updates[:5]:
            print(f"  {pid}  ->  {bc}")
        return

    # Pipe SQL via stdin directly into psql inside the Docker container
    exec_result = subprocess.run(
        ["ssh", PI_HOST, "sudo docker exec -i fims-postgres-1 psql -U fims -d fims --set ON_ERROR_STOP=1"],
        input=sql_block,
        capture_output=True,
        text=True,
    )

    if exec_result.stdout:
        print(exec_result.stdout)
    if exec_result.stderr:
        print("STDERR:", exec_result.stderr)
    if exec_result.returncode != 0:
        print(f"ERROR: psql exited with code {exec_result.returncode}")
    else:
        print("Done.")


# ── Barcode scanning ──────────────────────────────────────────────────────────

def decode_page(page_num: int) -> list[tuple[str, int, int]]:
    """Return list of (barcode_str, x, y) sorted top-to-bottom then left-to-right."""
    path = PAGES_DIR / f"page_{page_num:03d}.jpg"
    if not path.exists():
        return []
    img = Image.open(path)
    results = pyzbar_decode(img)
    out = []
    for r in results:
        data = r.data.decode()
        cx = r.rect.left + r.rect.width // 2
        cy = r.rect.top + r.rect.height // 2
        out.append((data, cx, cy))
    # Sort top-to-bottom, left-to-right (row buckets of ~200px)
    out.sort(key=lambda t: (t[2] // 200, t[1]))
    return out


def last4(item_number: str) -> str:
    return item_number[-4:]


def barcode_key(barcode: str) -> str:
    """Extract the 4-digit item-number fragment from a barcode (positions 8-11, 1-indexed)."""
    return barcode[7:11] if len(barcode) >= 11 else ""


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool, page_range: tuple[int, int]) -> None:
    print("Loading products from DB...")
    products = load_products()
    print(f"  {len(products)} products with catalog_page")

    # Group products by page
    by_page: dict[int, list[dict]] = defaultdict(list)
    for p in products:
        by_page[p["catalog_page"]].append(p)

    # Build lookup: (page, last4) → product
    page_last4: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for p in products:
        key = (p["catalog_page"], last4(p["item_number"]))
        page_last4[key].append(p)

    updates: list[tuple[str, str]] = []
    no_match: list[tuple[int, str]] = []
    ambiguous: list[tuple[int, str, list[str]]] = []

    start, end = page_range
    pages_to_scan = sorted(k for k in by_page if start <= k <= end)

    print(f"Scanning {len(pages_to_scan)} pages ({start}–{end})...\n")

    already_matched: set[str] = set()  # product_ids matched across all pages

    for page_num in pages_to_scan:
        decoded = decode_page(page_num)
        if not decoded:
            print(f"  page {page_num:3d}: no barcodes decoded")
            continue

        # Filter to digit-only barcodes (skip QR/URL)
        barcodes = [(bc, x, y) for bc, x, y in decoded if bc.isdigit() and len(bc) >= 11]
        if not barcodes:
            continue

        page_products = [p for p in by_page.get(page_num, []) if p["id"] not in already_matched]
        if not page_products:
            continue

        matched_on_page: dict[str, str] = {}  # product_id -> barcode

        # Pass 1: last-4 rule
        for bc, x, y in barcodes:
            key4 = barcode_key(bc)
            candidates = [p for p in page_products if last4(p["item_number"]) == key4]
            if len(candidates) == 1:
                p = candidates[0]
                if p["id"] not in matched_on_page:
                    matched_on_page[p["id"]] = bc

        # Pass 2: position-based for leftovers
        unmatched_barcodes = [(bc, x, y) for bc, x, y in barcodes if not any(
            matched_on_page.get(p["id"]) == bc for p in page_products
        )]
        unmatched_products = [p for p in page_products if p["id"] not in matched_on_page]

        if len(unmatched_barcodes) == len(unmatched_products) and unmatched_products:
            # Same count — match by position order
            for (bc, x, y), p in zip(unmatched_barcodes, unmatched_products):
                matched_on_page[p["id"]] = bc

        # Record results
        for p in page_products:
            bc = matched_on_page.get(p["id"])
            if bc:
                already_matched.add(p["id"])
                print(
                    f"  page {page_num:3d}: {p['item_number']:10s}  "
                    f"{p['name'][:32]:32s}  ->  {bc}"
                )
                updates.append((p["id"], bc))
            else:
                no_match.append((page_num, p["item_number"]))

    print(f"\n{'='*60}")
    print(f"Matched:   {len(updates)}")
    print(f"No match:  {len(no_match)}")
    print(f"Ambiguous: {len(ambiguous)}")

    if no_match:
        print("\nNo match (page, item_number):")
        for page_num, item_number in no_match[:20]:
            print(f"  page {page_num}: {item_number}")

    if ambiguous:
        print("\nAmbiguous (multiple products share last-4 on same page):")
        for page_num, bc, names in ambiguous[:10]:
            print(f"  page {page_num}: {bc}  candidates={names}")

    print()
    apply_updates(updates, dry_run)


def parse_range(s: str) -> tuple[int, int]:
    if "-" in s:
        a, b = s.split("-", 1)
        return int(a), int(b)
    n = int(s)
    return n, n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pages", default="1-177")
    args = parser.parse_args()

    page_range = parse_range(args.pages)
    print(f"{'DRY RUN  ' if args.dry_run else 'LIVE RUN '}  pages {page_range[0]}–{page_range[1]}\n")
    run(args.dry_run, page_range)


if __name__ == "__main__":
    main()
