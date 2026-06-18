#!/usr/bin/env python3
"""Queue YouTube video searches for a filtered RM Enterprises product subset.

Default mode is a dry run that prints a ranked report only.

Usage:
    python scripts/queue_rm_brand_videos.py
    python scripts/queue_rm_brand_videos.py --execute
    python scripts/queue_rm_brand_videos.py --execute --include-secondary --limit 25
    python scripts/queue_rm_brand_videos.py --brand "No Name" --brand "Sunwing"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def _add_import_paths() -> None:
    """Make `app` importable whether the script is run from repo root or /app."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    backend_dir = repo_root / "backend"

    candidates = []
    if backend_dir.exists():
        candidates.append(str(backend_dir))
    if (repo_root / "app").exists():
        candidates.append(str(repo_root))

    for candidate in reversed(candidates):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)


_add_import_paths()

from app.worker.tasks.video_search import find_product_videos  # noqa: E402


DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

DEFAULT_BRANDS = [
    "No Name",
    "Sunwing",
    "Pyro Box",
    "Suns Fireworks",
    "Supreme",
    "Miracle",
    "Top Gun",
]

SMALL_ITEM_PATTERNS = [
    re.compile(r"\bfountain(s)?\b", re.IGNORECASE),
    re.compile(r"\bsparkler(s)?\b", re.IGNORECASE),
    re.compile(r"\bsnake(s)?\b", re.IGNORECASE),
    re.compile(r"\bsmoke\b", re.IGNORECASE),
    re.compile(r"\bspinner(s)?\b", re.IGNORECASE),
    re.compile(r"\bpopper(s)?\b", re.IGNORECASE),
    re.compile(r"\bpunk(s)?\b", re.IGNORECASE),
    re.compile(r"\blighter(s)?\b", re.IGNORECASE),
    re.compile(r"\blance(s)?\b", re.IGNORECASE),
    re.compile(r"\bgender reveal\b", re.IGNORECASE),
    re.compile(r"\bsmoke ball(s)?\b", re.IGNORECASE),
    re.compile(r"\bparachute(s)?\b", re.IGNORECASE),
    re.compile(r"\bwheel(s)?\b", re.IGNORECASE),
    re.compile(r"\bground\b", re.IGNORECASE),
]

PRIORITY_PATTERNS = [
    re.compile(r"\bcake(s)?\b", re.IGNORECASE),
    re.compile(r"\bshot(s)?\b", re.IGNORECASE),
    re.compile(r"\bbattery\b", re.IGNORECASE),
    re.compile(r"\baerial\b", re.IGNORECASE),
    re.compile(r"\bfinale\b", re.IGNORECASE),
    re.compile(r"\bbarrage\b", re.IGNORECASE),
    re.compile(r"\brepeater\b", re.IGNORECASE),
    re.compile(r"\bartillery\b", re.IGNORECASE),
    re.compile(r"\bshell(s)?\b", re.IGNORECASE),
    re.compile(r"\bmine(s)?\b", re.IGNORECASE),
    re.compile(r"\bcomet(s)?\b", re.IGNORECASE),
    re.compile(r"\bmulti[- ]shot\b", re.IGNORECASE),
]

