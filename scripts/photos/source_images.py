"""
Phase 1 photo audit: gather candidate replacement images for selected products.

This script only reads from the database. It writes:
  - media/photo_audit/{product_id}/*.*
  - media/photo_audit/{product_id}/manifest.json

Sources:
  1. gotfireworks.com
  2. worldclassfireworks.com
  3. general web image search via ddgs
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
import psycopg
from bs4 import BeautifulSoup
from ddgs import DDGS

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@100.73.208.99:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "media" / "photo_audit"
GOTFIREWORKS_JSON = (
    ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_scraped.json"
)
FW_TYPES = [
    "fountains",
    "show-starters",
    "finales",
    "artillery-shells",
    "family-packs",
    "firecrackers",
    "novelties",
    "sparklers",
    "roman-candles",
    "rockets",
    "show-to-go-cartons",
]
SKU_FROM_FILENAME_RE = re.compile(r"/(\d{7})[^/]*\.(?:png|jpe?g|webp)$", re.IGNORECASE)
DEFAULT_WEB_TOP_N = 5


def normalize_sku(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def safe_component(value: object) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", str(value or ""))


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_products(
    ids: list[str] | None,
    brand: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    where: list[str] = ["p.item_number IS NOT NULL"]
    params: list[Any] = []

    if ids:
        where.append(f"p.id::text = ANY(%s)")
        params.append(ids)
    if brand:
        where.append("COALESCE(b.name, '') ILIKE %s")
        params.append(f"%{brand}%")
    if limit is not None:
        limit = max(limit, 0)

    query = f"""
        SELECT
            p.id::text AS product_id,
            p.item_number,
            p.name,
            b.name AS brand_name,
            p.image_path
        FROM products p
        LEFT JOIN product_brands b ON b.id = p.brand_id
        WHERE {" AND ".join(where)}
        ORDER BY p.item_number NULLS LAST, p.id
    """
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    products: list[dict[str, Any]] = []
    for row in rows:
        products.append(
            {
                "product_id": row[0],
                "item_number": normalize_sku(row[1]),
                "name": normalize_text(row[2]),
                "brand": normalize_text(row[3]),
                "current_image": row[4],
            }
        )
    return products


def maybe_sample(products: list[dict[str, Any]], sample_n: int | None) -> list[dict[str, Any]]:
    if sample_n is None or sample_n <= 0 or len(products) <= sample_n:
        return products
    return random.sample(products, sample_n)


def load_gotfireworks_page_map() -> dict[str, str]:
    if not GOTFIREWORKS_JSON.exists():
        return {}
    try:
        scraped = json.loads(GOTFIREWORKS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    page_map: dict[str, str] = {}
    for item in scraped:
        sku = normalize_sku(item.get("sku"))
        url = str(item.get("url") or "").strip()
        if sku and url and sku not in page_map:
            page_map[sku] = url
    return page_map


def fetch_gotfireworks_candidates(
    client: httpx.Client,
    product: dict[str, Any],
    page_map: dict[str, str],
) -> list[dict[str, str]]:
    page_url = page_map.get(product["item_number"])
    if not page_url:
        return []
    resp = client.get(page_url)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    img = soup.select_one("img.gallery-placeholder__image")
    if not img or not img.get("src"):
        return []
    return [{"source": "gotfireworks", "url": img["src"]}]


def enumerate_worldclass_images(client: httpx.Client) -> dict[str, str]:
    sku_to_image: dict[str, str] = {}
    for fw_type in FW_TYPES:
        url = f"https://www.worldclassfireworks.com/fw_type/{fw_type}/"
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  worldclass:{fw_type}: fetch failed {resp.status_code}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.product-single")
        found = 0
        for card in cards:
            img = card.select_one(".product-media img")
            if not img or not img.get("src"):
                continue
            match = SKU_FROM_FILENAME_RE.search(img["src"])
            if not match:
                continue
            sku = match.group(1)
            if sku not in sku_to_image:
                sku_to_image[sku] = img["src"]
                found += 1
        print(f"  worldclass:{fw_type}: {len(cards)} cards, {found} new SKUs")
        time.sleep(0.4 + random.random() * 0.3)
    return sku_to_image


def query_web_images(product: dict[str, Any], top_n: int = DEFAULT_WEB_TOP_N) -> list[dict[str, str]]:
    parts = [f'"{product["name"]}"']
    if product.get("brand"):
        parts.append(product["brand"])
    parts.extend(["firework", product["item_number"]])
    query = " ".join(part for part in parts if part).strip()

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    with DDGS() as ddgs:
        for result in ddgs.images(query, max_results=top_n):
            url = str(result.get("image") or result.get("thumbnail") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            results.append({"source": "web", "url": url})
    return results


def ext_from_response(url: str, response: httpx.Response) -> str:
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }.get(content_type, ".jpg")


def download_candidate(url: str, dest_base: Path) -> tuple[bool, str, Path | None]:
    existing = sorted(dest_base.parent.glob(f"{dest_base.stem}.*"))
    for path in existing:
        if path.is_file() and path.stat().st_size > 0:
            return True, "exists", path
    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return False, f"fetch {resp.status_code}", None
            ext = ext_from_response(url, resp)
            dest = dest_base.with_suffix(ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True, "downloaded", dest
    except httpx.HTTPError as exc:
        return False, str(exc), None


def build_candidates(
    product: dict[str, Any],
    page_map: dict[str, str],
    worldclass_map: dict[str, str],
    web_top_n: int,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    candidates.extend(fetch_gotfireworks_candidates(_SOURCE_HTTP, product, page_map))
    worldclass_url = worldclass_map.get(product["item_number"])
    if worldclass_url:
        candidates.append({"source": "worldclass", "url": worldclass_url})
    candidates.extend(query_web_images(product, top_n=web_top_n))

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = candidate["url"]
        if url in seen:
            continue
        seen.add(url)
        deduped.append(candidate)
    return deduped


def prepare_worldclass_map(client: httpx.Client) -> dict[str, str]:
    print("Enumerating World Class products...")
    sku_to_image = enumerate_worldclass_images(client)
    print(f"  worldclass: total unique SKUs {len(sku_to_image)}")
    return sku_to_image


def prepare_products(args: argparse.Namespace) -> list[dict[str, Any]]:
    ids = [value.strip() for value in args.ids.split(",") if value.strip()] if args.ids else None
    products = load_products(ids=ids, brand=args.brand, limit=args.limit)
    if args.sample:
        products = maybe_sample(products, args.sample)
    return products


def write_manifest(product: dict[str, Any], candidates: list[dict[str, str]]) -> None:
    product_dir = MEDIA_DIR / product["product_id"]
    manifest_path = product_dir / "manifest.json"
    manifest = {
        "product_id": product["product_id"],
        "item_number": product["item_number"],
        "name": product["name"],
        "brand": product["brand"],
        "current_image": product["current_image"],
        "candidates": candidates,
    }
    product_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def process_product(
    product: dict[str, Any],
    page_map: dict[str, str],
    worldclass_map: dict[str, str],
    web_top_n: int,
) -> tuple[int, int]:
    candidates = build_candidates(product, page_map, worldclass_map, web_top_n)
    product_dir = MEDIA_DIR / product["product_id"]
    product_dir.mkdir(parents=True, exist_ok=True)

    # Download in a small batch with bounded concurrency.
    download_plan: list[tuple[dict[str, str], Path]] = []
    source_counts: dict[str, int] = {}
    for candidate in candidates:
        source = candidate["source"]
        source_counts[source] = source_counts.get(source, 0) + 1
        index = source_counts[source]
        download_plan.append((candidate, product_dir / f"{source}_{index}"))

    downloaded = 0
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(download_plan)))) as pool:
        futures = {}
        for candidate, dest in download_plan:
            futures[pool.submit(download_candidate, candidate["url"], dest)] = (candidate, dest)
        for future in as_completed(futures):
            candidate, dest = futures[future]
            ok, status, final_path = future.result()
            if ok:
                if status == "downloaded":
                    downloaded += 1
                candidate["file"] = (final_path or dest).relative_to(ROOT).as_posix()
            else:
                candidate["file"] = ""
                print(f"  {product['product_id']} {candidate['source']}: {status}")

    # Rebuild candidate file names in source order for the manifest.
    source_counts.clear()
    for candidate in candidates:
        source = candidate["source"]
        source_counts[source] = source_counts.get(source, 0) + 1
        index = source_counts[source]
        candidate.setdefault("file", (product_dir / f"{source}_{index}").relative_to(ROOT).as_posix())

    write_manifest(product, candidates)
    return len(candidates), downloaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect candidate replacement photos")
    parser.add_argument("--sample", type=int, default=None, help="Random sample size")
    parser.add_argument("--brand", type=str, default=None, help='Filter by brand name, e.g. "World Class"')
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of products loaded")
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated product ids")
    parser.add_argument("--web-top-n", type=int, default=DEFAULT_WEB_TOP_N, help="Top N web image search results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    random.seed()

    products = prepare_products(args)
    print(f"Loaded {len(products)} products after filters")
    if not products:
        print("Nothing to do")
        return 0

    page_map = load_gotfireworks_page_map()
    print(f"Loaded {len(page_map)} gotfireworks page URLs")

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        worldclass_map = prepare_worldclass_map(client)

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    total_candidates = 0
    total_downloaded = 0
    for index, product in enumerate(products, 1):
        print(
            f"[{index}/{len(products)}] {product['product_id']} "
            f"{product['item_number']} {product['name']}"
        )
        candidates, downloaded = process_product(
            product=product,
            page_map=page_map,
            worldclass_map=worldclass_map,
            web_top_n=args.web_top_n,
        )
        total_candidates += candidates
        total_downloaded += downloaded

    print(f"\nProducts processed: {len(products)}")
    print(f"Candidates recorded: {total_candidates}")
    print(f"New files downloaded: {total_downloaded}")
    print(f"Manifest root: {MEDIA_DIR.relative_to(ROOT).as_posix()}")
    return 0


_SOURCE_HTTP = httpx.Client(
    headers={"User-Agent": USER_AGENT},
    timeout=httpx.Timeout(20.0, connect=10.0),
    follow_redirects=True,
)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        _SOURCE_HTTP.close()
