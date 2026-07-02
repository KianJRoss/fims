#!/usr/bin/env python3
"""Link legacy-kiosk videos to FIMS products that share a barcode.

For every FIMS product whose barcode appears in legacy_kiosk_videos but that
has no product_videos row for the legacy file: create the pairing, but only
when the file actually exists on the Video Pi. Pairings whose filename
plausibly matches the product (item number in filename, or >=50% name-token
overlap) are confirmed; the rest are inserted unconfirmed so they land in the
review queue instead of playing a possibly-wrong clip as authoritative —
legacy barcodes were reused across years, so a barcode match alone does not
prove the video shows this product.

Run on the FIMS Pi:  python3 scripts/audit/link_legacy_videos.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request

import psycopg

DSN = "postgresql://fims:fims@localhost:5432/fims"
VIDEO_PI_VIDEOS_URL = "http://192.168.0.198:7777/videos"

STOPWORDS = {"the", "and", "for", "with", "shot", "shots", "gram", "cake",
             "fireworks", "firework", "mp4", "mov"}


def tokens(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return {t for t in normalized.split() if len(t) > 2 and t not in STOPWORDS}


def plausible(name: str, item_number: str | None, filename: str) -> bool:
    fname = filename.lower()
    item = (item_number or "").strip().lower()
    if item and item in fname:
        return True
    name_tokens = tokens(name)
    if not name_tokens:
        return False
    overlap = name_tokens & tokens(filename)
    return len(overlap) / len(name_tokens) >= 0.5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write pairings (default dry-run)")
    args = parser.parse_args()

    with urllib.request.urlopen(VIDEO_PI_VIDEOS_URL, timeout=15) as response:
        on_drive = {name.lower() for name in json.load(response)["videos"]}

    conn = psycopg.connect(DSN)
    rows = conn.execute(
        """
        SELECT DISTINCT p.id, p.name, p.item_number, lkv.video_filename
        FROM products p
        JOIN product_barcodes pb ON pb.product_id = p.id
        JOIN legacy_kiosk_videos lkv
          ON (lkv.gtin = pb.barcode OR lkv.gtin_norm = pb.barcode)
        WHERE NOT EXISTS (
            SELECT 1 FROM product_videos pv
            WHERE pv.product_id = p.id
              AND lower(pv.video_filename) = lower(lkv.video_filename)
        )
        """
    ).fetchall()

    linked = skipped_missing = 0
    for product_id, name, item_number, filename in rows:
        if filename.lower() not in on_drive:
            print(f"SKIP (not on drive): {name} -> {filename}")
            skipped_missing += 1
            continue
        confirmed = plausible(name, item_number, filename)
        label = "CONFIRMED" if confirmed else "unconfirmed (review)"
        print(f"LINK [{label}]: {name} -> {filename}")
        if args.apply:
            conn.execute(
                """
                INSERT INTO product_videos
                    (product_id, file_path, source, confirmed, download_status,
                     original_filename, video_filename, is_primary, uploaded_at, created_at)
                VALUES (%s, %s, 'LEGACY_KIOSK', %s, 'pending', %s, %s, FALSE, now(), now())
                ON CONFLICT (product_id, video_filename) DO NOTHING
                """,
                (str(product_id), f"/media/pi/VIDEOS/videos/{filename}", confirmed,
                 filename, filename),
            )
        linked += 1

    if args.apply:
        conn.commit()
    conn.close()
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: {linked} linked, {skipped_missing} skipped (file missing)")


if __name__ == "__main__":
    main()
