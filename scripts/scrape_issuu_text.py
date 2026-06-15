"""
Scrape the Issuu accessibility HTML layer for any catalog.
Extracts real embedded text — no OCR needed.

Usage:
  python scrape_issuu_text.py --slug jakes --year 2026 --cdn-id 260506140512-f077399ecfd86afa6eee7e4087f1bd81 --pages 177 --start-page 11
"""
import argparse
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://issuu.com/",
}

# Patterns for product fields
_SKU_RE = re.compile(r"SKU[:\s]*(\d{5,10})", re.IGNORECASE)
_BARCODE_RE = re.compile(r"\b(\d{12,14})\b")
_SHOTS_RE = re.compile(r"(\d+)\s*shots?", re.IGNORECASE)
_SHELLS_RE = re.compile(r"(\d+)\s*shells?", re.IGNORECASE)
_PACKING_RE = re.compile(r"(\d+/\d+)\b")
_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{2})?)")
_CATEGORY_WORDS = {
    "ASSORTMENTS", "CAKES", "SHELLS", "FOUNTAINS", "ROCKETS", "SPARKLERS",
    "NOVELTIES", "ARTILLERY", "FIRECRACKERS", "SMOKE", "PARACHUTES",
    "ROMAN CANDLES", "MISSILES", "HELICOPTERS", "SPINNERS", "MINES",
}


class A11yParser(HTMLParser):
    """Extracts text from Issuu's a11y-paragraph elements in page order."""

    def __init__(self):
        super().__init__()
        self._in_p = False
        self._current_top = 0.0
        self.segments: list[tuple[float, str]] = []  # (top%, text)

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            attrs_d = dict(attrs)
            cls = attrs_d.get("class", "")
            if "a11y-paragraph" in cls:
                self._in_p = True
                style = attrs_d.get("style", "")
                m = re.search(r"top:([\d.]+)%", style)
                self._current_top = float(m.group(1)) if m else 0.0

    def handle_endtag(self, tag):
        if tag == "p":
            self._in_p = False

    def handle_data(self, data):
        if self._in_p and data.strip():
            self.segments.append((self._current_top, data.strip()))


def fetch_page_text(cdn_id: str, page_num: int) -> list[tuple[float, str]]:
    url = f"https://svg.issuu.com/{cdn_id}/page_{page_num}.html"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        return []
    parser = A11yParser()
    parser.feed(resp.text)
    return sorted(parser.segments, key=lambda x: x[0])  # sort top-to-bottom


def parse_page(segments: list[tuple[float, str]], page_num: int) -> dict:
    texts = [t for _, t in segments]
    full_text = " | ".join(texts)

    # SKU / item number
    sku_m = _SKU_RE.search(full_text)
    item_number = sku_m.group(1) if sku_m else None

    # Barcodes — long digit strings that aren't the SKU
    barcodes = [
        m for m in _BARCODE_RE.findall(full_text)
        if not (item_number and m == item_number)
    ]

    # Shot / shell count
    shots_m = _SHOTS_RE.search(full_text)
    shells_m = _SHELLS_RE.search(full_text)
    shot_count = int(shots_m.group(1)) if shots_m else (int(shells_m.group(1)) if shells_m else None)

    # Packing
    pack_m = _PACKING_RE.search(full_text)
    packing = pack_m.group(1) if pack_m else None

    # Price
    price_m = _PRICE_RE.search(full_text)
    price = float(price_m.group(1)) if price_m else None

    # Category — ALL CAPS word(s) matching known categories
    category = None
    for t in texts:
        if t.upper() in _CATEGORY_WORDS:
            category = t.upper()
            break

    # Product name — ALL CAPS text that isn't a category or SKU line
    name = None
    for t in texts:
        upper = t.strip().upper()
        if (
            upper == t.strip()  # all caps
            and len(t.strip()) > 3
            and upper not in _CATEGORY_WORDS
            and not _SKU_RE.search(t)
            and not _BARCODE_RE.fullmatch(t.strip())
            and not t.strip().startswith("$")
            and not _PACKING_RE.fullmatch(t.strip())
        ):
            name = t.strip()
            break

    # Description — mixed-case longer text
    desc_parts = [
        t for t in texts
        if any(c.islower() for c in t) and len(t) > 15
    ]
    description = " ".join(desc_parts) if desc_parts else None

    return {
        "page": page_num,
        "name": name,
        "item_number": item_number,
        "barcodes": barcodes,
        "shot_count": shot_count,
        "packing": packing,
        "price": price,
        "category": category,
        "description": description,
        "raw_segments": texts,
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape Issuu accessibility text layer for a catalog")
    parser.add_argument("--cdn-id", required=True, help="Issuu CDN ID")
    parser.add_argument("--slug", required=True, help="Catalog brand slug (e.g. jakes)")
    parser.add_argument("--year", default="2026", help="Catalog year")
    parser.add_argument("--pages", type=int, required=True, help="Total pages")
    parser.add_argument("--start-page", type=int, default=1, help="First product page")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests (seconds)")
    args = parser.parse_args()

    out_dir = SCRIPTS_DIR / "catalogs" / args.slug / args.year
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "text_layer.json"

    results = []
    for n in range(1, args.pages + 1):
        if n < args.start_page:
            print(f"  Page {n}/{args.pages} [skip — TOC/cover]")
            results.append({"page": n, "skipped": True})
            continue

        print(f"  Page {n}/{args.pages}", end="", flush=True)
        segments = fetch_page_text(args.cdn_id, n)
        if not segments:
            print(" [no data]")
            results.append({"page": n, "name": None, "item_number": None, "barcodes": []})
            time.sleep(args.delay)
            continue

        parsed = parse_page(segments, n)
        marker = f"  SKU:{parsed['item_number']}" if parsed["item_number"] else "  (no SKU)"
        print(f"{marker}  name={parsed['name']!r}")
        results.append(parsed)
        time.sleep(args.delay)

    # Summary
    with_sku = [r for r in results if r.get("item_number")]
    with_barcode = [r for r in results if r.get("barcodes")]
    print(f"\nDone. Pages: {len(results)}  With SKU: {len(with_sku)}  With barcode: {len(with_barcode)}")

    out_path.write_text(
        json.dumps({"meta": {"cdn_id": args.cdn_id, "slug": args.slug, "year": args.year, "pages": args.pages}, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
