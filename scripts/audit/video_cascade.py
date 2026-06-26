#!/usr/bin/env python3
"""Read-only Tier 1 audit cascade for in-store product videos.

This script classifies unconfirmed product videos for in-store products using
cheap title-based signals only. It writes JSON and Markdown artifacts for human
review and does not perform any writes to the database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Iterable, Sequence

import psycopg


DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")

OUTPUT_DIR = Path(__file__).resolve().parent
JSON_OUT = OUTPUT_DIR / "video_cascade_t1.json"
MD_OUT = OUTPUT_DIR / "video_cascade_t1.md"

CURATED_SOURCES = {"instore_playlist", "LEGACY_KIOSK"}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "big",
    "by",
    "for",
    "from",
    "fx",
    "in",
    "it",
    "item",
    "of",
    "on",
    "our",
    "pack",
    "packaging",
    "paks",
    "set",
    "the",
    "to",
    "with",
}

BLOCKLIST_TERMS = [
    "official music video",
    "unboxing of a phone",
    "breaking news",
    "news at",
    "vs bears",
    "super bowl",
    "quarterback",
    "touchdown",
    "pregame",
    "stadium",
    "highlights",
    "gameplay",
    "weather",
    "basketball",
    "football",
    "nfl",
    "nba",
    "soccer",
    "goal",
    "trailer",
    "movie",
    "lyrics",
    "song",
    "vlog",
]

FIREWORKS_CONTEXT_TERMS = [
    "fireworks",
    "firework",
    "cake",
    "500g",
    "200g",
    "repeater",
    "fountain",
    "shells",
    "finale",
    "mortar",
    "pyro",
    "25 shot",
    "16 shot",
    "shot",
]

NAME_OVERLAP_KEEP_THRESHOLD = 0.6


def normalize_text(text: str | None) -> str:
    """Lowercase and normalize text to alphanumeric tokens separated by spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def tokenize(text: str | None) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    return normalized.split()


def filtered_name_tokens(name: str | None) -> list[str]:
    tokens = tokenize(name)
    return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]


def title_token_set(title: str | None) -> set[str]:
    return set(tokenize(title))


def item_number_text(item_number: object | None) -> str:
    if item_number is None:
        return ""
    return str(item_number).strip()


def brand_tokens(brand: str | None) -> list[str]:
    tokens = tokenize(brand)
    return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]


def first_matching_term(haystack: str, terms: Sequence[str]) -> str | None:
    for term in terms:
        if term in haystack:
            return term
    return None


def title_has_fireworks_context(normalized_title: str) -> bool:
    token_set = set(normalized_title.split())
    for term in FIREWORKS_CONTEXT_TERMS:
        if " " in term:
            if term in normalized_title:
                return True
        elif term == "shot":
            if term in token_set:
                return True
        elif term in normalized_title:
            return True
    return False


def title_has_blocklist_hit(normalized_title: str) -> str | None:
    return first_matching_term(normalized_title, BLOCKLIST_TERMS)


def compute_score(
    *,
    decision: str,
    name_overlap_ratio: float,
    item_match: bool,
    brand_match: bool,
    fireworks_ctx: bool,
    blocklist_hit: str | None,
    curated_source: bool,
) -> int:
    """Heuristic score used for ranking within the chosen decision bucket."""
    if curated_source:
        return 100
    if decision == "KEEP" and item_match:
        return 100
    if decision == "KEEP" and blocklist_hit is None and fireworks_ctx:
        base = 80 + round(name_overlap_ratio * 20)
        if brand_match:
            base += 5
        return min(base, 100)
    if decision == "KEEP":
        base = 65 + round(name_overlap_ratio * 20)
        if brand_match:
            base += 5
        if fireworks_ctx:
            base += 5
        return min(base, 100)
    if decision == "QUARANTINE":
        base = -80 - round(name_overlap_ratio * 10)
        if blocklist_hit:
            base -= 10
        return base
    base = round(name_overlap_ratio * 40)
    if brand_match:
        base += 5
    if fireworks_ctx:
        base += 5
    if blocklist_hit:
        base -= 10
    return base


