"""
Import Jake's catalog into FIMS using the Issuu text layer (text_layer.json).
Categories assigned from Table of Contents page ranges.
Each page can have multiple products — parsed from raw_segments by splitting on SKU markers.

Usage:
  python importers/jakes.py [year]
"""
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DB_URL = "postgresql://fims:fims@localhost:5432/fims"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
BRAND_NAME = "World Class"

# Table of contents — (category_name, first_page, last_page)
SECTION_MAP = [
    ("Assortments",           2,   15),
    ("Artillery Shells",      16,  25),
    ("3-Inch 500 Gram Cakes", 26,  29),
    ("Z Cakes",               30,  35),
    ("500 Gram Cakes",        36,  66),
    ("Show To Go Cartons",    67,  70),
    ("200 Gram Cakes",        71,  96),
    ("Saturn Missiles",       97,  97),
    ("Fountains",             98,  104),
    ("Firecrackers",          105, 123),
    ("Smoke",                 124, 126),
    ("Novelties",             127, 129),
    ("Parachutes",            130, 139),
    ("Rockets & Missiles",    140, 141),
    ("Roman Candles",         142, 145),
    ("Sparklers",             146, 177),
]

_SKU_RE = re.compile(r"SKU[:\s]*(\d{5,10})", re.IGNORECASE)
_BARCODE_RE = re.compile(r"BARCODE[:\s]*(?:USA\s+)?(\d{8,14})")
_SHOTS_RE = re.compile(r"(\d+)\s*shots?", re.IGNORECASE)
_SHELLS_RE = re.compile(r"(\d+)\s*shells?", re.IGNORECASE)
_PACKING_RE = re.compile(r"PACKING[:\s]*([\d/]+)", re.IGNORECASE)

# Words that signal the product name ends and the description begins
_VERB_SPLIT = re.compile(
    r"\b(packs?|features?|delivers?|includes?|brings?|comes?|offers?|provides?|"
    r"shoots?|fires?|fills?|combines?|boasts?|showcases?|explodes?|launches?|"
    r"lights?|creates?|gives?|contains?|blends?)\b",
    re.IGNORECASE,
)
_SKIP_STARTS = re.compile(
    r"^(a |an |the |two |three |four |five |six |seven |eight |nine |ten |"
    r"\d+|large|small|medium|premium|massive|compact|huge|loaded|mid|full|"
    r"mixed|power|patriotic|huge|classic|ultimate|perfect|designed)",
    re.IGNORECASE,
)
_NON_NAME_CAPS = {
    "ASSORTMENTS", "ARTILLERY SHELLS", "3 INCH 500 GRAM CAKES", "Z CAKES",
    "500 GRAM CAKES", "SHOW TO GO CARTONS", "200 GRAM CAKES", "SATURN MISSILES",
    "SATURN MISSILE", "FOUNTAINS", "FIRECRACKERS", "SMOKE", "SMOKE GRENADES",
    "NOVELTIES", "PARACHUTES", "ROCKETS", "MISSILES", "ROCKETS MISSILES",
    "ROMAN CANDLES", "SPARKLERS", "SAFE & SANE ASSORTMENTS", "FAR EAST IMPORTS",
    "ALPHABETICAL INDEX", "PRE-MADE APPAREL", "CUSTOM APPAREL", "CUSTOM SIGNS",
    "NEW FOR 2026", "3 INCH 5 0 0 G RAM CAKES", "FOUNTAIS",
}


def category_for_page(page: int) -> str | None:
    for name, lo, hi in SECTION_MAP:
        if lo <= page <= hi:
            return name
    return None


def extract_name_from_description(desc: str | None) -> str | None:
    """Try to pull a product name from the first words of a description."""
    if not desc:
        return None
    # Strip leading "DESCRIPTION: " if present
    desc = re.sub(r"^DESCRIPTION:\s*", "", desc).strip()
    if _SKIP_STARTS.match(desc):
        return None
    m = _VERB_SPLIT.search(desc)
    if not m:
        return None
    candidate = desc[: m.start()].strip().rstrip(",").strip()
    words = candidate.split()
    if not words or len(words) > 5:
        return None
    # Reject if any word is lowercase (not a proper noun phrase)
    if any(w[0].islower() for w in words if w):
        return None
    return candidate or None


def parse_products_from_page(result: dict) -> list[dict]:
    """
    Split a page's raw_segments into per-product records.
    Returns a list of {item_number, barcode, shot_count, packing, description} dicts.
    """
    raw = result.get("raw_segments", [])
    if not raw:
        return []

    # Find all SKU positions in raw segments
    sku_positions: list[tuple[int, str]] = []
    for i, seg in enumerate(raw):
        m = _SKU_RE.search(seg)
        if m:
            # A single segment can contain multiple SKUs (e.g. "SKU:1001401 1001409")
            for sku_match in _SKU_RE.finditer(seg):
                sku_positions.append((i, sku_match.group(1)))

    if not sku_positions:
        return []

    products = []
    # Build per-product segment windows between consecutive SKUs
    for idx, (seg_pos, item_number) in enumerate(sku_positions):
        # Window: from this SKU's segment to just before the next SKU's segment
        if idx + 1 < len(sku_positions):
            next_seg_pos = sku_positions[idx + 1][0]
            window = raw[seg_pos: next_seg_pos]
        else:
            window = raw[seg_pos:]

        full_text = " ".join(window)

        # Barcode — take the FIRST barcode found in this window
        bc_m = _BARCODE_RE.search(full_text)
        barcode = bc_m.group(1) if bc_m else None

        # Shot count
        shots_m = _SHOTS_RE.search(full_text)
        shells_m = _SHELLS_RE.search(full_text)
        shot_count = int(shots_m.group(1)) if shots_m else (int(shells_m.group(1)) if shells_m else None)

        # Packing
        pack_m = _PACKING_RE.search(full_text)
        packing = pack_m.group(1) if pack_m else None

        # Description — find the segment starting with DESCRIPTION:
        description = None
        for seg in window:
            if seg.strip().upper().startswith("DESCRIPTION:"):
                description = seg.strip()
                break

        products.append({
            "item_number": item_number,
            "barcode": barcode,
            "shot_count": shot_count,
            "packing": packing,
            "description": description,
            "page": result.get("page"),
        })

    return products


