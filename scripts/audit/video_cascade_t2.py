#!/usr/bin/env python3
"""Read-only Tier 2 audit cascade for in-store product videos.

This script enriches unconfirmed product videos with yt-dlp metadata, applies
stricter scoring than Tier 1, and writes JSON and Markdown artifacts for human
review. It performs no database writes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import psycopg

from video_cascade import normalize_text as normalize, tokenize, STOPWORDS, BLOCKLIST_TERMS as BLOCKLIST


DB_URL = os.environ.get("DATABASE_URL", "postgresql://fims:fims@100.73.208.99:5432/fims")

OUTPUT_DIR = Path(__file__).resolve().parent
JSON_OUT = OUTPUT_DIR / "video_cascade_t2.json"
MD_OUT = OUTPUT_DIR / "video_cascade_t2.md"
CACHE_OUT = OUTPUT_DIR / "video_cascade_t2_cache.json"

CURATED_SOURCES = ("instore_playlist", "LEGACY_KIOSK")

KNOWN_OFFICIAL = {
    "worldclass",
    "sunwing",
    "jakes",
    "blackcat",
    "brothers",
    "greatgrizzly",
    "madox",
}

FETCH_TIMEOUT_SECONDS = 45
CACHE_FLUSH_EVERY = 10

NAME_OVERLAP_CONFIRM_MIN = 0.6
NAME_OVERLAP_LOW_MAX = 0.2
CONFIRM_THRESHOLD = 60
QUAR_THRESHOLD = 15

ITEM_MATCH_BONUS = 45
NAME_OVERLAP_GOOD_BONUS = 15
NAME_OVERLAP_ZERO_PENALTY = -25
CHANNEL_MATCH_BONUS = 12
OFFICIAL_CHANNEL_BONUS = 10
FIREWORKS_CONTEXT_BONUS = 6
BLOCKLIST_LOW_OVERLAP_PENALTY = -80
BLOCKLIST_PENALTY = -20
DURATION_SHORT_PENALTY = -15
DURATION_GOOD_BONUS = 10
DURATION_MEDIUM_PENALTY = -8
DURATION_LONG_PENALTY = -25

YTDLP_FORMAT = (
    "%(id)s\t%(channel)s\t%(channel_id)s\t%(duration)s\t%(view_count)s\t%(upload_date)s\t"
    "%(availability)s\t%(live_status)s\t%(title)s"
)


def _load_json_file(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _json_default(o: object) -> object:
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def _write_json_file(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _clean_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "NONE", "NULL"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _normalize_cache_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    status = entry.get("status")
    if status == "dead":
        return {"status": "dead"}
    if status == "ok":
        return {
            "status": "ok",
            "id": entry.get("id"),
            "channel": entry.get("channel"),
            "channel_id": entry.get("channel_id"),
            "duration": _clean_int(entry.get("duration")),
            "view_count": _clean_int(entry.get("view_count")),
            "upload_date": entry.get("upload_date"),
            "availability": entry.get("availability"),
            "live_status": entry.get("live_status"),
            "title": entry.get("title"),
        }
    return None


def load_cache() -> dict[str, dict]:
    raw = _load_json_file(CACHE_OUT, {})
    if not isinstance(raw, dict):
        return {}
    cache: dict[str, dict] = {}
    for youtube_id, entry in raw.items():
        normalized = _normalize_cache_entry(entry)
        if normalized is not None:
            cache[str(youtube_id)] = normalized
    return cache


def save_cache(cache: dict[str, dict]) -> None:
    _write_json_file(CACHE_OUT, cache)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return normalize(text)


def filtered_name_tokens(name: str | None) -> list[str]:
    return [token for token in tokenize(name) if len(token) > 2 and token not in STOPWORDS]


def brand_tokens(brand: str | None) -> list[str]:
    return [token for token in tokenize(brand) if len(token) > 2 and token not in STOPWORDS]


def item_number_text(item_number: object | None) -> str:
    if item_number is None:
        return ""
    return str(item_number).strip()


def title_has_fireworks_context(normalized_title: str) -> bool:
    token_set = set(normalized_title.split())
    for term in (
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
    ):
        if " " in term:
            if term in normalized_title:
                return True
        elif term == "shot":
            if term in token_set:
                return True
        elif term in normalized_title:
            return True
    return False


def title_blocklist_hit(normalized_title: str) -> str | None:
    for term in BLOCKLIST:
        if term in normalized_title:
            return term
    return None


def distinctive_channel_hit(channel: str | None, tokens: Iterable[str]) -> str | None:
    if not channel:
        return None
    channel_norm = normalize_text(channel)
    channel_compact = channel_norm.replace(" ", "")
    channel_tokens = set(channel_norm.split())

    for token in tokens:
        if token in channel_tokens or token in channel_norm or token in channel_compact:
            return token

    for official in KNOWN_OFFICIAL:
        if official in channel_compact or official in channel_norm.replace(" ", ""):
            return official
    return None


def coerce_metadata(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status == "dead":
        return {"status": "dead"}
    if status == "ok":
        return {
            "status": "ok",
            "id": raw.get("id"),
            "channel": raw.get("channel"),
            "channel_id": raw.get("channel_id"),
            "duration": _clean_int(raw.get("duration")),
            "view_count": _clean_int(raw.get("view_count")),
            "upload_date": raw.get("upload_date"),
            "availability": raw.get("availability"),
            "live_status": raw.get("live_status"),
            "title": raw.get("title"),
        }
    return None


def fetch_yt_dlp_metadata(youtube_id: str) -> dict:
    url = f"https://youtu.be/{youtube_id}"
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--skip-download",
        "--print",
        YTDLP_FORMAT,
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FETCH_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {"status": "dead"}

    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0 or not stdout:
        return {"status": "dead"}

    line = next((line for line in stdout.splitlines() if line.strip()), "")
    if not line:
        return {"status": "dead"}

    parts = line.split("\t", 8)
    if len(parts) < 9:
        return {"status": "dead"}

    vid, channel, channel_id, duration, view_count, upload_date, availability, live_status, title = parts
    return {
        "status": "ok",
        "id": vid or youtube_id,
        "channel": channel or None,
        "channel_id": channel_id or None,
        "duration": _clean_int(duration),
        "view_count": _clean_int(view_count),
        "upload_date": upload_date or None,
        "availability": availability or None,
        "live_status": live_status or None,
        "title": title or None,
    }


def fetch_metadata(
    youtube_ids: list[str],
    cache: dict[str, dict],
    *,
    refresh: bool,
    no_fetch: bool,
) -> dict[str, dict]:
    if no_fetch:
        return cache

    pending = [youtube_id for youtube_id in youtube_ids if refresh or youtube_id not in cache]
    total = len(pending)
    fetched_since_flush = 0

    for idx, youtube_id in enumerate(pending, start=1):
        print(f"fetch {idx}/{total} {youtube_id} ...", file=sys.stderr)
        cache[youtube_id] = fetch_yt_dlp_metadata(youtube_id)
        fetched_since_flush += 1
        if fetched_since_flush >= CACHE_FLUSH_EVERY:
            save_cache(cache)
            fetched_since_flush = 0

    if pending:
        save_cache(cache)
    return cache


def build_query(product_filter: str | None) -> tuple[str, list[object]]:
    sql = """
        SELECT
            p.id::text AS product_id,
            p.item_number::text AS item_number,
            p.name AS product_name,
            b.name AS brand_name,
            pv.id::text AS video_id,
            pv.youtube_id,
            pv.title,
            pv.url
        FROM products p
        LEFT JOIN product_brands b
            ON b.id = p.brand_id
        JOIN product_videos pv
            ON pv.product_id = p.id
        WHERE p.in_store = true
          AND pv.confirmed = false
          AND COALESCE(pv.source, '') NOT IN ('instore_playlist', 'LEGACY_KIOSK')
          AND pv.youtube_id IS NOT NULL
          AND NOT EXISTS (
                SELECT 1
                FROM product_videos curated
                WHERE curated.product_id = p.id
                  AND (
                        curated.source = 'instore_playlist'
                        OR (curated.source = 'LEGACY_KIOSK' AND curated.confirmed = true)
                  )
          )
    """
    params: list[object] = []
    if product_filter:
        sql += """
          AND (p.id::text = %s OR p.item_number::text = %s)
        """
        params.extend([product_filter, product_filter])
    sql += """
        ORDER BY p.name, p.id, pv.id
    """
    return sql, params


def fetch_rows(product_filter: str | None) -> list[tuple]:
    sql, params = build_query(product_filter)
    with psycopg.connect(DB_URL) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def group_rows(rows: Iterable[tuple]) -> list[dict]:
    products: list[dict] = []
    current_product_id: str | None = None
    current_product: dict | None = None

    for row in rows:
        product_id, item_number, product_name, brand_name, video_id, youtube_id, title, url = row
        if product_id != current_product_id:
            if current_product is not None:
                products.append(current_product)
            current_product_id = product_id
            current_product = {
                "product_id": product_id,
                "item_number": item_number,
                "name": product_name,
                "brand": brand_name,
                "videos": [],
            }

        assert current_product is not None
        current_product["videos"].append(
            {
                "video_id": video_id,
                "youtube_id": youtube_id,
                "title": title,
                "url": url,
            }
        )

    if current_product is not None:
        products.append(current_product)

    return products


def compute_signals(
    *,
    product_name: str | None,
    item_number: object | None,
    brand_name: str | None,
    title: str | None,
    channel: str | None,
) -> dict:
    normalized_title = normalize_text(title)
    title_tokens = set(tokenize(title))
    name_tokens = filtered_name_tokens(product_name)
    matched_name_tokens = sum(1 for token in name_tokens if token in title_tokens)
    name_overlap_ratio = (matched_name_tokens / len(name_tokens)) if name_tokens else 0.0

    item_value = item_number_text(item_number)
    item_match = bool(item_value) and item_value.lower() in normalized_title

    brand_token_list = brand_tokens(brand_name)
    brand_match = any(token in title_tokens for token in brand_token_list)

    fireworks_ctx = title_has_fireworks_context(normalized_title)
    blocklist_hit = title_blocklist_hit(normalized_title)

    channel_tokens = set(tokenize(channel))
    channel_hit = distinctive_channel_hit(channel, brand_token_list + name_tokens)
    channel_match = bool(channel_hit or channel_tokens.intersection(set(brand_token_list + name_tokens)))
    official_channel = False
    if channel:
        channel_norm = normalize_text(channel)
        channel_compact = channel_norm.replace(" ", "")
        official_channel = any(official in channel_compact for official in KNOWN_OFFICIAL)

    return {
        "name_overlap_ratio": name_overlap_ratio,
        "item_match": item_match,
        "brand_match": brand_match,
        "fireworks_ctx": fireworks_ctx,
        "blocklist_hit": blocklist_hit,
        "channel_match": channel_match,
        "channel_hit": channel_hit,
        "official_channel": official_channel,
    }


def score_duration(duration: int | None) -> tuple[int, str | None, bool]:
    if duration is None:
        return 0, None, False
    if duration < 5:
        return DURATION_SHORT_PENALTY, "duration <5s", False
    if duration <= 180:
        return DURATION_GOOD_BONUS, "duration 5..180s", False
    if duration <= 360:
        return DURATION_MEDIUM_PENALTY, "duration 181..360s", False
    return DURATION_LONG_PENALTY, "likely compilation", True


def score_video(product: dict, video: dict, metadata: dict | None) -> dict:
    signals = compute_signals(
        product_name=product.get("name"),
        item_number=product.get("item_number"),
        brand_name=product.get("brand"),
        title=video.get("title"),
        channel=(metadata or {}).get("channel"),
    )

    score = 0
    reasons: list[str] = []
    hard_quarantine = False

    if metadata and metadata.get("status") == "dead":
        return {
            **video,
            "status": "dead",
            "channel": None,
            "channel_id": None,
            "duration": None,
            "view_count": None,
            "upload_date": None,
            "availability": None,
            "live_status": None,
            "score": -999,
            "reason": "unavailable on youtube",
            "bucket": "QUARANTINE",
            **signals,
        }

    if signals["item_match"]:
        score += ITEM_MATCH_BONUS
        reasons.append("item# in title")

    if signals["name_overlap_ratio"] >= NAME_OVERLAP_CONFIRM_MIN:
        score += NAME_OVERLAP_GOOD_BONUS
        reasons.append(f"name overlap {signals['name_overlap_ratio']:.2f}")
    elif signals["name_overlap_ratio"] == 0:
        score += NAME_OVERLAP_ZERO_PENALTY
        reasons.append("no name overlap")

    if signals["brand_match"]:
        score += 5
        reasons.append("brand match in title")

    if signals["fireworks_ctx"]:
        score += FIREWORKS_CONTEXT_BONUS
        reasons.append("fireworks context")

    if signals["blocklist_hit"]:
        score += BLOCKLIST_PENALTY
        reasons.append(f"blocklist hit: {signals['blocklist_hit']}")

    if signals["channel_match"]:
        score += CHANNEL_MATCH_BONUS
        reasons.append(f"channel match: {signals['channel_hit'] or 'token'}")
    if signals["official_channel"]:
        score += OFFICIAL_CHANNEL_BONUS
        reasons.append("known official channel")

    duration = None
    view_count = None
    upload_date = None
    availability = None
    live_status = None
    channel = None
    channel_id = None
    title = video.get("title")
    status = metadata.get("status") if metadata else None

    if metadata and status == "ok":
        channel = metadata.get("channel")
        channel_id = metadata.get("channel_id")
        duration = metadata.get("duration")
        view_count = metadata.get("view_count")
        upload_date = metadata.get("upload_date")
        availability = metadata.get("availability")
        live_status = metadata.get("live_status")

        duration_delta, duration_reason, duration_hard = score_duration(duration)
        score += duration_delta
        if duration_reason:
            reasons.append(duration_reason)
        hard_quarantine = hard_quarantine or duration_hard
    else:
        hard_quarantine = False

    if signals["blocklist_hit"] and signals["name_overlap_ratio"] <= NAME_OVERLAP_LOW_MAX:
        score += BLOCKLIST_LOW_OVERLAP_PENALTY
        hard_quarantine = True
        reasons.append("blocklist + low overlap")

    if signals["name_overlap_ratio"] == 0:
        hard_quarantine = True
    if metadata and status == "ok" and duration is not None and duration > 360:
        hard_quarantine = True

    if score >= CONFIRM_THRESHOLD and signals["name_overlap_ratio"] > 0:
        bucket = "CONFIRM-CANDIDATE"
    elif hard_quarantine or score < QUAR_THRESHOLD:
        bucket = "QUARANTINE"
    else:
        bucket = "UNCERTAIN"

    if not reasons:
        reasons.append("weak signal only")

    return {
        **video,
        "status": status or "unknown",
        "channel": channel,
        "channel_id": channel_id,
        "duration": duration,
        "view_count": view_count,
        "upload_date": upload_date,
        "availability": availability,
        "live_status": live_status,
        "score": score,
        "reason": "; ".join(reasons),
        "bucket": bucket,
        **signals,
    }


def recommend_for_product(scored_videos: list[dict]) -> dict | None:
    if not scored_videos:
        return None
    top = max(scored_videos, key=lambda item: (item["score"], item["name_overlap_ratio"]))
    if top["score"] >= CONFIRM_THRESHOLD and top["name_overlap_ratio"] > 0:
        return {
            "video_id": top["video_id"],
            "youtube_id": top["youtube_id"],
            "title": top["title"],
            "score": top["score"],
            "channel": top.get("channel"),
            "duration": top.get("duration"),
        }
    return None


def format_duration(duration: int | None) -> str:
    return "NA" if duration is None else f"{duration}s"


def format_views(view_count: int | None) -> str:
    return "NA" if view_count is None else f"{view_count:,}"


def escape_md(value: object | None) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def truncate_text(value: str | None, limit: int = 70) -> str:
    if not value:
        return ""
    text = value.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def write_outputs(products: list[dict]) -> dict[str, int]:
    _write_json_file(JSON_OUT, products)

    totals = {"RECOMMEND": 0, "CONFIRM-CANDIDATE": 0, "QUARANTINE": 0, "UNCERTAIN": 0}
    lines: list[str] = []
    total_videos = 0

    for product in products:
        total_videos += len(product["all"])
        totals["RECOMMEND"] += 1 if product["recommend"] else 0
        totals["CONFIRM-CANDIDATE"] += sum(1 for video in product["all"] if video["bucket"] == "CONFIRM-CANDIDATE")
        totals["QUARANTINE"] += len(product["quarantine"])
        totals["UNCERTAIN"] += len(product["uncertain"])

    lines.append("# Video Cascade T2")
    lines.append("")
    lines.append(f"- Products: {len(products)}")
    lines.append(f"- Videos reviewed: {total_videos}")
    lines.append(f"- RECOMMEND: {totals['RECOMMEND']}")
    lines.append(f"- CONFIRM-CANDIDATE: {totals['CONFIRM-CANDIDATE']}")
    lines.append(f"- QUARANTINE: {totals['QUARANTINE']}")
    lines.append(f"- UNCERTAIN: {totals['UNCERTAIN']}")
    lines.append("")

    for product in products:
        header_id = product["item_number"] or product["product_id"]
        lines.append(f"## {escape_md(product['name'])} ({escape_md(header_id)})")
        lines.append("")
        lines.append(f"- Brand: {escape_md(product['brand'])}")
        if product["recommend"]:
            rec = product["recommend"]
            lines.append(
                "- Recommend: "
                f"{escape_md(rec['youtube_id'])} | {escape_md(rec['title'])} | "
                f"{escape_md(rec.get('channel'))} | {format_duration(rec.get('duration'))} | "
                f"score {rec['score']}"
            )
        else:
            lines.append("- Recommend: NONE (needs sourcing / manual)")
        lines.append("")
        lines.append("| bucket | score | title | channel | duration | views | reason |")
        lines.append("| --- | ---: | --- | --- | ---: | ---: | --- |")
        for video in product["all"]:
            lines.append(
                "| {bucket} | {score} | {title} | {channel} | {duration} | {views} | {reason} |".format(
                    bucket=escape_md(video["bucket"]),
                    score=video["score"],
                    title=escape_md(truncate_text(video.get("title"), 72)),
                    channel=escape_md(truncate_text(video.get("channel"), 28)),
                    duration=escape_md(format_duration(video.get("duration"))),
                    views=escape_md(format_views(video.get("view_count"))),
                    reason=escape_md(truncate_text(video.get("reason"), 90)),
                )
            )
        lines.append("")

    MD_OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return totals


def build_products(rows: list[tuple], metadata_cache: dict[str, dict]) -> list[dict]:
    products = group_rows(rows)
    output: list[dict] = []

    for product in products:
        scored_videos: list[dict] = []
        for video in product["videos"]:
            metadata = metadata_cache.get(video["youtube_id"])
            scored_videos.append(score_video(product, video, metadata))

        scored_videos.sort(key=lambda item: (-item["score"], item["video_id"]))
        recommend = recommend_for_product(scored_videos)

        quarantine: list[dict] = []
        uncertain: list[dict] = []
        for video in scored_videos:
            if recommend and video["video_id"] == recommend["video_id"]:
                continue
            if video["bucket"] == "QUARANTINE":
                quarantine.append(video)
            elif video["bucket"] == "UNCERTAIN":
                uncertain.append(video)

        output.append(
            {
                "product_id": product["product_id"],
                "item_number": product["item_number"],
                "name": product["name"],
                "brand": product["brand"],
                "recommend": recommend,
                "quarantine": quarantine,
                "uncertain": uncertain,
                "all": scored_videos,
            }
        )

    return output


def fetch_all_metadata(products: list[dict], *, refresh: bool, no_fetch: bool) -> dict[str, dict]:
    cache = load_cache()
    youtube_ids: list[str] = []
    seen: set[str] = set()
    for product in products:
        for video in product["videos"]:
            youtube_id = video["youtube_id"]
            if youtube_id and youtube_id not in seen:
                seen.add(youtube_id)
                youtube_ids.append(youtube_id)
    return fetch_metadata(youtube_ids, cache, refresh=refresh, no_fetch=no_fetch)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tier 2 read-only audit cascade for in-store videos")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch yt-dlp metadata for all ids")
    parser.add_argument("--product", default=None, help="Optional product id or item number filter")
    parser.add_argument("--no-fetch", action="store_true", help="Use only cached metadata and skip yt-dlp")
    return parser.parse_args()


def print_totals(totals: dict[str, int], products: list[dict]) -> None:
    print(f"PRODUCTS: {len(products)}", file=sys.stderr)
    print(f"RECOMMEND: {totals['RECOMMEND']}", file=sys.stderr)
    print(f"CONFIRM-CANDIDATE: {totals['CONFIRM-CANDIDATE']}", file=sys.stderr)
    print(f"QUARANTINE: {totals['QUARANTINE']}", file=sys.stderr)
    print(f"UNCERTAIN: {totals['UNCERTAIN']}", file=sys.stderr)


def main() -> None:
    args = parse_args()
    rows = fetch_rows(args.product)
    raw_products = group_rows(rows)
    metadata_cache = fetch_all_metadata(raw_products, refresh=args.refresh, no_fetch=args.no_fetch)
    products = build_products(rows, metadata_cache)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    totals = write_outputs(products)
    print_totals(totals, products)


if __name__ == "__main__":
    main()
