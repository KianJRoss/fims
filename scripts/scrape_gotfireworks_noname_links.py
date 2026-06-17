"""
Scrape every gotfireworks.com product page linked directly from NoName2026.pdf.

The PDF's product images are hyperlinks straight to the matching gotfireworks.com
product page (discovered 2026-06-17). Each page's "More Information" table gives
authoritative SKU/Brand/Shots/Duration/Case Packing/Product Catalog Name — no OCR
or fuzzy name-matching needed, unlike crosscheck_gotfireworks.py.

Input:  scripts/catalogs/noname/2026/gotfireworks_links.json  (page -> url list)
Output: scripts/catalogs/noname/2026/gotfireworks_scraped.json

Run:
    python scripts/scrape_gotfireworks_noname_links.py
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
LINKS_JSON = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_links.json"
OUTPUT_JSON = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_scraped.json"

DURATION_RE = re.compile(r"(\d+)\s*sec", re.IGNORECASE)


def parse_product_page(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="product-attribute-specs-table")
    if table is None:
        return None

    attrs: dict[str, str] = {}
    for row in table.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if th is None or td is None:
            continue
        attrs[th.get_text(strip=True)] = td.get_text(strip=True)

    sku = attrs.get("SKU")
    if not sku:
        return None

    duration_seconds = None
    duration_raw = attrs.get("Duration")
    if duration_raw:
        m = DURATION_RE.search(duration_raw)
        if m:
            duration_seconds = int(m.group(1))

    shots_raw = attrs.get("Shots")
    shot_count = int(shots_raw) if shots_raw and shots_raw.isdigit() else None

    desc_div = soup.select_one(".product.attribute.description .value")
    description = desc_div.get_text(strip=True) if desc_div else None

    in_stock_span = soup.select_one(".stock.available span, .stock.unavailable span")
    stock_status = in_stock_span.get_text(strip=True) if in_stock_span else None

    return {
        "url": url,
        "sku": sku,
        "brand": attrs.get("Brand"),
        "sales_per_case": attrs.get("Sales Per Case"),
        "shot_count": shot_count,
        "duration_seconds": duration_seconds,
        "dimension": attrs.get("Dimension"),
        "case_packing": attrs.get("Case Packing"),
        "product_catalog_name": attrs.get("Product Catalog Name"),
        "description": description,
        "stock_status": stock_status,
    }


def main() -> None:
    links = json.loads(LINKS_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(links)} links from {LINKS_JSON}")

    results = []
    errors = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        for i, entry in enumerate(links, 1):
            url = entry["url"]
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    errors.append({"url": url, "status": resp.status_code})
                    print(f"[{i}/{len(links)}] {resp.status_code} {url}")
                    continue
                parsed = parse_product_page(resp.text, url)
                if parsed is None:
                    errors.append({"url": url, "status": "no-table"})
                    print(f"[{i}/{len(links)}] NO-TABLE {url}")
                    continue
                parsed["page"] = entry["page"]
                results.append(parsed)
                print(f"[{i}/{len(links)}] OK {parsed['sku']} {parsed['product_catalog_name']}")
            except httpx.HTTPError as exc:
                errors.append({"url": url, "status": f"error: {exc}"})
                print(f"[{i}/{len(links)}] ERROR {url}: {exc}")

            time.sleep(0.4 + random.random() * 0.3)

    OUTPUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved {len(results)} parsed products to {OUTPUT_JSON}")
    if errors:
        print(f"{len(errors)} errors/skips:")
        for e in errors[:20]:
            print(" ", e)


if __name__ == "__main__":
    main()
