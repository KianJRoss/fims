"""
Import Jake's catalog vision.json into FIMS database.
Reads: scripts/catalogs/jakes/{year}/vision.json
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DB_URL = "postgresql://fims:fims@localhost:5432/fims"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
BRAND_NAME = "World Class / Jakes"


def main(year: str = "2026"):
    vision_path = SCRIPTS_DIR / "catalogs" / "jakes" / year / "vision.json"
    if not vision_path.exists():
        print(f"Not found: {vision_path}")
        sys.exit(1)

    data = json.loads(vision_path.read_text(encoding="utf-8"))
    products = [
        p
        for page in data["pages"]
        for p in page.get("products", [])
        if p.get("item_number")
    ]
    print(f"Found {len(products)} products with item numbers in vision.json")

    conn = psycopg.connect(DB_URL, autocommit=False)
    inserted = skipped = 0
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
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

            cur.execute("SELECT id FROM price_types WHERE code = 'RETAIL'")
            price_row = cur.fetchone()
            if not price_row:
                cur.execute("SELECT id FROM price_types LIMIT 1")
                price_row = cur.fetchone()
            price_type_id = price_row[0] if price_row else None

            for p in products:
                item_no = p["item_number"]
                cur.execute("SELECT id FROM products WHERE item_number = %s", (item_no,))
                if cur.fetchone():
                    skipped += 1
                    continue

                pid = str(uuid.uuid4())
                name = (p.get("name") or "").strip() or f"Item {item_no}"
                cur.execute(
                    """INSERT INTO products
                           (id, name, item_number, description, shot_count, brand_id,
                            is_active, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)""",
                    (
                        pid,
                        name,
                        item_no,
                        p.get("description"),
                        p.get("shell_count"),
                        brand_id,
                        now,
                        now,
                    ),
                )

                for bc in p.get("barcodes") or []:
                    cur.execute(
                        """INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary)
                           VALUES (%s, %s, 'UPC', false) ON CONFLICT DO NOTHING""",
                        (pid, bc),
                    )

                inserted += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Inserted: {inserted}  Skipped (already exist): {skipped}")


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else "2026"
    main(year)
