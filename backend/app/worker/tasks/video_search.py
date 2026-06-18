from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import psycopg

from app.worker.celery_app import celery_app

DB_URL = "postgresql://fims:fims@postgres:5432/fims"


@celery_app.task(name="video_search.find_product_videos")
def find_product_videos(product_id: str, product_name: str, item_number: str | None = None):
    queries = []
    if product_name:
        queries.append(f"'{product_name}' fireworks")
    if item_number:
        queries.append(f"'{item_number}' fireworks review")

    if not queries:
        return

    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT youtube_id FROM product_videos WHERE product_id = %s AND youtube_id IS NOT NULL",
                (product_id,),
            )
            existing_ids = {row[0] for row in cur.fetchall() if row[0]}

            for query in queries:
                command = [
                    "yt-dlp",
                    f"ytsearch5:{query}",
                    "--dump-json",
                    "--flat-playlist",
                    "--no-download",
                    "--quiet",
                ]
                result = subprocess.run(command, capture_output=True, text=True, check=True)
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    video = json.loads(line)
                    youtube_id = video.get("id")
                    if not youtube_id or youtube_id in existing_ids:
                        continue

                    existing_ids.add(youtube_id)
                    cur.execute(
                        """
                        INSERT INTO product_videos
                            (product_id, file_path, source, url, youtube_id, title,
                             thumbnail_url, search_query, confirmed, is_primary,
                             original_filename, duration_seconds, uploaded_at,
                             video_filename)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            product_id,
                            "",
                            "YOUTUBE",
                            video.get("url") or youtube_id,
                            youtube_id,
                            video.get("title"),
                            video.get("thumbnail"),
                            query,
                            False,
                            False,
                            None,
                            None,
                            datetime.now(timezone.utc).replace(tzinfo=None),
                            youtube_id,
                        ),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@celery_app.task(name="app.worker.tasks.video_search.auto_search_missing_videos")
def auto_search_missing_videos(batch_size: int = 25) -> dict:
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, item_number
                FROM products
                WHERE is_active IS TRUE
                  AND no_video_confirmed IS FALSE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM product_videos
                      WHERE product_videos.product_id = products.id
                        AND product_videos.confirmed IS TRUE
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM product_videos
                      WHERE product_videos.product_id = products.id
                  )
                ORDER BY created_at DESC, LOWER(name)
                LIMIT %s
                """,
                (batch_size,),
            )
            rows = cur.fetchall()

        for product_id, product_name, item_number in rows:
            find_product_videos.delay(str(product_id), product_name, item_number)

        return {"queued": len(rows), "batch_size": batch_size}
    finally:
        conn.close()
