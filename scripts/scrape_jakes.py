from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://www.jakesfireworks.com"
LISTING_PATH = "/fireworks/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 0.5

SCRIPT_DIR = Path(__file__).resolve().parent
JSON_OUTPUT = SCRIPT_DIR / "jakes_catalog.json"
CSV_OUTPUT = SCRIPT_DIR / "jakes_catalog.csv"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=30)
    response.encoding = "utf-8"  # site is UTF-8 but doesn't always declare it in headers
    time.sleep(REQUEST_DELAY_SECONDS)
    response.raise_for_status()
    return response


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def split_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    return [token for token in value.split() if token]


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def extract_item_number(image_url: str | None) -> str | None:
    if not image_url:
        return None
    filename = os.path.basename(urlparse(image_url).path)
    match = re.match(r"^(\d+)-", filename)
    return match.group(1) if match else None


def extract_description_and_specs(soup: BeautifulSoup) -> tuple[str | None, dict[str, Any]]:
    description: str | None = None
    meta = soup.select_one('meta[name="description"]')
    if isinstance(meta, Tag):
        description = meta.get("content")
        if description:
            description = normalize_text(description)

    if not description:
        for selector in (".entry-content", ".product-detail"):
            container = soup.select_one(selector)
            if not isinstance(container, Tag):
                continue
            first_paragraph = container.find("p")
            if first_paragraph:
                text = normalize_text(first_paragraph.get_text(" ", strip=True))
                if text:
                    description = text
                    break

    specs: dict[str, Any] = {}
    seen_tables: set[int] = set()
    seen_dls: set[int] = set()

    for selector in (".product-detail", ".entry-content", "table", "dl"):
        for element in soup.select(selector):
            element_id = id(element)
            if element.name == "table":
                if element_id in seen_tables:
                    continue
                seen_tables.add(element_id)
                rows = []
                for row in element.find_all("tr"):
                    cells = [
                        normalize_text(cell.get_text(" ", strip=True))
                        for cell in row.find_all(["th", "td"])
                    ]
                    cells = [cell for cell in cells if cell]
                    if len(cells) >= 2:
                        key = cells[0]
                        value = " ".join(cells[1:]).strip()
                        if key and value:
                            specs[key] = value
                        rows.append(cells)
                if rows and "tables" not in specs:
                    specs["tables"] = []
                if rows:
                    specs["tables"].append(rows)

            elif element.name == "dl":
                if element_id in seen_dls:
                    continue
                seen_dls.add(element_id)
                pairs: list[list[str]] = []
                terms = element.find_all("dt")
                for term in terms:
                    definition = term.find_next_sibling("dd")
                    if not definition:
                        continue
                    key = normalize_text(term.get_text(" ", strip=True))
                    value = normalize_text(definition.get_text(" ", strip=True))
                    if key and value:
                        specs[key] = value
                        pairs.append([key, value])
                if pairs and "dl" not in specs:
                    specs["dl"] = []
                if pairs:
                    specs["dl"].append(pairs)

    return description, specs


def extract_product_detail(session: requests.Session, product_url: str) -> dict[str, Any]:
    try:
        response = fetch(session, product_url)
    except Exception as exc:
        print(f"Detail error: {product_url} — {exc}", file=sys.stderr)
        return {"description": None, "specs": {}}

    soup = BeautifulSoup(response.text, "lxml")
    description, specs = extract_description_and_specs(soup)
    return {"description": description, "specs": specs}


def extract_card_data(card: Tag) -> dict[str, Any]:
    link = card.select_one("h4 > a")
    media_image = card.select_one(".product-media img")

    name = normalize_text(link.get_text(" ", strip=True)) if isinstance(link, Tag) else ""
    url = ""
    if isinstance(link, Tag):
        url = urljoin(BASE_URL, link.get("href") or "")

    image_url = ""
    if isinstance(media_image, Tag):
        image_url = urljoin(BASE_URL, media_image.get("src") or "")

    return {
        "name": name or None,
        "url": url or None,
        "category": (card.get("data-category") or "").strip() or None,
        "colors": split_tokens(card.get("data-color")),
        "effects": split_tokens(card.get("data-effect")),
        "shot_count": parse_int(card.get("data-shots")),
        "duration_seconds": parse_int(card.get("data-duration")),
        "image_url": image_url or None,
        "item_number": extract_item_number(image_url),
    }


