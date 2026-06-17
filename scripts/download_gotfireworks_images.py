"""
Download product photos from gotfireworks.com for products that still have no
image_path, using the URL list already scraped into gotfireworks_scraped.json
(see scrape_gotfireworks_noname_links.py).

Saves to media/product_images/{item_number}.{ext} and updates products.image_path,
matching the existing convention used by backfill_product_images.py.

Run:
    python scripts/download_gotfireworks_images.py
"""
from __future__ import annotations

import json
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
SCRAPED_JSON = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_scraped.json"
IMAGES_DIR = ROOT / "media" / "product_images"


def normalize_sku(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def fetch_image_url(client: httpx.Client, page_url: str) -> str | None:
    resp = client.get(page_url)
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    img = soup.select_one("img.gallery-placeholder__image")
    if img and img.get("src"):
        return img["src"]
    return None


def main() -> None:
    scraped = json.loads(SCRAPED_JSON.read_text(encoding="utf-8"))
    by_sku = {normalize_sku(item["sku"]): item for item in scraped if item.get("sku")}

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_number FROM products WHERE image_path IS NULL AND item_number IS NOT NULL"
            )
            missing_skus = {normalize_sku(row[0]) for row in cur.fetchall()}

        targets = [by_sku[sku] for sku in missing_skus if sku in by_sku]
        print(f"{len(missing_skus)} products missing an image; {len(targets)} have a known gotfireworks URL")

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        failed = []

        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
            for i, item in enumerate(targets, 1):
                sku = normalize_sku(item["sku"])
                try:
                    image_url = fetch_image_url(client, item["url"])
                    if not image_url:
                        failed.append((sku, "no image found on page"))
                        print(f"[{i}/{len(targets)}] {sku}: no image found")
                        continue

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
