"""
Merge scraped gotfireworks.com No Name/RM data (gotfireworks_scraped.json) into the
live FIMS products table, matched by SKU == products.item_number.

Non-destructive: only fills fields that are currently NULL/empty on the matching
product (shot_count, duration_seconds, description, brand). Case packing/sales-per-case
info is appended to notes (products has no packing column — case pack detail belongs
in the separate case_packs table, out of scope for this merge). Never overwrites a
value a human (or another import) already set.

For SKUs with no matching product yet, inserts a new product row (brand resolved
by name, category left null — gotfireworks.com's "More Information" table has no
category field).

Run:
    python scripts/merge_gotfireworks_noname.py
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_scraped.json"


def normalize_sku(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def get_or_create_brand(cur, name: str | None) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    cur.execute("SELECT id FROM product_brands WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO product_brands (name) VALUES (%s) RETURNING id",
        (name,),
    )
    return cur.fetchone()[0]


def main() -> None:
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"Scraped JSON not found: {JSON_PATH}. Run scrape_gotfireworks_noname_links.py first.")

    scraped = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(scraped)} scraped gotfireworks products")

    updated = 0
    inserted = 0
    skipped_no_sku = 0
    no_change = 0

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for item in scraped:
                sku = normalize_sku(item.get("sku"))
                if not sku:
                    skipped_no_sku += 1
                    continue

                cur.execute(
                    """
                    SELECT id, shot_count, duration_seconds, description, notes, brand_id
                    FROM products
                    WHERE item_number = %s
                    """,
                    (sku,),
                )
                row = cur.fetchone()

                brand_id = get_or_create_brand(cur, item.get("brand"))

                pack_note = None
                if item.get("case_packing") or item.get("sales_per_case"):
                    pack_note = (
                        f"GotFireworks case packing: {item.get('case_packing') or '?'}"
                        f" (sales per case: {item.get('sales_per_case') or '?'})"
                    )

                if row:
                    product_id, shot_count, duration_seconds, description, notes, existing_brand_id = row
                    sets = []
                    params = []

                    if shot_count is None and item.get("shot_count") is not None:
                        sets.append("shot_count = %s")
                        params.append(item["shot_count"])
                    if duration_seconds is None and item.get("duration_seconds") is not None:
                        sets.append("duration_seconds = %s")
                        params.append(item["duration_seconds"])
                    if not description and item.get("description"):
                        sets.append("description = %s")
                        params.append(item["description"])
                    if existing_brand_id is None and brand_id is not None:
                        sets.append("brand_id = %s")
                        params.append(brand_id)
                    if pack_note and (not notes or pack_note not in notes):
                        new_notes = (notes.strip() + "\n\n" if notes and notes.strip() else "") + pack_note
                        sets.append("notes = %s")
                        params.append(new_notes)

                    if sets:
                        sets.append("updated_at = now()")
                        params.append(product_id)
                        cur.execute(
                            f"UPDATE products SET {', '.join(sets)} WHERE id = %s",
                            params,
                        )
                        updated += 1
                    else:
                        no_change += 1
                else:
                    name = item.get("product_catalog_name") or sku
                    new_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO products (
                            id, name, item_number, description, notes,
                            shot_count, duration_seconds, brand_id,
                            is_active, in_store, no_video_confirmed,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            true, false, false,
                            now(), now()
                        )
                        """,
                        (
                            new_id,
                            name,
                            sku,
                            item.get("description"),
                            pack_note,
                            item.get("shot_count"),
                            item.get("duration_seconds"),
                            brand_id,
                        ),
                    )
                    inserted += 1

        conn.commit()

    print(f"Updated (gap-filled): {updated}")
    print(f"Inserted (new products): {inserted}")
    print(f"Already complete, no change needed: {no_change}")
    print(f"Skipped (no SKU in scraped data): {skipped_no_sku}")


if __name__ == "__main__":
    main()
