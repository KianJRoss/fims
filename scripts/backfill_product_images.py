"""Backfill products.image_path for any product whose item_number matches a PNG
in media/product_images/.

Run on the Pi:
    cd ~/fims
    python scripts/backfill_product_images.py
"""

import os
from pathlib import Path

import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "media" / "product_images"


def main() -> None:
    pngs = {p.stem: f"product_images/{p.name}" for p in IMAGES_DIR.glob("*.png")}
    if not pngs:
        print("No PNGs found in media/product_images/ — nothing to backfill.")
        return

    print(f"Found {len(pngs)} PNG files.")

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            updated = 0
            for item_number, rel_path in pngs.items():
                cur.execute(
                    "UPDATE products SET image_path = %s WHERE item_number = %s AND (image_path IS NULL OR image_path != %s)",
                    (rel_path, item_number, rel_path),
                )
                updated += cur.rowcount
        conn.commit()

    print(f"Updated {updated} products with image_path.")


if __name__ == "__main__":
    main()