PRIORITY_LABEL_PATTERNS = [
    ("cake", re.compile(r"\bcake(s)?\b", re.IGNORECASE)),
    ("shot", re.compile(r"\bshot(s)?\b", re.IGNORECASE)),
    ("battery", re.compile(r"\bbattery\b", re.IGNORECASE)),
    ("aerial", re.compile(r"\baerial\b", re.IGNORECASE)),
    ("finale", re.compile(r"\bfinale\b", re.IGNORECASE)),
    ("barrage", re.compile(r"\bbarrage\b", re.IGNORECASE)),
    ("repeater", re.compile(r"\brepeater\b", re.IGNORECASE)),
    ("artillery", re.compile(r"\bartillery\b", re.IGNORECASE)),
    ("shell", re.compile(r"\bshell(s)?\b", re.IGNORECASE)),
    ("mine", re.compile(r"\bmine(s)?\b", re.IGNORECASE)),
    ("comet", re.compile(r"\bcomet(s)?\b", re.IGNORECASE)),
    ("multi-shot", re.compile(r"\bmulti[- ]shot\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class ProductRow:
    product_id: str
    item_number: str | None
    name: str
    brand_name: str
    shot_count: int | None
    effects: str | None


@dataclass(frozen=True)
class ScoredProduct:
    row: ProductRow
    bucket: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually enqueue video searches instead of printing a dry-run report.",
    )
    parser.add_argument(
        "--include-secondary",
        action="store_true",
        help="When used with --execute, also enqueue the uncertain SECONDARY items.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap how many products get enqueued in this run.",
    )
    parser.add_argument(
        "--brand",
        action="append",
        default=[],
        help="Restrict to specific brand name(s); may be repeated.",
    )
    return parser.parse_args()


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def combined_search_text(name: str | None, effects: str | None) -> str:
    parts = [normalize_text(name), normalize_text(effects)]
    return " ".join(part for part in parts if part).lower()


def is_priority_signal(text: str, shot_count: int | None) -> bool:
    if shot_count is not None and shot_count >= 9:
        return True
    return any(pattern.search(text) for pattern in PRIORITY_PATTERNS)


def is_small_item(text: str) -> bool:
    return any(pattern.search(text) for pattern in SMALL_ITEM_PATTERNS)


def classify_product(row: ProductRow) -> ScoredProduct | None:
    text = combined_search_text(row.name, row.effects)
    small_match = is_small_item(text)
    parachute_match = bool(re.search(r"\bparachute(s)?\b", text, re.IGNORECASE))
    priority_match = is_priority_signal(text, row.shot_count)

    if small_match and not (parachute_match and row.shot_count is not None and row.shot_count >= 9):
        return None

    if priority_match:
        reason_bits: list[str] = []
        if row.shot_count is not None and row.shot_count >= 9:
            reason_bits.append("shot_count>=9")
        matched_keywords = [label for label, pattern in PRIORITY_LABEL_PATTERNS if pattern.search(text)]
        if matched_keywords:
            reason_bits.extend(matched_keywords)
        if parachute_match and row.shot_count is not None and row.shot_count >= 9:
            reason_bits.append("parachute+high-shot")
        reason = ", ".join(dict.fromkeys(reason_bits)) or "priority signal"
        return ScoredProduct(row=row, bucket="PRIORITY", reason=reason)

    return ScoredProduct(row=row, bucket="SECONDARY", reason="uncertain")


def resolve_brands(cur, requested_brands: list[str]) -> dict[int, str]:
    brand_names = requested_brands or DEFAULT_BRANDS
    resolved: dict[int, str] = {}
    seen_ids: set[int] = set()

    for brand_name in brand_names:
        cur.execute(
            "SELECT id, name FROM product_brands WHERE LOWER(name) = LOWER(%s)",
            (brand_name,),
        )
        row = cur.fetchone()
        if not row:
            print(f"WARNING: brand not found: {brand_name}")
            continue
        brand_id = int(row["id"])
        if brand_id in seen_ids:
            continue
        resolved[brand_id] = row["name"]
        seen_ids.add(brand_id)

    return resolved


def fetch_products(cur, brand_ids: list[int]) -> list[ProductRow]:
    if not brand_ids:
        return []

    cur.execute(
        """
        SELECT
            p.id AS product_id,
            p.item_number,
            p.name,
            b.name AS brand_name,
            p.shot_count,
            p.effects
        FROM products p
        JOIN product_brands b ON b.id = p.brand_id
        WHERE p.is_active IS TRUE
          AND p.no_video_confirmed IS FALSE
          AND p.brand_id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1
              FROM product_videos pv
              WHERE pv.product_id = p.id
                AND pv.confirmed IS TRUE
          )
        ORDER BY lower(b.name), p.item_number NULLS LAST, lower(p.name)
        """,
        (brand_ids,),
    )
    rows = []
    for record in cur.fetchall():
        rows.append(
            ProductRow(
                product_id=str(record["product_id"]),
                item_number=record["item_number"],
                name=record["name"],
                brand_name=record["brand_name"],
                shot_count=record["shot_count"],
                effects=record["effects"],
            )
        )
    return rows


def print_report(scored: list[ScoredProduct], skipped_small_count: int) -> None:
    priority = [item for item in scored if item.bucket == "PRIORITY"]
    secondary = [item for item in scored if item.bucket == "SECONDARY"]

    def _print_section(title: str, items: list[ScoredProduct]) -> None:
        print(f"\n{title} ({len(items)})")
        print("item_number | name | brand | shot_count")
        print("-" * 72)
        if not items:
            print("(none)")
            return
        for item in items:
            row = item.row
            item_number = row.item_number or ""
            shot_count = "" if row.shot_count is None else str(row.shot_count)
            print(f"{item_number} | {row.name} | {row.brand_name} | {shot_count}")

    print(f"Skipped small items: {skipped_small_count}")
    _print_section("PRIORITY", priority)
    _print_section("SECONDARY", secondary)


def main() -> int:
    args = parse_args()

    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit must be >= 0")

    with psycopg.connect(DB_URL, autocommit=False) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            resolved_brands = resolve_brands(cur, args.brand)
            if not resolved_brands:
                print("No brands resolved; nothing to do.")
                return 0

            products = fetch_products(cur, list(resolved_brands.keys()))
            deduped: dict[str, ProductRow] = {}
            for product in products:
                deduped.setdefault(product.product_id, product)

            scored: list[ScoredProduct] = []
            skipped_small_count = 0
            for product in deduped.values():
                classification = classify_product(product)
                if classification is None:
                    skipped_small_count += 1
                    continue
                scored.append(classification)

            scored.sort(
                key=lambda item: (
                    0 if item.bucket == "PRIORITY" else 1,
                    item.row.brand_name.lower(),
                    item.row.shot_count is None,
                    -(item.row.shot_count or 0),
                    (item.row.item_number or ""),
                    item.row.name.lower(),
                )
            )

            print_report(scored, skipped_small_count)

            if not args.execute:
                return 0

            queue: list[ScoredProduct] = [item for item in scored if item.bucket == "PRIORITY"]
            if args.include_secondary:
                queue.extend(item for item in scored if item.bucket == "SECONDARY")

            if args.limit is not None:
                queue = queue[: args.limit]

            if not queue:
                print("\nNo products selected for enqueueing.")
                return 0

            print(f"\nEnqueueing {len(queue)} products...")
            for index, item in enumerate(queue, start=1):
                row = item.row
                print(
                    f"[{index}/{len(queue)}] enqueue {row.item_number or '-'} | "
                    f"{row.name} | {row.brand_name} | {item.bucket} ({item.reason})"
                )
                find_product_videos.delay(row.product_id, row.name, row.item_number)
                if index < len(queue):
                    time.sleep(0.5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
