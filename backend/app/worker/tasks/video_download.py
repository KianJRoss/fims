from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

import psycopg

from app.worker.celery_app import celery_app

DB_URL = "postgresql://fims:fims@postgres:5432/fims"


@celery_app.task(name="video_download.download_video")
def download_video(video_id: int):
    conn: psycopg.Connection | None = None
    try:
        conn = psycopg.connect(DB_URL, autocommit=False)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT confirmed, file_path, youtube_id, product_id, download_status FROM product_videos WHERE id = %s",
                (video_id,),
            )
            row = cur.fetchone()
            if not row:
                return

            confirmed, file_path, youtube_id, product_id, _download_status = row
            if not confirmed:
                return

            media_root = os.getenv("MEDIA_ROOT", "/app/media")
            media_root_path = Path(media_root)
            if file_path:
                existing_file = media_root_path / file_path
                if existing_file.exists():
                    return

            cur.execute(
                "UPDATE product_videos SET download_status = %s WHERE id = %s",
                ("queued", video_id),
            )
            conn.commit()

            output_dir = f"{media_root}/videos/{product_id}"
            os.makedirs(output_dir, exist_ok=True)

            cur.execute(
                "UPDATE product_videos SET download_status = %s WHERE id = %s",
                ("downloading", video_id),
            )
            conn.commit()

            download_cmd = [
                "yt-dlp",
                "-f",
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                f"{output_dir}/{youtube_id}.%(ext)s",
                f"https://www.youtube.com/watch?v={youtube_id}",
            ]
            subprocess.run(download_cmd, check=True, capture_output=True)

            matches = sorted(glob.glob(f"{output_dir}/{youtube_id}.*"))
            if not matches:
                raise FileNotFoundError(f"No downloaded file found for video {video_id}")
            found_file = matches[0]

            dur_result = subprocess.run(
                ["yt-dlp", "--print", "duration", f"https://www.youtube.com/watch?v={youtube_id}"],
                capture_output=True,
                text=True,
            )
            duration = int(dur_result.stdout.strip()) if dur_result.returncode == 0 and dur_result.stdout.strip() else None

            relative_path = Path(found_file).resolve().relative_to(Path(media_root).resolve())
            filename = os.path.basename(found_file)

            cur.execute(
                """
                UPDATE product_videos
                SET file_path = %s,
                    original_filename = %s,
                    duration_seconds = %s,
                    download_status = %s
                WHERE id = %s
                """,
                (relative_path.as_posix(), filename, duration, "done", video_id),
            )
            conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE product_videos SET download_status = %s WHERE id = %s",
                        ("error", video_id),
                    )
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            conn.close()