def classify_video(
    *,
    product_name: str | None,
    item_number: object | None,
    brand_name: str | None,
    source: str | None,
    title: str | None,
) -> tuple[str, int, str]:
    normalized_title = normalize_text(title)
    title_tokens = title_token_set(title)
    curated_source = source in CURATED_SOURCES

    name_tokens = filtered_name_tokens(product_name)
    matched_name_tokens = sum(1 for token in name_tokens if token in title_tokens)
    name_overlap_ratio = (matched_name_tokens / len(name_tokens)) if name_tokens else 0.0

    item_value = item_number_text(item_number)
    item_match = bool(item_value) and item_value.lower() in normalized_title

    brand_token_list = brand_tokens(brand_name)
    brand_match = any(token in title_tokens for token in brand_token_list)

    fireworks_ctx = title_has_fireworks_context(normalized_title)
    blocklist_hit = title_has_blocklist_hit(normalized_title)

    if curated_source:
        decision = "KEEP"
        reason = "curated source"
    elif item_match:
        decision = "KEEP"
        reason = "item# in title"
    elif blocklist_hit and name_overlap_ratio < NAME_OVERLAP_KEEP_THRESHOLD:
        decision = "QUARANTINE"
        reason = f"blocklist hit: {blocklist_hit}"
    elif name_overlap_ratio >= NAME_OVERLAP_KEEP_THRESHOLD and fireworks_ctx:
        decision = "KEEP"
        reason = "strong name + fireworks context"
    elif name_overlap_ratio == 0:
        decision = "QUARANTINE"
        reason = "no product-name overlap"
    else:
        decision = "UNCERTAIN"
        parts = [f"name_overlap={name_overlap_ratio:.2f}"]
        if brand_match:
            parts.append("brand_match")
        if fireworks_ctx:
            parts.append("fireworks_ctx")
        if blocklist_hit:
            parts.append(f"blocklist_hit={blocklist_hit}")
        reason = "; ".join(parts)

    score = compute_score(
        decision=decision,
        name_overlap_ratio=name_overlap_ratio,
        item_match=item_match,
        brand_match=brand_match,
        fireworks_ctx=fireworks_ctx,
        blocklist_hit=blocklist_hit,
        curated_source=curated_source,
    )
    return decision, score, reason


def build_query(product_filter: str | None) -> tuple[str, list[object]]:
    base_sql = """
        SELECT
            p.id::text AS product_id,
            p.item_number::text AS item_number,
            p.name AS product_name,
            b.name AS brand_name,
            pv.id AS video_id,
            pv.youtube_id,
            pv.title,
            pv.source
        FROM products p
        LEFT JOIN product_brands b
            ON b.id = p.brand_id
        JOIN product_videos pv
            ON pv.product_id = p.id
           AND pv.confirmed = false
        WHERE p.in_store = true
    """
    params: list[object] = []
    if product_filter:
        base_sql += """
          AND (p.id::text = %s OR p.item_number::text = %s)
        """
        params.extend([product_filter, product_filter])
    base_sql += """
        ORDER BY p.name, p.id, pv.id
    """
    return base_sql, params


def fetch_rows(product_filter: str | None) -> list[tuple]:
    sql, params = build_query(product_filter)
    with psycopg.connect(DB_URL) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def group_rows(rows: Iterable[tuple]) -> list[dict]:
    grouped: list[dict] = []
    current_product_id: str | None = None
    current_entry: dict | None = None

    for row in rows:
        product_id, item_number, product_name, brand_name, video_id, youtube_id, title, source = row
        if product_id != current_product_id:
            if current_entry is not None:
                grouped.append(current_entry)
            current_product_id = product_id
            current_entry = {
                "product_id": product_id,
                "item_number": item_number,
                "name": product_name,
                "brand": brand_name,
                "n_unconfirmed": 0,
                "keep": [],
                "quarantine": [],
                "uncertain": [],
            }

        assert current_entry is not None
        current_entry["n_unconfirmed"] += 1
        decision, score, reason = classify_video(
            product_name=product_name,
            item_number=item_number,
            brand_name=brand_name,
            source=source,
            title=title,
        )
        video_entry = {
            "video_id": video_id,
            "youtube_id": youtube_id,
            "title": title,
            "score": score,
            "reason": reason,
        }
        current_entry[decision.lower()].append(video_entry)

    if current_entry is not None:
        grouped.append(current_entry)

    return grouped


