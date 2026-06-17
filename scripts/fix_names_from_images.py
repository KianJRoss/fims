#!/usr/bin/env python3
"""
Fix "Item XXXXXXX" placeholder names by:
  1. Applying names from vision.json (previously AI-extracted, 153 entries)
  2. OCR-ing catalog page images with pytesseract for the rest

Match strategy for OCR:
  - Run pytesseract image_to_data() on each page image
  - Each product's item_number appears somewhere on the page (in description block)
  - Product name is the ALL CAPS text appearing before (above) the item number
  - Filter using SKIP_NAMES to exclude category headers

Usage:
    python scripts/fix_names_from_images.py [--dry-run] [--ocr-only] [--vision-only]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageOps
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    sys.exit("pip install rapidocr-onnxruntime pillow numpy")

_ocr_engine = None

def get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine

PAGES_DIR = Path(__file__).parent / "catalogs" / "jakes" / "2026" / "pages"
VISION_PATH = Path(__file__).parent / "catalogs" / "jakes" / "2026" / "vision.json"

PI_HOST = "krioasns@100.73.208.99"
PSQL = "sudo docker exec fims-postgres-1 psql -U fims -d fims"

SKIP_NAMES = {
    "ASSORTMENTS", "ARTILLERY SHELLS", "ARTILLERY SHELL", "500 GRAM CAKES",
    "200 GRAM CAKES", "Z CAKES", "3 INCH 500 GRAM CAKES", "SATURN MISSILES",
    "SATURN MISSILE", "FOUNTAINS", "FIRECRACKERS", "SMOKE", "NOVELTIES",
    "PARACHUTES", "ROCKETS", "MISSILES", "ROMAN CANDLES", "SPARKLERS",
    "SHOW TO GO CARTONS", "WARNING", "WORLD-CLASS", "WORLD CLASS",
    "NEW FOR 2026", "PACKING", "BARCODE", "DESCRIPTION", "UNIT SIZE",
    "UNITSIZE", "ITEM NUMBER", "SHOTS", "DURATION", "EFFECTS",
    "200 GRAM", "500 GRAM", "GRAM CAKES", "NOISE", "SPECIAL EFFECTS",
    "MULTI SHOT", "MULTI-SHOT", "CAKE", "CAKES",
}

NON_ALPHA_RE = re.compile(r"^[^A-Za-z]+$")
ITEM_NUM_RE = re.compile(r"\b(1\d{6})\b")

# Words that indicate warning/spec text, not a product name
WARN_WORDS = {
    "WARNING", "CAUTION", "SHOOT", "SHOOTS", "FLAMING", "FLAM", "FLAME",
    "READ", "CAREFULLY", "CAREFUL", "PANEL", "SIDE", "OTHER", "ADDITIONAL",
    "NOTICE", "DANGER", "INSTRUCTION", "INDOOR", "OUTDOOR", "DONOTHOLD",
    "LIGHTFUSE", "GETAWAY", "SPECTATOR", "CONSUMER", "FIREWORK",
    "MADEINCHINA", "CHINA", "PACKING", "BARCODE", "DESCRIPTION",
    "PRODUCT", "HEADER", "GRAM", "GRAMS", "SHOTS", "SHOT",
    "NEW", "SERVE", "LONG", "POWER", "SUPER", "SHELLS", "SHELL",
    "BALLS", "BALL", "COLOR", "COLORS", "SANE",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

def psql_query(sql: str) -> list[list[str]]:
    cmd = f"{PSQL} -t -A -F'|' -c \"{sql}\""
    result = subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"psql_query failed: {result.stderr}")
    return [line.split("|") for line in result.stdout.splitlines() if line.strip()]


def apply_updates(updates: dict[str, str], dry_run: bool) -> None:
    if not updates:
        print("Nothing to update.")
        return
    if dry_run:
        print(f"\n[DRY RUN] {len(updates)} updates — first 10:")
        for item_num, name in list(updates.items())[:10]:
            print(f"  {item_num} -> {name}")
        return

    lines = ["BEGIN;"]
    for item_number, name in updates.items():
        safe_name = name.replace("'", "''")
        lines.append(
            f"UPDATE products SET name='{safe_name}' "
            f"WHERE item_number='{item_number}' AND name LIKE 'Item %';"
        )
    lines.append("COMMIT;")
    sql_block = "\n".join(lines)

    result = subprocess.run(
        ["ssh", PI_HOST, "sudo docker exec -i fims-postgres-1 psql -U fims -d fims --set ON_ERROR_STOP=1"],
        input=sql_block,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    if result.returncode != 0:
        print(f"ERROR: psql exited {result.returncode}")
    else:
        print(f"Done. ({len(updates)} products updated)")


# ── Vision.json names ─────────────────────────────────────────────────────────

def load_vision_names() -> dict[str, str]:
    if not VISION_PATH.exists():
        print("WARNING: vision.json not found, skipping")
        return {}
    data = json.loads(VISION_PATH.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for page in data.get("pages", []):
        for prod in page.get("products", []):
            item = str(prod.get("item_number") or "").strip()
            name = str(prod.get("name") or "").strip()
            if item and name and not name.lower().startswith("item "):
                out[item] = name
    return out


# ── OCR helpers ───────────────────────────────────────────────────────────────

def looks_like_name(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 3 or len(t) > 50:
        return False
    if NON_ALPHA_RE.fullmatch(t):
        return False
    alpha = [c for c in t if c.isalpha()]
    if not alpha:
        return False
    if not all(c.isupper() for c in alpha):
        return False
    if t.upper() in SKIP_NAMES:
        return False
    if ":" in t or t[0].isdigit():
        return False
    words = t.split()
    if not (1 <= len(words) <= 6):
        return False
    # Reject single-word names that are known junk or too short
    if len(words) == 1 and (len(t) < 4 or t.upper() in WARN_WORDS):
        return False
    # Reject if any word is a warning keyword
    if any(w.upper() in WARN_WORDS for w in words):
        return False
    # Reject runon OCR artifacts: long word with no spaces (>14 chars = concatenated garbage)
    if any(len(w) > 14 for w in words):
        return False
    return True


def ocr_page(page_num: int) -> dict[str, str]:
    """Return {item_number: name} for a single page using RapidOCR."""
    path = PAGES_DIR / f"page_{page_num:03d}.jpg"
    if not path.exists():
        return {}

    img = Image.open(path).convert("RGB")
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    arr = np.array(gray)

    engine = get_ocr_engine()
    result, _ = engine(arr)
    if not result:
        return {}

    # RapidOCR result: list of [polygon, text, score]
    # polygon is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] — top-left first
    # Results come roughly top-to-bottom already, but sort by y to be sure
    lines: list[tuple[float, str]] = []
    for row in result:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        poly = row[0]
        text = str(row[1] or "").strip()
        score = float(row[2]) if len(row) > 2 else 0.0
        if not text or score < 0.5:
            continue
        # avg y of bounding box
        try:
            y = sum(pt[1] for pt in poly) / len(poly)
        except Exception:
            y = 0.0
        lines.append((y, text))

    lines.sort(key=lambda l: l[0])

    # Find item numbers; name is the nearest ALL CAPS line above each
    found: dict[str, str] = {}
    for idx, (y, line_text) in enumerate(lines):
        m = ITEM_NUM_RE.search(line_text)
        if not m:
            continue
        item_num = m.group(1)
        if item_num in found:
            continue
        for back in range(idx - 1, max(idx - 10, -1), -1):
            candidate = lines[back][1]
            if looks_like_name(candidate):
                found[item_num] = candidate
                break
    return found


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool, vision_only: bool, ocr_only: bool) -> None:
    # Load all placeholder products from DB grouped by page
    print("Loading placeholder products from DB...")
    rows = psql_query(
        "SELECT item_number, catalog_page FROM products "
        "WHERE name LIKE 'Item %' AND is_active = TRUE AND catalog_page IS NOT NULL "
        "ORDER BY catalog_page, item_number"
    )
    placeholder_items: dict[str, int] = {}   # item_number -> catalog_page
    pages_needed: set[int] = set()
    for row in rows:
        if len(row) >= 2:
            item_num, page = row[0].strip(), row[1].strip()
            if item_num and page:
                placeholder_items[item_num] = int(page)
                pages_needed.add(int(page))

    print(f"  {len(placeholder_items)} products still need names across {len(pages_needed)} pages")

    updates: dict[str, str] = {}

    # Step 1: vision.json
    if not ocr_only:
        vision_names = load_vision_names()
        applied = 0
        for item_num in list(placeholder_items.keys()):
            if item_num in vision_names:
                updates[item_num] = vision_names[item_num]
                applied += 1
        print(f"\nVision.json: {applied} names found for placeholder products")

    # Step 2: OCR remaining pages
    if not vision_only:
        remaining_items = {k: v for k, v in placeholder_items.items() if k not in updates}
        remaining_pages = set(remaining_items.values())
        print(f"\nOCR: scanning {len(remaining_pages)} pages for {len(remaining_items)} remaining products...")

        for page_num in sorted(remaining_pages):
            page_products = [k for k, v in remaining_items.items() if v == page_num]
            ocr_names = ocr_page(page_num)
            matched = 0
            for item_num in page_products:
                if item_num in ocr_names:
                    name = ocr_names[item_num]
                    updates[item_num] = name
                    matched += 1
                    print(f"  page {page_num:3d}: {item_num} -> {name}")
            if not matched:
                print(f"  page {page_num:3d}: no matches (products: {page_products})")

    print(f"\n{'='*60}")
    print(f"Total names found: {len(updates)} / {len(placeholder_items)}")
    still_missing = len(placeholder_items) - len(updates)
    print(f"Still missing:     {still_missing}")
    print()
    apply_updates(updates, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vision-only", action="store_true", help="Only apply vision.json names")
    parser.add_argument("--ocr-only", action="store_true", help="Skip vision.json, OCR only")
    args = parser.parse_args()
    run(args.dry_run, args.vision_only, args.ocr_only)


if __name__ == "__main__":
    main()
