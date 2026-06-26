#!/usr/bin/env python3
"""Layer-2 scripted online enricher -> evidence ledger.

This script searches retailer/brand pages for in-store products by SKU + name,
extracts candidate facts, and appends them to the evidence ledger. It does not
write to the products database.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import psycopg
import requests
from bs4 import BeautifulSoup

from evidence_ledger import add_records, apply as apply_ledger, load_ledger, verify as verify_ledger, DSN, FILLABLE


AUDIT_DIR = Path(__file__).resolve().parent
LEDGER_PATH = AUDIT_DIR / "evidence_ledger.json"
RUN_LOG_PATH = AUDIT_DIR / "scrape_enrich_run.json"
PRODUCT_RESEARCH_DIR = AUDIT_DIR / "product_research"

SEARCH_URL = "https://html.duckduckgo.com/html/"
FETCH_TIMEOUT_SECONDS = 15
SEARCH_LIMIT = 6
PAGE_SLEEP_SECONDS = 1.0
PRODUCT_SLEEP_MIN = 2.0
PRODUCT_SLEEP_MAX = 4.0
DUCKDUCKGO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

IGNORED_DOMAIN_SNIPPETS = {
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.com",
    "pinterest.com",
    "reddit.com",
    "wikipedia.org",
    "ebay.com",
    "amazon.com",
    "amazon.",
    "darbydental.com",
    "armyproperty.com",
    "aztechydraulics.com",
    "govets.com",
    "grainger.com",
    "hearth.com",
    "globalindustrial.com",
    "instagram.com",
    "midwestbusparts.com",
    "radiatorsupplyhouse.com",
    "taobao.com",
    "tiktok.com",
    "truckpartsline.com",
    "trewautomation.com",
    "vimeo.com",
    "zoro.com",
}

FIREWORKS_CONTEXT_TERMS = {
    "firework",
    "fireworks",
    "pyro",
    "pyrotechnic",
    "cake",
    "fountain",
    "mortar",
    "shell",
    "artillery",
    "roman candle",
    "sparkler",
    "shots",
    "shot",
    "wholesale fireworks",
}

RESEARCH_FIELDS = tuple(
    field for field in ("shot_count", "duration_seconds", "effects", "packing", "description") if field in FILLABLE
)
FIELD_ORDER = {field: index for index, field in enumerate(RESEARCH_FIELDS)}
INT_FIELDS = {"shot_count", "duration_seconds"}

SKU_DIGITS_RE = re.compile(r"\d+")
BARCODE_RE = re.compile(r"\b(\d{11,13})\b")
SHOT_COUNT_RE = re.compile(r"(?<!\d)(\d{1,4})\s*(?:shots?|shot count|breaks?)\b", re.IGNORECASE)
PACKING_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
LABEL_SPLIT_RE = re.compile(r"\s*[:\-]\s*")
WORD_RE = re.compile(r"[A-Za-z0-9]+")
PARAGRAPH_WORD_LIMIT = 12
EFFECT_SIGNAL_RE = re.compile(
    r"\b("
    r"brocade|chrysanthemum|chrys\.?|crackle|crackling|dahlia|glitter|strobe|willow|"
    r"pearl|pearls|palm|peony|comet|tail|tails|mine|mines|bouquet|wave|spinner|"
    r"whistle|whistles|report|reports|titanium|dragon|crossette|horsetail|fish|"
    r"red|green|blue|purple|yellow|gold|silver|white|orange|lemon"
    r")\b",
    re.IGNORECASE,
)
EFFECT_JUNK_RE = re.compile(
    r"\b("
    r"effects?\s+holders?|holder|add to cart|quick fuse|privacy|shipping|loyalty|"
    r"contains a bundle|ultimate .* experience|facebook|iframe|plugin"
    r")\b",
    re.IGNORECASE,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def normalize_space(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_item_number(value: Any) -> str:
    return normalize_space(value).upper()


def db_field_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def slugify_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_space(value).lower()).strip()


def filename_slug(value: Any, fallback: str = "product") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", normalize_space(value)).strip("._-")
    return (slug or fallback)[:120]


def tokenize(value: Any) -> set[str]:
    return {token for token in WORD_RE.findall(normalize_space(value).lower()) if token}


def clean_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def is_ignored_domain(url: str) -> bool:
    domain = clean_domain(url)
    return any(snippet in domain for snippet in IGNORED_DOMAIN_SNIPPETS)


def current_utc_date() -> str:
    return now_utc().date().isoformat()


def product_key(product_id: Any, item_number: Any) -> str:
    item = normalize_item_number(item_number)
    return item or str(product_id or "").strip()


def load_today_seen_product_keys() -> set[str]:
    ledger = load_json(LEDGER_PATH, [])
    seen: set[str] = set()
    if not isinstance(ledger, list):
        return seen
    today = current_utc_date()
    for rec in ledger:
        if not isinstance(rec, dict):
            continue
        captured_at = normalize_space(rec.get("captured_at"))
        if not captured_at.startswith(today):
            continue
        key = product_key(rec.get("product_id"), rec.get("item_number"))
        if key:
            seen.add(key)
    return seen


def fetch_products(
    limit: int | None,
    only_skus: set[str] | None,
    only_product_ids: set[str] | None = None,
    skip_product_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    sql_text = """
        SELECT
            p.id,
            p.item_number::text AS item_number,
            p.name,
            p.brand_id,
            COALESCE(b.name, '') AS brand_name,
            p.shot_count,
            p.duration_seconds,
            p.effects,
            p.packing,
            p.description,
            COALESCE(c.name, '') AS category_name
        FROM products p
        LEFT JOIN product_brands b
            ON b.id = p.brand_id
        LEFT JOIN product_categories c
            ON c.id = p.category_id
        WHERE p.in_store = true
        ORDER BY p.id
    """
    rows: list[dict[str, Any]] = []
    with psycopg.connect(DSN) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql_text)
            for row in cur.fetchall():
                item_number = normalize_item_number(row[1])
                if only_skus and item_number not in only_skus:
                    continue
                if only_product_ids and str(row[0]) not in only_product_ids:
                    continue
                key = product_key(row[0], item_number)
                if skip_product_keys and key in skip_product_keys:
                    continue
                current_values = {
                    "shot_count": row[5],
                    "duration_seconds": row[6],
                    "effects": row[7],
                    "packing": row[8],
                    "description": row[9],
                }
                target_fields = [field for field in RESEARCH_FIELDS if db_field_missing(current_values[field])]
                if not target_fields:
                    continue
                rows.append(
                    {
                        "id": row[0],
                        "item_number": item_number,
                        "name": normalize_space(row[2]),
                        "brand_id": row[3],
                        "brand_name": normalize_space(row[4]),
                        "category_name": normalize_space(row[10]),
                        "current_values": current_values,
                        "target_fields": target_fields,
                    }
                )
    if limit is not None:
        rows = rows[:limit]
    return rows


def ddg_search(session: requests.Session, query: str) -> list[str]:
    response = session.get(
        SEARCH_URL,
        params={"q": query},
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": DUCKDUCKGO_UA},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a.result__a"):
        href = anchor.get("href")
        if not href:
            continue
        real_url = decode_ddg_url(href)
        if not real_url:
            continue
        domain = clean_domain(real_url)
        if not domain:
            continue
        if domain in seen:
            continue
        seen.add(domain)
        urls.append(real_url)
        if len(urls) >= SEARCH_LIMIT:
            break
    return urls


def decode_ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            return unquote(query["uddg"][0])
        return href
    parsed = urlparse(urljoin("https://html.duckduckgo.com", href))
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    if parsed.scheme and parsed.netloc:
        return parsed.geturl()
    return ""


def page_looks_html(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    return "html" in content_type or "text/" in content_type or "xhtml" in content_type


def fetch_page(session: requests.Session, url: str) -> tuple[str | None, str | None]:
    for attempt in range(2):
        try:
            response = session.get(
                url,
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": DUCKDUCKGO_UA},
                allow_redirects=True,
            )
            response.raise_for_status()
            if not page_looks_html(response):
                time.sleep(PAGE_SLEEP_SECONDS)
                return None, None
            result = (response.url, response.text)
        except requests.RequestException:
            if attempt == 0:
                time.sleep(PAGE_SLEEP_SECONDS)
                continue
            time.sleep(PAGE_SLEEP_SECONDS)
            return None, None
        time.sleep(PAGE_SLEEP_SECONDS)
        return result
    return None, None


def parse_jsonld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        payload = normalize_space(script.string or script.get_text())
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        objects.extend(extract_product_objects(data))
    return objects


def extract_product_objects(data: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        type_value = data.get("@type")
        if is_product_type(type_value):
            items.append(data)
        graph = data.get("@graph")
        if isinstance(graph, list):
            for entry in graph:
                items.extend(extract_product_objects(entry))
        for key in ("mainEntity", "item", "product"):
            items.extend(extract_product_objects(data.get(key)))
    elif isinstance(data, list):
        for entry in data:
            items.extend(extract_product_objects(entry))
    return items


def is_product_type(type_value: Any) -> bool:
    if isinstance(type_value, str):
        return type_value.lower() == "product"
    if isinstance(type_value, list):
        return any(isinstance(item, str) and item.lower() == "product" for item in type_value)
    return False


def extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    text = soup.get_text("\n", strip=True)
    blocks: list[str] = []
    for raw_line in text.splitlines():
        line = normalize_space(raw_line)
        if line:
            blocks.append(line)
    return blocks


def page_text_bundle(soup: BeautifulSoup) -> str:
    parts = [
        normalize_space(soup.title.get_text(" ", strip=True)) if soup.title else "",
        normalize_space(soup.find("meta", attrs={"property": "og:title"}).get("content"))
        if soup.find("meta", attrs={"property": "og:title"})
        else "",
        normalize_space(soup.find("meta", attrs={"name": "description"}).get("content"))
        if soup.find("meta", attrs={"name": "description"})
        else "",
        normalize_space(soup.find("meta", attrs={"property": "og:description"}).get("content"))
        if soup.find("meta", attrs={"property": "og:description"})
        else "",
        " ".join(extract_text_blocks(soup)),
    ]
    return normalize_space(" ".join(part for part in parts if part))


def page_visible_lines(soup: BeautifulSoup) -> list[str]:
    lines = extract_text_blocks(soup)
    return [line for line in lines if line and len(line) < 500]


def sku_digits(sku: str) -> str:
    return "".join(SKU_DIGITS_RE.findall(sku))


def has_fireworks_context(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in FIREWORKS_CONTEXT_TERMS)


def identity_for_page(
    soup: BeautifulSoup,
    sku: str,
    name: str,
    brand_name: str,
    known: dict[str, Any] | None = None,
) -> tuple[str, float]:
    bundle = page_text_bundle(soup)
    bundle_upper = bundle.upper()
    sku_upper = normalize_item_number(sku)
    numeric_sku = sku_digits(sku_upper)

    name_tokens = tokenize(name)
    brand_tokens = tokenize(brand_name)
    page_tokens = tokenize(bundle)
    name_present = bool(name_tokens) and len(name_tokens & page_tokens) >= max(1, len(name_tokens) // 2)
    brand_present = bool(brand_tokens) and bool(brand_tokens & page_tokens)
    fireworks_context = has_fireworks_context(bundle)

    if sku_upper and sku_upper in bundle_upper and (fireworks_context or name_present or brand_present):
        return f"exact SKU found in page text ({sku_upper})", 0.9

    for barcode in BARCODE_RE.findall(bundle):
        if numeric_sku and barcode.endswith(numeric_sku) and (fireworks_context or name_present or brand_present):
            return f"barcode {barcode} contains SKU digits {numeric_sku}", 0.9

    if name_present and brand_present and fireworks_context:
        known = known or {}
        shot = clean_positive_int(known.get("shot_count"), "shot_count")
        duration = clean_positive_int(known.get("duration_seconds"), "duration_seconds")
        category_tokens = tokenize(known.get("category_name"))
        category_present = bool(category_tokens) and bool(category_tokens & page_tokens)
        shot_present = bool(shot) and re.search(rf"\b{shot}\s*(?:shots?|shot count|breaks?)\b", bundle, re.I)
        duration_present = bool(duration) and re.search(rf"\b{duration}\s*(?:sec(?:onds?)?|seconds?|secs?)\b", bundle, re.I)
        if shot_present or duration_present or category_present:
            matched = []
            if shot_present:
                matched.append("shot_count")
            if duration_present:
                matched.append("duration")
            if category_present:
                matched.append("category")
            return "strong product identity via name+brand+known " + "+".join(matched), 0.85
        return "name+brand match, SKU not found", 0.5

    if name_tokens:
        overlap = len(name_tokens & page_tokens) / max(1, len(name_tokens))
        if overlap >= 0.4:
            return "loose name match", 0.3

    return "loose name match", 0.3


def jsonld_iter_values(obj: dict[str, Any], keys: Iterable[str]) -> Iterable[Any]:
    for key in keys:
        value = obj.get(key)
        if value is not None:
            yield value


def additional_properties(obj: dict[str, Any]) -> list[dict[str, Any]]:
    value = obj.get("additionalProperty")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def extract_jsonld_value(products: list[dict[str, Any]], field: str) -> tuple[Any | None, str | None, bool]:
    for obj in products:
        if field == "description":
            description = clean_description(obj.get("description"))
            if description:
                return description, "jsonld.description", False

        if field == "shot_count":
            for candidate in jsonld_iter_values(obj, ("numberOfItems", "numberOfPieces", "shots", "shotCount")):
                parsed = clean_positive_int(candidate, field)
                if parsed is not None:
                    return parsed, "jsonld", False
        elif field == "duration_seconds":
            for candidate in jsonld_iter_values(obj, ("duration", "durationSeconds", "runTime")):
                parsed = parse_duration_seconds(candidate)
                if parsed is not None:
                    return parsed, "jsonld", False
        elif field == "effects":
            from_props = extract_from_additional_properties(obj, {"effects", "color", "colors", "effect", "style"})
            if from_props:
                return from_props, "jsonld.effects", False
            for candidate in jsonld_iter_values(obj, ("keywords", "additionalType", "description")):
                parsed = clean_effects(candidate)
                if parsed is not None:
                    return parsed, "jsonld", False
        elif field == "packing":
            from_props = extract_from_additional_properties(
                obj, {"packing", "package", "pack", "case pack", "casepack", "case quantity"}
            )
            if from_props:
                packed = clean_packing(from_props)
                if packed is not None:
                    return packed, "jsonld.packing", False
            for candidate in jsonld_iter_values(obj, ("packaging", "isPackaged", "packageType")):
                packed = clean_packing(candidate)
                if packed is not None:
                    return packed, "jsonld", False
    return None, None, False


def extract_from_additional_properties(obj: dict[str, Any], names: set[str]) -> str | None:
    for entry in additional_properties(obj):
        label = normalize_space(entry.get("name")).lower()
        if not label:
            continue
        compact_label = re.sub(r"\s+", " ", label)
        if not any(name in compact_label for name in names):
            continue
        value = entry.get("value")
        if value is None:
            value = entry.get("valueText")
        if isinstance(value, list):
            joined = join_text_list(value)
            if joined:
                return joined
        else:
            text = normalize_space(value)
            if text:
                return text
        nested = entry.get("valueReference")
        if isinstance(nested, dict):
            nested_text = normalize_space(nested.get("name") or nested.get("value"))
            if nested_text:
                return nested_text
    return None


def join_text_list(value: list[Any]) -> str | None:
    pieces = [normalize_space(item) for item in value if normalize_space(item)]
    if not pieces:
        return None
    return ", ".join(pieces)


def clean_positive_int(value: Any, field: str) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
    else:
        text = normalize_space(value)
        if not text:
            return None
        match = re.search(r"\d+", text)
        if not match:
            return None
        parsed = int(match.group(0))
    if parsed <= 0:
        return None
    if field == "shot_count" and parsed >= 2000:
        return None
    if field == "duration_seconds" and parsed > 600:
        return None
    return parsed


def parse_duration_seconds(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        return parsed if 0 < parsed <= 600 else None

    text = normalize_space(value)
    if not text:
        return None

    iso_match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
        text,
        flags=re.IGNORECASE,
    )
    if iso_match:
        hours = int(iso_match.group(1) or 0)
        minutes = int(iso_match.group(2) or 0)
        seconds = float(iso_match.group(3) or 0)
        parsed = int(hours * 3600 + minutes * 60 + seconds)
        return parsed if 0 < parsed <= 600 else None

    match = re.search(r"(?<!\d)(\d{1,4})\s*(?:sec(?:onds?)?|seconds?|secs?|s)\b", text, re.IGNORECASE)
    if match:
        parsed = int(match.group(1))
        return parsed if 0 < parsed <= 600 else None

    match = re.search(r"duration[:\s]+(\d{1,4})\b", text, re.IGNORECASE)
    if match:
        parsed = int(match.group(1))
        return parsed if 0 < parsed <= 600 else None
    return None


def clean_effects(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        text = join_text_list(value)
    else:
        text = normalize_space(value)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    if not text:
        return None
    if text.lower() in {"effect", "effects", "color", "colors", "performance"}:
        return None
    if EFFECT_JUNK_RE.search(text):
        return None
    if len(text) > 300:
        text = text[:300].rstrip(" ,;")
    words = text.split()
    if len(words) > PARAGRAPH_WORD_LIMIT and "," not in text:
        return None
    if not EFFECT_SIGNAL_RE.search(text):
        return None
    if len(words) > 28 and text.count(",") < 2:
        return None
    return text


def clean_packing(value: Any) -> str | None:
    text = normalize_space(value)
    if not text:
        return None
    match = PACKING_RE.search(text)
    if not match:
        return None
    packed = f"{int(match.group(1))}/{int(match.group(2))}"
    return packed if re.fullmatch(r"\d+/\d+", packed) else None


def clean_description(value: Any) -> str | None:
    text = normalize_space(value)
    if not text or len(text) < 20:
        return None
    if clean_packing(text):
        return None
    return text[:1000]


def extract_regex_value(lines: list[str], field: str) -> tuple[Any | None, str | None, bool]:
    if field == "shot_count":
        for line in lines:
            match = SHOT_COUNT_RE.search(line)
            if match:
                parsed = clean_positive_int(match.group(1), field)
                if parsed is not None:
                    return parsed, "regex", True
    elif field == "duration_seconds":
        for line in lines:
            parsed = parse_duration_seconds(line)
            if parsed is not None:
                return parsed, "regex", True
    elif field == "effects":
        for line in lines:
            label, value = split_label_value(line)
            if label and label in {"effects", "color", "colors"}:
                cleaned = clean_effects(value)
                if cleaned is not None:
                    return cleaned, "labelled", False
        for line in lines:
            if "effects" in line.lower() or "colors" in line.lower():
                candidate = normalize_space(line)
                candidate = LABEL_SPLIT_RE.split(candidate, maxsplit=1)[-1].strip()
                cleaned = clean_effects(candidate)
                if cleaned is not None:
                    return cleaned, "labelled", False
    elif field == "packing":
        for line in lines:
            if "pack" not in line.lower() and "case" not in line.lower():
                continue
            match = PACKING_RE.search(line)
            if match:
                packed = f"{int(match.group(1))}/{int(match.group(2))}"
                if re.fullmatch(r"\d+/\d+", packed):
                    return packed, "regex", True
    elif field == "description":
        for line in lines:
            label, value = split_label_value(line)
            if label and label in {"description", "product description", "details", "overview"}:
                cleaned = clean_description(value)
                if cleaned is not None:
                    return cleaned, "labelled", False
    return None, None, False


def split_label_value(line: str) -> tuple[str, str]:
    parts = LABEL_SPLIT_RE.split(line, maxsplit=1)
    if len(parts) != 2:
        return "", ""
    return normalize_space(parts[0]).lower(), normalize_space(parts[1])


def extract_meta_description(soup: BeautifulSoup) -> str | None:
    for selector, attr in (
        (("meta", {"name": "description"}), "content"),
        (("meta", {"property": "og:description"}), "content"),
        (("meta", {"name": "twitter:description"}), "content"),
    ):
        tag = soup.find(*selector)
        if not tag:
            continue
        value = clean_description(tag.get(attr))
        if value is not None:
            return value
    return None


def extract_description_from_text(lines: list[str], name: str) -> str | None:
    name_tokens = tokenize(name)
    for line in lines:
        cleaned = normalize_space(line)
        if len(cleaned) < 20:
            continue
        if clean_packing(cleaned):
            continue
        if name_tokens and len(tokenize(cleaned) & name_tokens) >= max(1, len(name_tokens) // 2):
            continue
        if len(cleaned.split()) > 50:
            continue
        return cleaned[:1000]
    return None


def build_records_from_page(
    page_url: str,
    html_text: str,
    sku: str,
    name: str,
    brand_name: str,
    product_id: str,
    known: dict[str, Any],
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    identity_check, base_confidence = identity_for_page(soup, sku, name, brand_name, known)
    jsonld_products = parse_jsonld_objects(soup)
    lines = page_visible_lines(soup)
    page_domain = clean_domain(page_url)
    records: list[dict[str, Any]] = []

    for field in RESEARCH_FIELDS:
        value: Any | None = None
        source_label = ""
        loose = False

        jsonld_value, jsonld_source, jsonld_loose = extract_jsonld_value(jsonld_products, field)
        if jsonld_value is not None:
            value = jsonld_value
            source_label = jsonld_source or "jsonld"
            loose = jsonld_loose
        else:
            regex_value, regex_source, regex_loose = extract_regex_value(lines, field)
            if regex_value is not None:
                value = regex_value
                source_label = regex_source or "regex"
                loose = regex_loose

        if value is None and field == "description":
            meta_value = extract_meta_description(soup)
            if meta_value is not None:
                value = meta_value
                source_label = "meta.description"
            else:
                text_value = extract_description_from_text(lines, name)
                if text_value is not None:
                    value = text_value
                    source_label = "text.description"

        if value is None:
            continue

        if field in INT_FIELDS:
            value = clean_positive_int(value, field)
        elif field == "packing":
            value = clean_packing(value)
        elif field == "effects":
            value = clean_effects(value)
        elif field == "description":
            value = clean_description(value)

        if value is None:
            continue

        confidence = base_confidence - (0.1 if loose else 0.0)
        confidence = max(0.0, min(1.0, confidence))
        records.append(
            {
                "product_id": product_id,
                "item_number": sku,
                "name": name,
                "field": field,
                "value": value,
                "source": f"{page_domain} ({source_label})" if source_label else page_domain,
                "url": page_url,
                "confidence": confidence,
                "identity_check": identity_check,
            }
        )
    return records


def search_queries_for_product(item_number: str, name: str, brand_name: str, product: dict[str, Any] | None = None) -> list[str]:
    product = product or {}
    current = product.get("current_values", {}) if isinstance(product.get("current_values"), dict) else {}
    category_name = normalize_space(product.get("category_name"))
    queries: list[str] = []
    if item_number:
        queries.append(f'"{item_number}" {name} fireworks'.strip())
    if brand_name:
        queries.append(f"{name} {brand_name} fireworks".strip())
    queries.append(f'"{name}" fireworks'.strip())
    shot = current.get("shot_count")
    duration = current.get("duration_seconds")
    if shot:
        queries.append(f'"{name}" "{shot} shot" fireworks'.strip())
        if brand_name:
            queries.append(f'"{name}" "{shot} shot" {brand_name} fireworks'.strip())
    if duration:
        queries.append(f'"{name}" "{duration} seconds" fireworks'.strip())
    if category_name:
        queries.append(f'"{name}" {category_name} fireworks'.strip())
    effects = normalize_space(current.get("effects"))
    if effects:
        effect_terms = " ".join(re.findall(r"[A-Za-z]+", effects)[:5])
        if effect_terms:
            queries.append(f'"{name}" {effect_terms} fireworks'.strip())
    deduped: list[str] = []
    seen = set()
    for query in queries:
        normalized = query.lower()
        if query and normalized not in seen:
            deduped.append(query)
            seen.add(normalized)
    return deduped


def fetch_candidate_urls(session: requests.Session, queries: list[str]) -> list[str]:
    urls: list[str] = []
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    for index, query in enumerate(queries):
        if index > 0 and len(urls) >= 3:
            break
        try:
            results = ddg_search(session, query)
        except requests.RequestException:
            continue
        if index == 1 and len(urls) >= 3:
            break
        for url in results:
            if is_ignored_domain(url):
                continue
            domain = clean_domain(url)
            if not domain or domain in seen_domains:
                continue
            if url in seen_urls:
                continue
            seen_domains.add(domain)
            seen_urls.add(url)
            urls.append(url)
            if len(urls) >= SEARCH_LIMIT:
                return urls
        if len(urls) >= SEARCH_LIMIT:
            break
    return urls


def process_product(
    session: requests.Session,
    product: dict[str, Any],
    force: bool,
    today_seen: set[str],
) -> dict[str, Any]:
    product_id = str(product["id"])
    item_number = product["item_number"]
    name = product["name"]
    brand_name = product["brand_name"]
    queries = search_queries_for_product(item_number, name, brand_name, product)
    urls_fetched: list[str] = []
    records: list[dict[str, Any]] = []
    fetched_pages = 0

    key = product_key(product_id, item_number)
    display_id = item_number or product_id
    if not force and key in today_seen:
        print(f"{display_id}, {name}, pages=0, fields=skipped")
        return {
            "product_id": product_id,
            "item_number": item_number,
            "name": name,
            "queries": queries,
            "urls_fetched": urls_fetched,
            "records_added": 0,
        }

    candidate_urls = fetch_candidate_urls(session, queries)
    for url in candidate_urls:
        fetched_url, html_text = fetch_page(session, url)
        if not fetched_url or not html_text:
            continue
        urls_fetched.append(fetched_url)
        fetched_pages += 1
        known = {**product.get("current_values", {}), "category_name": product.get("category_name", "")}
        page_records = build_records_from_page(fetched_url, html_text, item_number, name, brand_name, product_id, known)
        records.extend(page_records)

    added = add_records(records) if records else 0
    if not records:
        add_records(
            [
                {
                    "product_id": product_id,
                    "item_number": item_number,
                    "name": name,
                    "field": "description",
                    "value": f"NO_CANDIDATES:{display_id}",
                    "source": "scrape_enrich.no_candidates",
                    "url": "",
                    "confidence": 0,
                    "identity_check": "no candidate records found during product-scoped scrape",
                    "status": "rejected",
                    "rejected_reason": "no candidate records found",
                }
            ]
        )
    fields_found = sorted({rec["field"] for rec in records}, key=lambda field: FIELD_ORDER.get(field, 99))
    print(f"{display_id}, {name}, pages={fetched_pages}, fields={','.join(fields_found)}")
    entry = {
        "product_id": product_id,
        "item_number": item_number,
        "name": name,
        "brand_name": brand_name,
        "target_fields": product.get("target_fields", []),
        "known_values": product.get("current_values", {}),
        "queries": queries,
        "candidate_urls": candidate_urls,
        "urls_fetched": urls_fetched,
        "candidate_records": [
            {
                "field": rec.get("field"),
                "value": rec.get("value"),
                "source": rec.get("source"),
                "url": rec.get("url"),
                "confidence": rec.get("confidence"),
                "identity_check": rec.get("identity_check"),
            }
            for rec in records
        ],
        "records_added": added,
    }
    write_product_research_packet(entry)
    return entry


def write_product_research_packet(entry: dict[str, Any]) -> None:
    """Persist the per-product scratch packet used by the sentry/AI layer."""
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    identity = entry.get("item_number") or entry.get("product_id") or "product"
    name = filename_slug(entry.get("name"), "product")
    path = PRODUCT_RESEARCH_DIR / f"{stamp}_{filename_slug(identity)}_{name}.json"
    write_json(path, entry)


def verify_and_apply_ledger() -> None:
    ledger = load_ledger()
    apply_ledger(verify_ledger(ledger))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scripted online enricher for evidence ledger")
    parser.add_argument("--limit", type=int, default=None, help="process at most N products")
    parser.add_argument(
        "--only-sku",
        default="",
        help="comma-separated SKU list to restrict the run",
    )
    parser.add_argument(
        "--only-product-id",
        default="",
        help="comma-separated product UUIDs to restrict the run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="reprocess products even if the ledger has records captured today",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="keep looping over the remaining backlog until stopped",
    )
    parser.add_argument(
        "--watch-sleep",
        type=float,
        default=300.0,
        help="seconds to sleep between watch cycles when no backlog remains",
    )
    parser.add_argument(
        "--apply-verified",
        action="store_true",
        help="run evidence verification and apply any newly verified facts after each batch",
    )
    parser.add_argument(
        "--one",
        action="store_true",
        help="process exactly one eligible product and exit",
    )
    parser.add_argument(
        "--json-result",
        action="store_true",
        help="print the final processed product result as JSON",
    )
    return parser.parse_args()


def parse_only_skus(value: str) -> set[str] | None:
    items = {normalize_item_number(part) for part in value.split(",") if normalize_item_number(part)}
    return items or None


def parse_csv(value: str) -> set[str] | None:
    items = {part.strip() for part in value.split(",") if part.strip()}
    return items or None


def main() -> None:
    args = parse_args()
    only_skus = parse_only_skus(args.only_sku)
    only_product_ids = parse_csv(args.only_product_id)
    session = requests.Session()
    session.headers.update({"User-Agent": DUCKDUCKGO_UA})
    run_log: list[dict[str, Any]] = []

    seen_this_run: set[str] = set()

    def eligible_products() -> list[dict[str, Any]]:
        skip = seen_this_run if args.force else (load_today_seen_product_keys() | seen_this_run)
        return fetch_products(args.limit, only_skus, only_product_ids, skip_product_keys=skip)

    while True:
        products = eligible_products()
        if not products:
            write_json(RUN_LOG_PATH, run_log)
            if not args.watch:
                break
            # If the backlog stays empty, keep the watcher alive but idle.
            time.sleep(max(1.0, args.watch_sleep))
            continue

        for index, product in enumerate(products):
            key = product_key(product["id"], product["item_number"])
            try:
                entry = process_product(session, product, args.force, load_today_seen_product_keys() | seen_this_run)
                run_log.append(entry)
                seen_this_run.add(key)
                if args.apply_verified:
                    verify_and_apply_ledger()
            except Exception as exc:  # noqa: BLE001 - keep resumable per spec
                display_id = product["item_number"] or str(product["id"])
                print(f"{display_id}, {product['name']}, pages=0, fields=error")
                run_log.append(
                    {
                        "product_id": str(product["id"]),
                        "item_number": product["item_number"],
                        "name": product["name"],
                        "queries": search_queries_for_product(
                            product["item_number"], product["name"], product["brand_name"], product
                        ),
                        "urls_fetched": [],
                        "records_added": 0,
                        "error": str(exc),
                    }
                )
                seen_this_run.add(key)
            if index < len(products) - 1:
                time.sleep(random.uniform(PRODUCT_SLEEP_MIN, PRODUCT_SLEEP_MAX))
            if args.one:
                break

        write_json(RUN_LOG_PATH, run_log)
        if args.json_result and run_log:
            print("JSON_RESULT " + json.dumps(run_log[-1], ensure_ascii=False, default=json_default))
        if args.one:
            break
        if not args.watch:
            break
        time.sleep(max(1.0, args.watch_sleep))


if __name__ == "__main__":
    main()
