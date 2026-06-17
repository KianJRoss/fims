"""
Download product photos from worldclassfireworks.com (Jake's brand) for products
that still have no image_path.

worldclassfireworks.com has no saved per-product URL list (unlike the No Name PDF's
embedded hyperlinks), so this script first enumerates every product by walking the
site's `/fw_type/{type}/` taxonomy archive pages — each renders its full category on
one page (confirmed: no pagination, e.g. Finales = 231 products on one page). SKU is
embedded directly in the product image filename, e.g. "1004385-PIONEERS-OF-PROGRESS-
Right.png" -> SKU 1004385.

Saves to media/product_images/{item_number}.{ext} and updates products.image_path,
matching the existing convention used by backfill_product_images.py.

Run:
    python scripts/download_worldclass_images.py
"""
from __future__ import annotations

import os
import random
import re
import time
from pathlib import Path

import httpx
import psycopg
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "media" / "product_images"

FW_TYPES = [
    "fountains", "show-starters", "finales", "artillery-shells", "family-packs",
    "firecrackers", "novelties", "sparklers", "roman-candles", "rockets",
    "show-to-go-cartons",
]

# SKUs on this site are consistently 7 digits (confirmed: 548/549 World Class
# products in FIMS have a 7-digit item_number). Filenames use two different
# conventions: "1004385-PIONEERS-OF-PROGRESS-Right.png" (hyphenated) and
# "100399820Money20Maker.jpg" (older files where literal "20" replaced spaces
# with no separator) -- so anchor on exactly 7 digits at the start of the
# basename rather than requiring a hyphen after it.
SKU_FROM_FILENAME_RE = re.compile(r"/(\d{7})[^/]*\.(?:png|jpe?g)$", re.IGNORECASE)


def normalize_sku(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def enumerate_products(client: httpx.Client) -> dict[str, str]:
    """Returns {sku: image_url}, deduped across all fw_type pages."""
    sku_to_image: dict[str, str] = {}
    for fw_type in FW_TYPES:
        url = f"https://www.worldclassfireworks.com/fw_type/{fw_type}/"
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  {fw_type}: fetch failed {resp.status_code}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.product-single")
        found = 0
        for card in cards:
            img = card.select_one(".product-media img")
            if not img or not img.get("src"):
                continue
            m = SKU_FROM_FILENAME_RE.search(img["src"])
            if not m:
                continue
            sku = m.group(1)
            if sku not in sku_to_image:
                sku_to_image[sku] = img["src"]
                found += 1
        print(f"  {fw_type}: {len(cards)} cards, {found} new SKUs")
        time.sleep(0.4 + random.random() * 0.3)
    return sku_to_image


def main() -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        print("Enumerating World Class products by taxonomy page...")
        sku_to_image = enumerate_products(client)
        print(f"\nTotal unique SKUs found: {len(sku_to_image)}")

        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT item_number FROM products WHERE image_path IS NULL AND item_number IS NOT NULL"
                )
                missing_skus = {normalize_sku(row[0]) for row in cur.fetchall()}

            targets = {sku: url for sku, url in sku_to_image.items() if sku in missing_skus}
            print(f"{len(missing_skus)} products missing an image; {len(targets)} have a known World Class image")

            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            failed = []

            for i, (sku, image_url) in enumerate(targets.items(), 1):
                try:
                    ext = Path(image_url.split("?")[0]).suffix or ".jpg"
                    safe_sku = re.sub(r'[\\/:*?"<>|]', "-", sku)
                    dest = IMAGES_DIR / f"{safe_sku}{ext}"

                    img_resp = client.get(image_url)
                    if img_resp.status_code != 200:
                        failed.append((sku, f"image fetch {img_resp.status_code}"))
                        print(f"[{i}/{len(targets)}] {sku}: image fetch failed {img_resp.status_code}")
                        continue

                    dest.write_bytes(img_resp.content)
                    rel_path = f"product_images/{dest.name}"

                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE products SET image_path = %s WHERE item_number = %s AND image_path IS NULL",
                            (rel_path, sku),
                        )
                    conn.commit()
                    downloaded += 1
                    print(f"[{i}/{len(targets)}] {sku}: saved {rel_path}")
                except httpx.HTTPError as exc:
                    failed.append((sku, str(exc)))
                    print(f"[{i}/{len(targets)}] {sku}: ERROR {exc}")

                time.sleep(0.4 + random.random() * 0.3)

    print(f"\nDownloaded and linked: {downloaded}")
    print(f"Failed: {len(failed)}")
    for sku, reason in failed:
        print(" ", sku, reason)


if __name__ == "__main__":
    main()