def discover_total_pages(soup: BeautifulSoup) -> int | None:
    page_numbers: list[int] = []
    for link in soup.select("a[href*='/fireworks/page/']"):
        href = link.get("href") or ""
        match = re.search(r"/fireworks/page/(\d+)/?", href)
        if match:
            page_numbers.append(int(match.group(1)))
    if page_numbers:
        return max(page_numbers)
    return None


def scrape_listing_page(session: requests.Session, page_number: int) -> tuple[list[dict[str, Any]], int | None]:
    if page_number == 1:
        url = urljoin(BASE_URL, LISTING_PATH)
    else:
        url = urljoin(BASE_URL, f"/fireworks/page/{page_number}/")

    response = fetch(session, url)
    soup = BeautifulSoup(response.text, "lxml")

    cards = soup.select("div.product-single")
    products: list[dict[str, Any]] = []
    for card in cards:
        if isinstance(card, Tag):
            products.append(extract_card_data(card))

    return products, discover_total_pages(soup)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Jake's Fireworks catalog.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages to crawl; 0 means all pages.")
    parser.add_argument("--skip-detail", action="store_true", help="Skip visiting product detail pages.")
    args = parser.parse_args()

    session = build_session()
    all_products: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    total_pages: int | None = None
    page_number = 1
    consecutive_page_errors = 0

    while True:
        if args.max_pages and page_number > args.max_pages:
            break
        # NOTE: do NOT stop based on total_pages alone — the pagination widget on
        # page 1 shows e.g. "1 2 3 … 55" but the real last page may be 177.
        # total_pages updates as we crawl deeper and the widget reveals higher numbers.

        page_products: list[dict[str, Any]] = []
        page_loaded = False
        try:
            page_products, discovered_total = scrape_listing_page(session, page_number)
            page_loaded = True
            consecutive_page_errors = 0
            # Always take the max so later pages can reveal the true last page number
            if discovered_total and (total_pages is None or discovered_total > total_pages):
                total_pages = discovered_total

            for product in page_products:
                product_url = product.get("url")
                if product_url and product_url in seen_urls:
                    continue
                if product_url:
                    seen_urls.add(product_url)

                if not args.skip_detail and product_url:
                    try:
                        detail = extract_product_detail(session, product_url)
                        product["description"] = detail["description"]
                        product["specs"] = detail["specs"]
                    except Exception as exc:
                        print(f"Detail error: {product_url} — {exc}", file=sys.stderr)
                        product["description"] = None
                        product["specs"] = {}
                else:
                    product["description"] = None
                    product["specs"] = {}

                all_products.append(product)
        except Exception as exc:
            print(f"Page error: {page_number} — {exc}", file=sys.stderr)
        finally:
            total_label = str(args.max_pages) if args.max_pages else (str(total_pages) if total_pages else "?")
            print(f"Page {page_number}/{total_label} — scraped {len(all_products)} products so far")

        if page_loaded and not page_products:
            break
        if not page_loaded:
            consecutive_page_errors += 1
            if consecutive_page_errors >= 3:
                break
        page_number += 1

    json_output = []
    for product in all_products:
        row = dict(product)
        json_output.append(row)

    with JSON_OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(json_output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    fieldnames = [
        "name",
        "url",
        "category",
        "colors",
        "effects",
        "shot_count",
        "duration_seconds",
        "image_url",
        "item_number",
        "description",
        "specs",
    ]

    with CSV_OUTPUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for product in all_products:
            row = dict(product)
            row["colors"] = ",".join(row.get("colors") or [])
            row["effects"] = ",".join(row.get("effects") or [])
            row["specs"] = json.dumps(row.get("specs") or {}, ensure_ascii=False)
            writer.writerow({key: row.get(key) for key in fieldnames})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
