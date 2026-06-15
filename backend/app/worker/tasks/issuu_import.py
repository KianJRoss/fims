"""
Celery task: scrape an Issuu catalog text layer and import products.

For known brands with a custom importer (slug=="jakes"), runs the Jake's
import logic inline. For unknown catalogs, creates ImportRow records for
human review.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
import psycopg

from app.worker.celery_app import celery_app

DB_URL = "postgresql://fims:fims@postgres:5432/fims"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://issuu.com/",
}

_SKU_RE = re.compile(r"SKU[:\s]*(\d{5,10})", re.IGNORECASE)
_BARCODE_RE = re.compile(r"BARCODE[:\s]*(?:USA\s+)?(\d{8,14})")
_SHOTS_RE = re.compile(r"(\d+)\s*shots?", re.IGNORECASE)
_SHELLS_RE = re.compile(r"(\d+)\s*shells?", re.IGNORECASE)
_PACKING_RE = re.compile(r"PACKING[:\s]*([\d/]+)", re.IGNORECASE)

# Jake's TOC
JAKES_SECTION_MAP = [
    ("Assortments",           2,   15),
    ("Artillery Shells",      16,  25),
    ("3-Inch 500 Gram Cakes", 26,  29),
    ("Z Cakes",               30,  35),
    ("500 Gram Cakes",        36,  66),
    ("Show To Go Cartons",    67,  70),
    ("200 Gram Cakes",        71,  96),
    ("Saturn Missiles",       97,  97),
    ("Fountains",             98,  104),
    ("Firecrackers",          105, 123),
    ("Smoke",                 124, 126),
    ("Novelties",             127, 129),
    ("Parachutes",            130, 139),
    ("Rockets & Missiles",    140, 141),
    ("Roman Candles",         142, 145),
    ("Sparklers",             146, 177),
]

_VERB_SPLIT = re.compile(
    r"\b(packs?|features?|delivers?|includes?|brings?|comes?|offers?|provides?|"
    r"shoots?|fires?|fills?|combines?|boasts?|showcases?|explodes?|launches?|"
    r"lights?|creates?|gives?|contains?|blends?)\b",
    re.IGNORECASE,
)
_SKIP_STARTS = re.compile(
    r"^(a |an |the |two |three |four |five |six |seven |eight |nine |ten |"
    r"\d+|large|small|medium|premium|massive|compact|huge|loaded|mid|full|"
    r"mixed|power|patriotic|huge|classic|ultimate|perfect|designed)",
    re.IGNORECASE,
)


class A11yParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_p = False
        self._current_top = 0.0
        self.segments: list[tuple[float, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            attrs_d = dict(attrs)
            if "a11y-paragraph" in attrs_d.get("class", ""):
                self._in_p = True
                m = re.search(r"top:([\d.]+)%", attrs_d.get("style", ""))
                self._current_top = float(m.group(1)) if m else 0.0

    def handle_endtag(self, tag):
        if tag == "p":
            self._in_p = False

    def handle_data(self, data):
        if self._in_p and data.strip():
            self.segments.append((self._current_top, data.strip()))


def fetch_page_text(cdn_id: str, page_num: int) -> list[str]:
    url = f"https://svg.issuu.com/{cdn_id}/page_{page_num}.html"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=20)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    parser = A11yParser()
    parser.feed(resp.text)
    return [t for _, t in sorted(parser.segments, key=lambda x: x[0])]


def resolve_cdn_id(doc_slug: str) -> str | None:
    """Try to resolve a CDN ID from an Issuu document page."""
    try:
        url = f"https://issuu.com/search?q={doc_slug}"
        resp = httpx.get(url, headers=HEADERS, timeout=20)
        m = re.search(r'"revisionId"\s*:\s*"([^"]+)"', resp.text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def jakes_category_for_page(page: int) -> str | None:
    for name, lo, hi in JAKES_SECTION_MAP:
        if lo <= page <= hi:
            return name
    return None


def extract_name_from_description(desc: str | None) -> str | None:
    if not desc:
        return None
    desc = re.sub(r"^DESCRIPTION:\s*", "", desc).strip()
    if _SKIP_STARTS.match(desc):
        return None
    m = _VERB_SPLIT.search(desc)
    if not m:
        return None
    candidate = desc[: m.start()].strip().rstrip(",").strip()
    words = candidate.split()
    if not words or len(words) > 5:
        return None
    if any(w[0].islower() for w in words if w):
        return None
    return candidate or None


def parse_products_from_segments(raw: list[str], page_num: int) -> list[dict]:
    sku_positions: list[tuple[int, str]] = []
    for i, seg in enumerate(raw):
        for m in _SKU_RE.finditer(seg):
            sku_positions.append((i, m.group(1)))

    products = []
    for idx, (seg_pos, item_number) in enumerate(sku_positions):
        window = raw[seg_pos: sku_positions[idx + 1][0]] if idx + 1 < len(sku_positions) else raw[seg_pos:]
        full_text = " ".join(window)

        bc_m = _BARCODE_RE.search(full_text)
        barcode = bc_m.group(1) if bc_m else None

        shots_m = _SHOTS_RE.search(full_text)
        shells_m = _SHELLS_RE.search(full_text)
        shot_count = int(shots_m.group(1)) if shots_m else (int(shells_m.group(1)) if shells_m else None)

        pack_m = _PACKING_RE.search(full_text)
        packing = pack_m.group(1) if pack_m else None

        description = None
        for seg in window:
            if seg.strip().upper().startswith("DESCRIPTION:"):
                description = seg.strip()
                break

        products.append({
            "item_number": item_number,
            "barcode": barcode,
            "shot_count": shot_count,
            "packing": packing,
            "description": description,
            "page": page_num,
        })
    return products


def _mark_job(conn, job_id: int, status: str, error: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE import_jobs SET status=%s, error_message=%s, completed_at=%s WHERE id=%s",
            (status, error, datetime.now(timezone.utc) if status in ("done", "failed") else None, job_id),
        )
    conn.commit()


@celery_app.task(name="tasks.scrape_issuu_catalog", bind=True, max_retries=0)
def scrape_issuu_catalog(self, job_id: int, cdn_id: str | None, doc_slug: str | None, slug: str, year: str):
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        _mark_job(conn, job_id, "running")

        # Resolve CDN ID if not provided
        if not cdn_id and doc_slug:
            cdn_id = resolve_cdn_id(doc_slug)
        if not cdn_id:
            _mark_job(conn, job_id, "failed", "Could not resolve CDN ID from URL. Provide the raw CDN ID directly.")
            return

        # Detect page count by probing
        max_pages = 200
        page_count = 0
        for p in range(1, max_pages + 1):
            segs = fetch_page_text(cdn_id, p)
            if not segs:
                page_count = p - 1
                break
            if p == max_pages:
                page_count = max_pages
        else:
            page_count = max_pages

        if page_count == 0:
            _mark_job(conn, job_id, "failed", f"CDN ID {cdn_id!r} returned no pages — may be expired.")
            return

        # Scrape all pages
        all_products: list[dict] = []
        for page_num in range(1, page_count + 1):
            segs = fetch_page_text(cdn_id, page_num)
            products = parse_products_from_segments(segs, page_num)
            all_products.extend(products)
            time.sleep(0.15)

        # Deduplicate by item_number
        seen: dict[str, dict] = {}
        for p in all_products:
            if p["item_number"] not in seen:
                seen[p["item_number"]] = p
        unique_products = list(seen.values())

        if slug.lower() in ("jakes", "world_class", "worldclass"):
            _import_jakes(conn, job_id, unique_products, year)
        else:
            _create_review_rows(conn, job_id, unique_products, slug)

    except Exception as exc:
        try:
            _mark_job(conn, job_id, "failed", str(exc))
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _import_jakes(conn, job_id: int, products: list[dict], year: str):
    """Run Jake's catalog import directly (no review rows needed — text layer is clean)."""
    BRAND_NAME = "World Class"
    now = datetime.now(timezone.utc)
    inserted = updated = 0

    with conn.cursor() as cur:
        # Resolve brand
        cur.execute("SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", (BRAND_NAME,))
        row = cur.fetchone()
        brand_id = row[0] if row else None

        cur.execute("SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", ("World Class / Jakes",))
        old_row = cur.fetchone()
        old_brand_id = old_row[0] if old_row else None

        if brand_id and old_brand_id:
            cur.execute("UPDATE products SET brand_id=%s WHERE brand_id=%s", (brand_id, old_brand_id))
            cur.execute("DELETE FROM product_brands WHERE id=%s", (old_brand_id,))
        elif old_brand_id and not brand_id:
            cur.execute("UPDATE product_brands SET name=%s WHERE id=%s", (BRAND_NAME, old_brand_id))
            brand_id = old_brand_id
        elif not brand_id:
            cur.execute(
                "INSERT INTO product_brands (name, tier, brand_type) VALUES (%s,'tier1','house_brand') RETURNING id",
                (BRAND_NAME,),
            )
            brand_id = cur.fetchone()[0]

        cur.execute("SELECT id, name FROM product_categories")
        cat_map = {name: cid for cid, name in cur.fetchall()}

        cur.execute(
            "DELETE FROM product_barcodes WHERE product_id IN (SELECT id FROM products WHERE brand_id=%s)",
            (brand_id,),
        )

        for p in products:
            page_num = p.get("page")
            cat_name = jakes_category_for_page(page_num) if page_num else None
            cat_id = cat_map.get(cat_name) if cat_name else None
            name = extract_name_from_description(p.get("description")) or f"Item {p['item_number']}"

            cur.execute("SELECT id, name FROM products WHERE item_number = %s", (p["item_number"],))
            existing = cur.fetchone()

            if existing:
                pid, existing_name = existing
                use_name = name if (not existing_name.startswith("Item ") or name != f"Item {p['item_number']}") else existing_name
                cur.execute(
                    "UPDATE products SET name=%s, description=%s, shot_count=%s, brand_id=%s, category_id=%s, catalog_page=%s, updated_at=%s WHERE id=%s",
                    (use_name, p.get("description"), p.get("shot_count"), brand_id, cat_id, page_num, now, pid),
                )
                updated += 1
            else:
                pid = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO products (id, name, item_number, description, shot_count, brand_id, category_id, catalog_page, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s)",
                    (pid, name, p["item_number"], p.get("description"), p.get("shot_count"), brand_id, cat_id, page_num, now, now),
                )
                inserted += 1

            if p.get("barcode") and len(p["barcode"]) >= 8:
                cur.execute(
                    "INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary) VALUES (%s,%s,'UPC',true) ON CONFLICT DO NOTHING",
                    (pid, p["barcode"]),
                )

        cur.execute(
            "UPDATE import_jobs SET status='done', completed_at=%s WHERE id=%s",
            (now, job_id),
        )

    conn.commit()


def _create_review_rows(conn, job_id: int, products: list[dict], slug: str):
    """Create ImportRow records for human review (unknown catalog format)."""
    now = datetime.now(timezone.utc)
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        for i, p in enumerate(products):
            name = extract_name_from_description(p.get("description")) or f"Item {p['item_number']}"
            raw = {
                "item_code": p["item_number"],
                "name": name,
                "brand": slug,
                "barcode": p.get("barcode"),
                "shot_count": p.get("shot_count"),
                "packing": p.get("packing"),
                "description": p.get("description"),
                "catalog_page": p.get("page"),
            }
            cur.execute(
                "INSERT INTO import_rows (job_id, row_index, raw_data, review_status) VALUES (%s,%s,%s,'pending')",
                (job_id, i, Jsonb(raw)),
            )

        cur.execute(
            "UPDATE import_jobs SET status='review', completed_at=%s WHERE id=%s",
            (now, job_id),
        )

    conn.commit()
