from __future__ import annotations

import json
import subprocess

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
                             original_filename, duration_seconds)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        ),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
