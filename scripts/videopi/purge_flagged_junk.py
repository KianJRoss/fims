#!/usr/bin/env python3
"""Purge unconfirmed loose-YouTube videos from the 6 flagged in-store products.

Deletes product_videos WHERE confirmed=false AND source NOT IN curated, for the
6 flagged SKUs (resolved to UUID live). Curated rows (instore_playlist,
LEGACY_KIOSK) and any confirmed row are always kept.

Reversible: backs up every deleted row to flagged_junk_purge_backup.json first.
Default dry-run; pass --apply to commit.
"""
import json
import sys
from pathlib import Path

import psycopg

DSN = "postgresql://fims:fims@100.73.208.99:5432/fims"
BACKUP = Path(__file__).with_name("flagged_junk_purge_backup.json")
SKUS = ["MA016", "1003354", "NN5062", "NN4024", "NN2031", "1000470"]
CURATED = ("instore_playlist", "LEGACY_KIOSK")


def main() -> None:
    apply = "--apply" in sys.argv
    conn = psycopg.connect(DSN)
    if not apply:
        conn.read_only = True
    cur = conn.cursor()

    cur.execute("SELECT id, item_number FROM products WHERE item_number = ANY(%s)", (SKUS,))
    uids = {r[0]: r[1] for r in cur.fetchall()}

    cols = ["id", "product_id", "youtube_id", "is_primary", "confirmed", "source",
            "title", "url", "file_path", "video_filename", "download_status"]
    cur.execute(
        f"SELECT {','.join(cols)} FROM product_videos "
        "WHERE product_id = ANY(%s) AND confirmed=false AND source <> ALL(%s) ORDER BY id",
        (list(uids), list(CURATED)),
    )
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["_sku"] = uids.get(r["product_id"])
    BACKUP.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"backup {len(rows)} rows -> {BACKUP}")
    for r in rows:
        print(f"  DELETE id={r['id']} {r['_sku']} [{r['source']}] {r['youtube_id']} :: {r['title']}")

    if apply and rows:
        ids = [r["id"] for r in rows]
        cur.execute("DELETE FROM product_videos WHERE id = ANY(%s)", (ids,))
        conn.commit()
        print(f"COMMITTED: deleted {cur.rowcount} rows.")
    else:
        print("DRY-RUN (pass --apply to commit)." if not apply else "Nothing to delete.")
    conn.close()


if __name__ == "__main__":
    main()
