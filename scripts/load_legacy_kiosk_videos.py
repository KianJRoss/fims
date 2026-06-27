"""Populate the legacy_kiosk_videos lookup table from the old Red Rhino kiosk DB.

The old PyroSalesman kiosk mapped barcode (GTIN) -> video filename in a flat
SQLite table (redrhino.db). FIMS already imported the rows whose barcodes matched
a current product (see import_legacy_redrhino.py); this loads the FULL barcode->
video map into a dedicated lookup table so the video Remote can fall back to a
legacy clip when a scanned barcode isn't a FIMS product at all.

Source of truth is the recovered CSV shipped in the repo
(scripts/catalogs/legacy/redrhino_products.csv) so this can run on any host that
has the repo + the FIMS Postgres, without needing the legacy SQLite file.

Idempotent: truncates and reloads the table each run.

Run on the Pi:
    cd ~/fims
    docker compose exec -T api python /app/../scripts/load_legacy_kiosk_videos.py   # if mounted
    # or, simplest, from the host with the venv/psycopg available:
    DATABASE_URL=postgresql://fims:fims@localhost:5432/fims python scripts/load_legacy_kiosk_videos.py
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

LEGACY_DIR = Path(__file__).resolve().parent / "catalogs" / "legacy"
PRODUCTS_CSV = LEGACY_DIR / "redrhino_products.csv"

# Real barcodes only — the legacy table also keeps download-source URLs in the
# gtin column (e.g. http://dominatorfireworks.com/...), which are not scannable.
GTIN_RE = re.compile(r"^\d{6,14}$")
TRAILING_MP4_RE = re.compile(r"\.mp4\.?$", re.IGNORECASE)


def clean_name(pname: str) -> str:
    name = TRAILING_MP4_RE.sub("", pname).strip()
    return name or pname.strip()


def norm_gtin(gtin: str) -> str:
    stripped = gtin.lstrip("0")
    return stripped or gtin


def load_rows() -> dict[str, dict]:
    """gtin -> {gtin_norm, video_filename, name}. Last write wins per gtin."""
    rows: dict[str, dict] = {}
    with PRODUCTS_CSV.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            gtin = (row.get("gtin") or "").strip()
            if not GTIN_RE.match(gtin):
                continue
            vname = (row.get("vname") or "").strip()
            if not vname:
                continue
            rows[gtin] = {
                "gtin_norm": norm_gtin(gtin),
                "video_filename": Path(vname).name,  # store bare filename
                "name": clean_name(row.get("pname") or "") or None,
            }
    return rows


def main() -> None:
    if not PRODUCTS_CSV.exists():
        raise SystemExit(f"Legacy CSV not found: {PRODUCTS_CSV}")

    rows = load_rows()
    print(f"Loaded {len(rows)} unique numeric-GTIN rows with a video filename.")

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE legacy_kiosk_videos")
            cur.executemany(
                """
                INSERT INTO legacy_kiosk_videos (gtin, gtin_norm, video_filename, name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (gtin) DO UPDATE
                    SET gtin_norm = EXCLUDED.gtin_norm,
                        video_filename = EXCLUDED.video_filename,
                        name = EXCLUDED.name
                """,
                [
                    (gtin, r["gtin_norm"], r["video_filename"], r["name"])
                    for gtin, r in rows.items()
                ],
            )
        conn.commit()

        with conn.cursor() as cur:
            total = cur.execute("SELECT COUNT(*) FROM legacy_kiosk_videos").fetchone()[0]
    print(f"legacy_kiosk_videos now has {total} rows.")


if __name__ == "__main__":
    main()
