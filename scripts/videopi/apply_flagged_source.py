#!/usr/bin/env python3
"""Apply sourced videos for the 6 flagged in-store products (2026-06-26).

User-approved:
  - INSERT s5PUPb-0i84  -> MA016    (CEO 1500g finale, official PYROBOX channel)
  - INSERT ebYpd94LqiI  -> 1003354  (Premium Artillery Shells, World Class)
  - MOVE   OZyI23kMCkY  -> NN5062    (Gorilla Warfare NO NAME; was mislinked to WC 1015147)
  - INSERT XsgYYxuiRD0  -> 1015147   (Gorilla Warfare World Class, Jake's official)

NN4024 / NN2031 / 1000470 deliberately left video-less (no correct YT clip).

Reversible: writes scripts/videopi/flagged_source_backup.json BEFORE any write.
Run with --apply to commit; default is dry-run.
"""
import json
import sys
from pathlib import Path

import psycopg

DSN = "postgresql://fims:fims@100.73.208.99:5432/fims"
BACKUP = Path(__file__).with_name("flagged_source_backup.json")

# SKU -> products.id (UUID), verified live 2026-06-26
PID = {
    "MA016": "de493aa0-3ed1-46a3-9bf4-2329f8b64603",
    "1003354": "bda24651-c31b-452c-ada4-da64327bbefc",
    "NN5062": "9a485fe9-e545-4284-ad9d-5ccd38437bcf",
    "1015147": "1222afeb-35cf-4e14-bd7f-0961eed16de4",
}

# New inserts: (youtube_id, target SKU, title)
INSERTS = [
    ("s5PUPb-0i84", "MA016", "MA016 CEO"),
    ("ebYpd94LqiI", "1003354", "PREMIUM ARTILLERY - World Class Fireworks"),
    ("XsgYYxuiRD0", "1015147", "Jake's Fireworks - Gorilla Warfare"),
]

# Move existing curated row to a new product
MOVE_YID = "OZyI23kMCkY"
MOVE_TO_SKU = "NN5062"


def main() -> None:
    apply = "--apply" in sys.argv

    conn = psycopg.connect(DSN)
    if not apply:
        conn.read_only = True
    cur = conn.cursor()

    # ---- backup ----
    cur.execute(
        "SELECT id, product_id, youtube_id, is_primary, confirmed, source, title "
        "FROM product_videos WHERE youtube_id=%s",
        (MOVE_YID,),
    )
    move_row = cur.fetchone()
    backup = {
        "note": "reverse: move move_row back to original_product_id; delete inserted_youtube_ids",
        "move_row": {
            "id": move_row[0],
            "original_product_id": move_row[1],
            "youtube_id": move_row[2],
        },
        "inserted_youtube_ids": [y for y, _, _ in INSERTS],
    }
    BACKUP.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    print(f"backup -> {BACKUP}")
    print(f"  move row {move_row[0]} ({MOVE_YID}) from {move_row[1]} -> {PID[MOVE_TO_SKU]} ({MOVE_TO_SKU})")

    # ---- inserts ----
    for yid, sku, title in INSERTS:
        print(f"  INSERT {yid} -> {sku} ({PID[sku]}): {title}")
        if apply:
            cur.execute(
                """
                INSERT INTO product_videos
                    (product_id, file_path, original_filename, duration_seconds,
                     is_primary, uploaded_at, source, url, youtube_id, title,
                     confirmed, download_status, video_filename, created_at, updated_at)
                VALUES
                    (%s, %s, NULL, NULL,
                     true, now(), 'instore_playlist', %s, %s, %s,
                     true, 'pending', %s, now(), now())
                """,
                (
                    PID[sku],
                    f"videos/{yid}.mp4",
                    f"https://youtu.be/{yid}",
                    yid,
                    title,
                    f"{yid}.mp4",
                ),
            )

    # ---- move ----
    if apply:
        cur.execute(
            "UPDATE product_videos SET product_id=%s, is_primary=true, confirmed=true, updated_at=now() "
            "WHERE youtube_id=%s",
            (PID[MOVE_TO_SKU], MOVE_YID),
        )
        conn.commit()
        print("COMMITTED.")
    else:
        print("DRY-RUN (pass --apply to commit).")

    conn.close()


if __name__ == "__main__":
    main()
