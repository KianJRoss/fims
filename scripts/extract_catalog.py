import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

try:
    from rapidocr_onnxruntime import RapidOCR
    rapid_ocr = RapidOCR()
except Exception:
    rapid_ocr = None

try:
    import pytesseract
    _pytesseract_available = True
except Exception:
    _pytesseract_available = False

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    _pyzbar_available = True
except Exception:
    _pyzbar_available = False

SCRIPTS_DIR = Path(__file__).parent
CDN_ID = "260506140512-f077399ecfd86afa6eee7e4087f1bd81"
BASE_URL = f"https://image.isu.pub/{CDN_ID}/jpg/page_{{n}}.jpg"
TOTAL_PAGES = 177
PRODUCT_START_PAGE = 11  # pages 1-10 are cover + table of contents
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Default catalog folder: scripts/catalogs/{brand}/{year}/pages/
DEFAULT_CATALOG_SLUG = "jakes"
DEFAULT_CATALOG_YEAR = "2026"


def catalog_pages_dir(slug: str = DEFAULT_CATALOG_SLUG, year: str = DEFAULT_CATALOG_YEAR) -> Path:
    return SCRIPTS_DIR / "catalogs" / slug / year / "pages"


def catalog_output_path(slug: str = DEFAULT_CATALOG_SLUG, year: str = DEFAULT_CATALOG_YEAR) -> Path:
    return SCRIPTS_DIR / "catalogs" / slug / year / "vision.json"


def download_pages(max_pages: int, pages_dir: Path) -> None:
    pages_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    for n in range(1, max_pages + 1):
        dest = pages_dir / f"page_{n:03d}.jpg"
        if dest.exists():
            continue
        print(f"Downloading page {n}/{max_pages}")
        url = BASE_URL.format(n=n)
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        except Exception as e:
            print(f"  [WARN] Failed page {n}: {e}")
        time.sleep(0.3)


def ocr_page(image_path: Path) -> dict:
    try:
        pil_img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"  [WARN] Cannot open {image_path.name}: {e}")
        return {"text": "", "barcodes": []}

    text = ""

    if rapid_ocr is not None:
        try:
            arr = np.array(pil_img)
            result, _ = rapid_ocr(arr)
            if result:
                text = " | ".join(r[1] for r in result if r and len(r) > 1)
        except Exception as e:
            print(f"  [WARN] RapidOCR failed on {image_path.name}: {e}")

    if len(text) < 20 and _pytesseract_available:
        try:
            text = pytesseract.image_to_string(pil_img, config="--psm 11")
        except Exception as e:
            print(f"  [WARN] pytesseract failed on {image_path.name}: {e}")

    barcodes = []
    if _pyzbar_available:
        try:
            decoded = pyzbar_decode(pil_img)
            barcodes = [{"data": b.data.decode("utf-8", errors="replace"), "type": b.type} for b in decoded]
        except Exception as e:
            print(f"  [WARN] pyzbar failed on {image_path.name}: {e}")

    return {"text": text, "barcodes": barcodes}


_RE_SKU = re.compile(r"SKU[:\s]+(\d{5,10})", re.IGNORECASE)
_RE_BARCODE_TEXT = re.compile(r"BARCODE[:\s]+(\d{8,14})", re.IGNORECASE)
_RE_SHELLS = re.compile(r"(\d+)\s*SHELLS", re.IGNORECASE)
_RE_SHOTS = re.compile(r"(\d+)\s*shots?", re.IGNORECASE)
_RE_PACKING = re.compile(r"PACKING[:\s]+(\S+)", re.IGNORECASE)
_RE_DESCRIPTION = re.compile(r"DESCRIPTION[:\s]+(.+?)(?:\||\Z)", re.IGNORECASE | re.DOTALL)
# Category keywords that appear as page headers, not product names
_CATEGORY_WORDS = {
    "ASSORTMENTS", "CAKES", "SHELLS", "FOUNTAINS", "ROCKETS", "SPARKLERS",
    "NOVELTIES", "ARTILLERY", "FIRECRACKERS", "SMOKE", "PARACHUTES",
    "ROMAN CANDLES", "MISSILES", "HELICOPTERS", "SPINNERS",
}


