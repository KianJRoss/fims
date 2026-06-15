"""
Import Jake's catalog into FIMS using the Issuu text layer (text_layer.json).
Run scrape_issuu_text.py first to generate the source file.

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
BRAND_NAME = "World Class / Jakes"

# Pages that are clearly not products
_SKIP_NAMES = {
    "FAR EAST IMPORTS", "PRE-MADE APPAREL", "CUSTOM APPAREL",
    "CUSTOM SIGNS", "PRE-MADE SIGNS", "ALPHABETICAL INDEX",
    "ASSORTMENTS", "CAKES", "SHELLS", "FOUNTAINS", "ROCKETS",
    "SPARKLERS", "NOVELTIES", "ARTILLERY", "FIRECRACKERS",
}


def clean_name(raw: str | None, item_number: str | None) -> str:
    if not raw or raw.strip() in _SKIP_NAMES:
        return f"Item {item_number}" if item_number else "Unknown"
    # Strip OCR noise like "PACKING: ..." that ended up in name field
    name = re.sub(r"\s*(PACKING|BARCODE|SKU)[:\s].*", "", raw, flags=re.IGNORECASE).strip()
    return name or (f"Item {item_number}" if item_number else "Unknown")


def main(year: str = "2026"):
    text_path = SCRIPTS_DIR / "catalogs" / "jakes" / year / "text_layer.json"
    if not text_path.exists():
        print(f"Not found: {text_path}")
        print("Run: python scrape_issuu_text.py --cdn-id <CDN_ID> --slug jakes --year {year} --pages 177 --start-page 11")
        sys.exit(1)

    data = json.loads(text_path.read_text(encoding="utf-8"))
    products = [
        r for r in data["results"]
        if r.get("item_number") and not r.get("skipped")
    ]
    print(f"Found {len(products)} product records with item numbers")

    conn = psycopg.connect(DB_URL, autocommit=False)
    inserted = skipped = updated = 0
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            # Get/create brand
            cur.execute(
                "SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", (BRAND_NAME,)
            )
            row = cur.fetchone()
            brand_id = row[0] if row else None
            if not brand_id:
                cur.execute(
                    "INSERT INTO product_brands (name, tier, brand_type) VALUES (%s, 'tier1', 'house_brand') RETURNING id",
                    (BRAND_NAME,),
                )
                brand_id = cur.fetchone()[0]

            for p in products:
                item_no = p["item_number"]
                name = clean_name(p.get("name"), item_no)

                # Skip non-product pages
                if p.get("name") and p["name"].strip() in _SKIP_NAMES:
                    skipped += 1
                    continue

                # Check if already exists
                cur.execute("SELECT id FROM products WHERE item_number = %s", (item_no,))
                existing = cur.fetchone()

                if existing:
                    # Update with richer data if we have it
                    pid = existing[0]
                    cur.execute(
                        """UPDATE products SET name=%s, description=%s, shot_count=%s, updated_at=%s
                           WHERE id=%s AND (description IS NULL OR description = '')""",
                        (name, p.get("description"), p.get("shot_count"), now, pid),
                    )
                    updated += 1
                else:
                    pid = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO products
                               (id, name, item_number, description, shot_count, brand_id,
                                is_active, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)""",
                        (pid, name, item_no, p.get("description"), p.get("shot_count"),
                         brand_id, now, now),
                    )
                    inserted += 1

                # Insert barcodes
                for bc in p.get("barcodes") or []:
                    if bc and len(bc) >= 8:
                        cur.execute(
                            """INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary)
                               VALUES (%s, %s, 'UPC', false) ON CONFLICT DO NOTHING""",
                            (pid, bc),
                        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Inserted: {inserted}  Updated: {updated}  Skipped: {skipped}")


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else "2026"
    main(year)