def main(year: str = "2026"):
    text_path = SCRIPTS_DIR / "catalogs" / "jakes" / year / "text_layer.json"
    if not text_path.exists():
        print(f"Not found: {text_path}")
        sys.exit(1)

    data = json.loads(text_path.read_text(encoding="utf-8"))

    # Parse all products from all pages
    all_products: list[dict] = []
    for result in data["results"]:
        if result.get("skipped"):
            continue
        products = parse_products_from_page(result)
        all_products.extend(products)

    # Deduplicate by item_number — keep first occurrence (lowest page number)
    seen: dict[str, dict] = {}
    for p in all_products:
        if p["item_number"] not in seen:
            seen[p["item_number"]] = p
    unique_products = list(seen.values())

    print(f"Found {len(all_products)} product instances, {len(unique_products)} unique SKUs")

    conn = psycopg.connect(DB_URL, autocommit=False)
    inserted = updated = 0
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            # Resolve brand — merge "World Class / Jakes" into "World Class" if both exist
            cur.execute("SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", (BRAND_NAME,))
            row = cur.fetchone()
            brand_id = row[0] if row else None

            cur.execute("SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", ("World Class / Jakes",))
            old_row = cur.fetchone()
            old_brand_id = old_row[0] if old_row else None

            if brand_id and old_brand_id:
                # Merge: re-point old brand's products to canonical brand, then delete old
                cur.execute("UPDATE products SET brand_id=%s WHERE brand_id=%s", (brand_id, old_brand_id))
                cur.execute("DELETE FROM product_brands WHERE id=%s", (old_brand_id,))
                print(f"Merged 'World Class / Jakes' into '{BRAND_NAME}'")
            elif old_brand_id and not brand_id:
                cur.execute("UPDATE product_brands SET name=%s WHERE id=%s", (BRAND_NAME, old_brand_id))
                brand_id = old_brand_id
                print(f"Renamed brand to '{BRAND_NAME}'")
            elif not brand_id:
                cur.execute(
                    "INSERT INTO product_brands (name, tier, brand_type) VALUES (%s,'tier1','house_brand') RETURNING id",
                    (BRAND_NAME,),
                )
                brand_id = cur.fetchone()[0]

            # Category map
            cur.execute("SELECT id, name FROM product_categories")
            cat_map = {name: cid for cid, name in cur.fetchall()}

            # Clear all existing barcodes so we can re-assign correctly
            cur.execute(
                "DELETE FROM product_barcodes WHERE product_id IN "
                "(SELECT id FROM products WHERE brand_id=%s)",
                (brand_id,),
            )

            for p in unique_products:
                item_no = p["item_number"]
                page_num = p.get("page")
                cat_name = category_for_page(page_num) if page_num else None
                cat_id = cat_map.get(cat_name) if cat_name else None

                # Try to get a name from description
                name = extract_name_from_description(p.get("description"))
                if not name:
                    name = f"Item {item_no}"

                cur.execute("SELECT id, name FROM products WHERE item_number = %s", (item_no,))
                existing = cur.fetchone()

                if existing:
                    pid, existing_name = existing
                    # Only replace name if it was auto-generated or we found a real one
                    use_name = name if (not existing_name.startswith("Item ") or name != f"Item {item_no}") else existing_name
                    cur.execute(
                        """UPDATE products
                           SET name=%s, description=%s, shot_count=%s,
                               brand_id=%s, category_id=%s, catalog_page=%s, updated_at=%s
                           WHERE id=%s""",
                        (use_name, p.get("description"), p.get("shot_count"),
                         brand_id, cat_id, page_num, now, pid),
                    )
                    updated += 1
                else:
                    pid = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO products
                               (id, name, item_number, description, shot_count, brand_id,
                                category_id, catalog_page, is_active, created_at, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s)""",
                        (pid, name, item_no, p.get("description"), p.get("shot_count"),
                         brand_id, cat_id, page_num, now, now),
                    )
                    inserted += 1

                # Insert exactly ONE barcode per product
                if p.get("barcode") and len(p["barcode"]) >= 8:
                    cur.execute(
                        """INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary)
                           VALUES (%s,%s,'UPC',true) ON CONFLICT DO NOTHING""",
                        (pid, p["barcode"]),
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Inserted: {inserted}  Updated: {updated}")
    print("\nCategory breakdown:")
    for cat_name, lo, hi in SECTION_MAP:
        n = sum(1 for p in unique_products if p.get("page") and lo <= p["page"] <= hi)
        print(f"  {cat_name}: {n} products (pages {lo}-{hi})")


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else "2026"
    main(year)
