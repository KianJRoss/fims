"""Import the legacy Red Rhino kiosk database (redrhino.db, recovered from an old
Raspberry Pi OS SD card found plugged into the server Pi) into FIMS.

The old system mapped barcode (GTIN) -> product name -> video filename in a flat
SQLite table. It predates the current product catalog and contains ~15.5k unique
barcodes spanning brands like Texas Outlaw, Hog Wild, Flashing Fireworks, Red Rhino,
Black Cat, Cutting Edge, etc. — most are not in today's catalog.

Two-tier strategy:
1. UNAMBIGUOUS: barcodes that already match a current FIMS product get a
   ProductVideo row attached directly (additive, non-destructive) — but only if
   the referenced video file still actually exists on the video Pi's drive.
2. NEEDS REVIEW: barcodes with no current match are staged as ImportRows under one
   ImportJob (document_type=LEGACY_BARCODE_DB) so a human decides whether to attach
   each to an existing product or create a new one — consistent with how PDF/Issuu
   catalog imports already work in this system. Nothing is auto-created for these.

Run on the Pi:
    cd ~/fims
    python scripts/import_legacy_redrhino.py
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

LEGACY_DIR = Path(__file__).resolve().parent / "catalogs" / "legacy"
PRODUCTS_CSV = LEGACY_DIR / "redrhino_products.csv"
VIDEO_FILELIST = LEGACY_DIR / "videopi_filelist.txt"
VIDEO_DIR_PREFIX = "/media/pi/VIDEOS/videos"

GTIN_RE = re.compile(r"^\d{6,14}$")
TRAILING_MP4_RE = re.compile(r"\.mp4\.?$", re.IGNORECASE)


def clean_name(pname: str) -> str:
    name = TRAILING_MP4_RE.sub("", pname).strip()
    return name or pname.strip()


def load_video_filenames() -> dict[str, str]:
    """lowercased filename -> real-case filename, for case-insensitive lookup."""
    if not VIDEO_FILELIST.exists():
        print(f"WARNING: {VIDEO_FILELIST} not found — video existence checks disabled")
        return {}
    with VIDEO_FILELIST.open(encoding="utf-8", errors="replace") as fh:
        return {line.strip().lower(): line.strip() for line in fh if line.strip()}


def load_legacy_rows() -> list[dict]:
    rows = []
    with PRODUCTS_CSV.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            gtin = (row.get("gtin") or "").strip()
            if not GTIN_RE.match(gtin):
                continue  # skip YouTube-URL-keyed rows; no barcode to attach
            rows.append(
                {
                    "gtin": gtin,
                    "pname": (row.get("pname") or "").strip(),
                    "vname": (row.get("vname") or "").strip(),
                }
            )
    return rows


def main() -> None:
    legacy_rows = load_legacy_rows()
    video_files = load_video_filenames()
    print(f"Loaded {len(legacy_rows)} numeric-GTIN rows from legacy database.")
    print(f"Loaded {len(video_files)} filenames from video Pi listing.")

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT barcode, product_id FROM product_barcodes")
            existing_barcodes: dict[str, list[str]] = {}
            for barcode, product_id in cur.fetchall():
                existing_barcodes.setdefault(barcode, []).append(product_id)

            cur.execute("SELECT product_id, COUNT(*) FROM product_videos GROUP BY product_id")
            existing_video_counts: dict[str, int] = dict(cur.fetchall())

        matched_rows = []
        unmatched_rows = []
        for row in legacy_rows:
            if row["gtin"] in existing_barcodes:
                matched_rows.append(row)
            else:
                unmatched_rows.append(row)

        print(f"Barcodes already known to FIMS: {len(matched_rows)}")
        print(f"Net-new barcodes (no current product match): {len(unmatched_rows)}")

        # ── Tier 1: attach videos to already-matched products ──────────────────
        videos_attached = 0
        videos_skipped_no_file = 0
        videos_skipped_duplicate = 0
        now = datetime.now(timezone.utc)

        with conn.cursor() as cur:
            for row in matched_rows:
                real_filename = video_files.get(row["vname"].lower())
                if not real_filename:
                    videos_skipped_no_file += 1
                    continue

                for product_id in existing_barcodes[row["gtin"]]:
                    is_primary = existing_video_counts.get(product_id, 0) == 0
                    cur.execute(
                        """
                        INSERT INTO product_videos
                            (product_id, file_path, original_filename, video_filename,
                             source, title, confirmed, is_primary, uploaded_at, created_at)
                        VALUES (%s, %s, %s, %s, 'LEGACY_KIOSK', %s, TRUE, %s, %s, %s)
                        ON CONFLICT (product_id, video_filename) DO NOTHING
                        """,
                        (
                            product_id,
                            f"{VIDEO_DIR_PREFIX}/{real_filename}",
                            real_filename,
                            real_filename,
                            clean_name(row["pname"]),
                            is_primary,
                            now,
                            now,
                        ),
                    )
                    if cur.rowcount:
                        videos_attached += 1
                        existing_video_counts[product_id] = existing_video_counts.get(product_id, 0) + 1
                    else:
                        videos_skipped_duplicate += 1

        # ── Tier 2: stage net-new barcodes for human review ────────────────────
        staged = 0
        if unmatched_rows:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO import_jobs (document_type, file_name, file_path, status, created_at)
                    VALUES ('LEGACY_BARCODE_DB', 'redrhino.db (legacy kiosk system)', %s, 'review', %s)
                    RETURNING id
                    """,
                    (str(PRODUCTS_CSV), now),
                )
                job_id = cur.fetchone()[0]

                for idx, row in enumerate(unmatched_rows):
                    real_filename = video_files.get(row["vname"].lower())
                    raw_data = {
                        "gtin": row["gtin"],
                        "name": clean_name(row["pname"]),
                        "video_filename": real_filename or row["vname"],
                        "video_exists_on_kiosk": real_filename is not None,
                        "source": "legacy_redrhino_kiosk_db",
                    }
                    cur.execute(
                        """
                        INSERT INTO import_rows (job_id, row_index, raw_data, review_status)
                        VALUES (%s, %s, %s, 'pending')
                        """,
                        (job_id, idx, json.dumps(raw_data)),
                    )
                    staged += 1

        conn.commit()

    print()
    print(f"Videos attached to existing products: {videos_attached}")
    print(f"  (skipped, video file no longer on kiosk drive: {videos_skipped_no_file})")
    print(f"  (skipped, already attached: {videos_skipped_duplicate})")
    print(f"Rows staged for review under import job {job_id if unmatched_rows else 'N/A'}: {staged}")
    print("Review at: Documents -> Catalog Import (or GET /api/v1/imports/{job_id}/rows)")


if __name__ == "__main__":
    main()