def write_json(products: list[dict]) -> None:
    JSON_OUT.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")


def truncate_text(value: str | None, limit: int = 60) -> str:
    if not value:
        return ""
    text = value.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def write_markdown(products: list[dict]) -> dict[str, int]:
    totals = {"KEEP": 0, "QUARANTINE": 0, "UNCERTAIN": 0}
    lines: list[str] = []
    total_videos = 0

    for product in products:
        for bucket in ("keep", "quarantine", "uncertain"):
            totals[bucket.upper()] += len(product[bucket])
        total_videos += product["n_unconfirmed"]

    lines.append("# Video Cascade T1")
    lines.append("")
    lines.append(f"- Products with unconfirmed videos: {len(products)}")
    lines.append(f"- Unconfirmed videos classified: {total_videos}")
    lines.append(f"- KEEP: {totals['KEEP']}")
    lines.append(f"- QUARANTINE: {totals['QUARANTINE']}")
    lines.append(f"- UNCERTAIN: {totals['UNCERTAIN']}")
    lines.append("")

    for product in products:
        lines.append(f"## {product['name']} ({product['item_number'] or product['product_id']})")
        lines.append("")
        lines.append(f"- Brand: {product['brand'] or ''}")
        lines.append(f"- Unconfirmed videos: {product['n_unconfirmed']}")
        lines.append("")
        lines.append("| bucket | count | sample title |")
        lines.append("| --- | ---: | --- |")
        for bucket_name in ("keep", "quarantine", "uncertain"):
            sample = product[bucket_name][0]["title"] if product[bucket_name] else ""
            lines.append(
                "| {bucket} | {count} | {sample} |".format(
                    bucket=bucket_name.upper(),
                    count=len(product[bucket_name]),
                    sample=truncate_text(sample, 70).replace("|", "\\|"),
                )
            )
        lines.append("")

    MD_OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return totals


def run_tier_1(product_filter: str | None) -> tuple[list[dict], dict[str, int]]:
    rows = fetch_rows(product_filter)
    products = group_rows(rows)
    write_json(products)
    totals = write_markdown(products)
    return products, totals


def tier2_enrich_with_ytdlp_metadata() -> None:
    """Tier 2 stub.

    Intended future behavior: enrich Tier 1 candidates via yt-dlp metadata such
    as channel, duration, description, and upload hints to refine ambiguous
    title-only classifications. This version intentionally does not implement
    any network calls or persistence.
    """

    raise NotImplementedError("Tier 2 is not implemented yet; it will enrich via yt-dlp metadata.")


def tier3_vision_frame_check() -> None:
    """Tier 3 stub.

    Intended future behavior: inspect representative frames via scripts/vision/
    to confirm whether the video content visually matches the associated
    firework product. This version intentionally does not implement any vision
    processing or persistence.
    """

    raise NotImplementedError("Tier 3 is not implemented yet; it will perform a vision frame check.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="In-store video weed-out cascade (Tier 1, read-only)")
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), default=1, help="Cascade tier to run")
    parser.add_argument(
        "--product",
        default=None,
        help="Optional product filter matching product id or item number for spot checks",
    )
    return parser.parse_args()


def print_totals(totals: dict[str, int]) -> None:
    print(f"KEEP: {totals['KEEP']}")
    print(f"QUARANTINE: {totals['QUARANTINE']}")
    print(f"UNCERTAIN: {totals['UNCERTAIN']}")


def main() -> None:
    args = parse_args()
    if args.tier == 2:
        tier2_enrich_with_ytdlp_metadata()
    if args.tier == 3:
        tier3_vision_frame_check()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _, totals = run_tier_1(args.product)
    print_totals(totals)


if __name__ == "__main__":
    main()
