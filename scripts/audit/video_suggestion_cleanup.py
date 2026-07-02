#!/usr/bin/env python3
"""Cull junk from unconfirmed YouTube product video suggestions.

Defaults to a dry run. Pass --apply to back up and delete rows classified as
junk from product_videos.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


DEFAULT_DSN = "postgresql://fims:fims@localhost:5432/fims"
DEFAULT_BACKUP = "scripts/audit/video_suggestions_deleted.jsonl"
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "shot",
    "shots",
    "gram",
    "cake",
    "fireworks",
    "firework",
}
JUNK_TITLE_RE = re.compile(
    r"news|breaking|caught on (camera|video)|accident|arrested|police|"
    r"documentary|gameplay|walkthrough|minecraft|fortnite|roblox|podcast",
    re.IGNORECASE,
)


def tokens(text: str | None) -> set[str]:
    cleaned = re.sub(r"[^0-9a-z]+", " ", (text or "").lower())
    return {part for part in cleaned.split() if len(part) > 2 and part not in STOPWORDS}


def overlap_ratio(name: str | None, title: str | None) -> float:
    name_tokens = tokens(name)
    if not name_tokens:
        return 0.0
    title_tokens = tokens(title)
    return len(name_tokens & title_tokens) / len(name_tokens)


def classify(row: dict) -> str:
    title = row.get("title")
    if title is None:
        return "junk"

    if JUNK_TITLE_RE.search(title):
        return "junk"

    overlap = overlap_ratio(row.get("product_name"), title)
    item_number = str(row.get("item_number") or "").strip()
    title_lower = title.lower()
    if overlap == 0.0 and (not item_number or item_number.lower() not in title_lower):
        return "junk"

    return "keep"


def fetch_candidates(conn: psycopg.Connection) -> list[dict]:
    query = """
        SELECT
            pv.id,
            pv.product_id,
            pv.youtube_id,
            pv.title,
            p.name AS product_name,
            p.item_number
        FROM product_videos pv
        JOIN products p ON p.id = pv.product_id
        WHERE pv.confirmed = false
          AND pv.source = 'YOUTUBE'
        ORDER BY pv.id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        return list(cur.fetchall())


def backup_rows(rows: list[dict], backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with backup_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            payload = {
                "id": row["id"],
                "product_id": row["product_id"],
                "youtube_id": row["youtube_id"],
                "title": row["title"],
                "product_name": row["product_name"],
            }
            handle.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


def delete_rows(conn: psycopg.Connection, junk_ids: list) -> int:
    if not junk_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute("DELETE FROM product_videos WHERE id = ANY(%s)", (junk_ids,))
        return cur.rowcount


def print_dry_run(rows: list[dict], junk_rows: list[dict], keep_rows: list[dict]) -> None:
    print(f"total rows: {len(rows)}")
    print(f"junk count: {len(junk_rows)}")
    print(f"keep count: {len(keep_rows)}")
    print("sample junk titles:")
    for row in junk_rows[:15]:
        title = row.get("title")
        product_name = row.get("product_name")
        print(f"- {title!r} ({product_name})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cull junk from unconfirmed YouTube video suggestions."
    )
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help=f"Postgres DSN (default: {DEFAULT_DSN})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and delete junk rows. Defaults to dry-run.",
    )
    parser.add_argument(
        "--backup",
        default=DEFAULT_BACKUP,
        help=f"JSONL backup path for deleted rows (default: {DEFAULT_BACKUP})",
    )
    args = parser.parse_args()

    with psycopg.connect(args.dsn, autocommit=False, row_factory=dict_row) as conn:
        rows = fetch_candidates(conn)
        junk_rows = [row for row in rows if classify(row) == "junk"]
        keep_rows = [row for row in rows if classify(row) == "keep"]

        if not args.apply:
            print_dry_run(rows, junk_rows, keep_rows)
            return 0

        backup_rows(junk_rows, Path(args.backup))
        deleted_count = delete_rows(conn, [row["id"] for row in junk_rows])
        conn.commit()
        print(f"deleted count: {deleted_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