def _best_name(text: str) -> str | None:
    segments = [s.strip() for s in text.split("|")]
    for seg in segments:
        # Skip obvious non-names
        if any(kw in seg.upper() for kw in ("SKU:", "BARCODE:", "PACKING:", "DESCRIPTION:", "UNITSIZE:", "JAKESFIREWORKS", "1.800", "SHELLS", "SHOTS")):
            continue
        upper_words = [w for w in seg.split() if w.isupper() and len(w) >= 2]
        if len(upper_words) >= 2 and seg.upper() not in _CATEGORY_WORDS:
            return " ".join(upper_words)
    return None


def parse_products(page_num: int, text: str, barcodes: list) -> list:
    if not text.strip():
        return []

    barcode_strs = [b["data"] for b in barcodes]

    sku_m = _RE_SKU.search(text)
    shells_m = _RE_SHELLS.search(text)
    shots_m = _RE_SHOTS.search(text)
    pack_m = _RE_PACKING.search(text)
    desc_m = _RE_DESCRIPTION.search(text)
    bc_text_m = _RE_BARCODE_TEXT.search(text)

    item_number = sku_m.group(1) if sku_m else None
    shell_count = int(shells_m.group(1)) if shells_m else (int(shots_m.group(1)) if shots_m else None)
    packing = pack_m.group(1) if pack_m else None
    description = " ".join(desc_m.group(1).split()) if desc_m else None

    # Prefer pyzbar barcode; fall back to OCR-text barcode
    if not barcode_strs and bc_text_m:
        barcode_strs = [bc_text_m.group(1)]

    name = _best_name(text)

    if not any([item_number, name, barcode_strs]):
        return []

    return [{
        "name": name,
        "item_number": item_number,
        "shell_count": shell_count,
        "packing": packing,
        "description": description,
        "barcodes": barcode_strs,
        "page": page_num,
    }]


def process_pages(max_pages: int, output_path: Path, pages_dir: Path, start_page: int = 1) -> None:
    pages_out = []
    for n in range(1, max_pages + 1):
        img_path = pages_dir / f"page_{n:03d}.jpg"
        if not img_path.exists():
            print(f"  [SKIP] page_{n:03d}.jpg not found")
            pages_out.append({"page": n, "text": "", "barcodes": [], "products": []})
            continue

        is_product_page = n >= start_page
        print(f"Processing page {n}/{max_pages}{'' if is_product_page else ' [TOC/cover]'}")
        try:
            ocr_result = ocr_page(img_path)
            products = parse_products(n, ocr_result["text"], ocr_result["barcodes"]) if is_product_page else []
            pages_out.append({
                "page": n,
                "text": ocr_result["text"],
                "barcodes": ocr_result["barcodes"],
                "products": products,
            })
        except Exception as e:
            print(f"  [ERROR] page {n}: {e}")
            pages_out.append({"page": n, "text": "", "barcodes": [], "products": []})

    output = {
        "meta": {
            "total_pages": TOTAL_PAGES,
            "product_start_page": start_page,
            "pages_processed": len(pages_out),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "pages": pages_out,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract a fireworks catalog from Issuu page images")
    parser.add_argument("--pages", type=int, default=TOTAL_PAGES, help="Number of pages to process")
    parser.add_argument("--start-page", type=int, default=PRODUCT_START_PAGE, help="First page with product data")
    parser.add_argument("--skip-download", action="store_true", help="Skip download phase")
    parser.add_argument("--cdn-id", default=CDN_ID, help="Issuu CDN ID for the catalog")
    parser.add_argument("--slug", default=DEFAULT_CATALOG_SLUG, help="Catalog brand slug (e.g. jakes, rm, winda)")
    parser.add_argument("--year", default=DEFAULT_CATALOG_YEAR, help="Catalog year (e.g. 2026)")
    parser.add_argument("--output", type=Path, default=None, help="Override output JSON path")
    args = parser.parse_args()

    pages_dir = catalog_pages_dir(args.slug, args.year)
    output_path = args.output or catalog_output_path(args.slug, args.year)
    max_pages = args.pages

    # Allow overriding the CDN base URL per catalog
    global BASE_URL
    BASE_URL = f"https://image.isu.pub/{args.cdn_id}/jpg/page_{{n}}.jpg"

    if not args.skip_download:
        print(f"=== Download phase ({max_pages} pages → {pages_dir}) ===")
        download_pages(max_pages, pages_dir)

    print(f"\n=== OCR/parse phase ({max_pages} pages, products from page {args.start_page}) ===")
    process_pages(max_pages, output_path, pages_dir, start_page=args.start_page)


if __name__ == "__main__":
    main()
