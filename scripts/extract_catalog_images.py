"""Extract individual product photos from Jake's 2026 catalog pages.

Strategy: saturation-based blob detection in HSV space isolates colorful product
photos from the white/gray text background. Blobs sorted top-left → bottom-right
are matched positionally to SKUs from the DB (or text_layer.json fallback).

Run:
    python scripts/extract_catalog_images.py
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
CATALOG_DIR = SCRIPTS_DIR / "catalogs" / "jakes" / "2026"
PAGES_DIR = CATALOG_DIR / "pages"
OUTPUT_DIR = CATALOG_DIR / "product_images"
ISSUE_LOG = OUTPUT_DIR / "crop_issues.txt"
TEXT_LAYER = CATALOG_DIR / "text_layer.json"

START_PAGE = 11
END_PAGE = 163   # 164+ are apparel/signs, not fireworks products

# ── Tuning ─────────────────────────────────────────────────────────────────────
SAT_THRESH = 60        # HSV saturation threshold
VAL_THRESH = 50        # HSV value threshold
DILATE_ITER = 3
ERODE_ITER = 2
KERNEL_SIZE = 15
MIN_AREA_RATIO = 0.015  # blob must be ≥1.5% of content area
LEFT_TRIM_RATIO = 0.06  # colored sidebar to skip
CROP_PAD = 20           # px padding around each crop


# ── DB / text-layer lookup ─────────────────────────────────────────────────────

def load_page_skus() -> dict[int, list[str]]:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://fims:fims@localhost:5432/fims",
    ).replace("postgresql+psycopg://", "postgresql://")
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT catalog_page, item_number FROM products "
                "WHERE catalog_page IS NOT NULL AND item_number IS NOT NULL AND is_active = TRUE "
                "ORDER BY catalog_page, item_number"
            ).fetchall()
        mapping: dict[int, list[str]] = defaultdict(list)
        for page, sku in rows:
            mapping[int(page)].append(str(sku))
        total = sum(len(v) for v in mapping.values())
        print(f"DB: {total} SKUs across {len(mapping)} pages")
        return dict(mapping)
    except Exception as exc:
        print(f"DB unavailable ({exc}) — falling back to text_layer.json")

    if not TEXT_LAYER.exists():
        print("No text_layer.json found; running without SKU mapping")
        return {}

    mapping = defaultdict(list)
    data = json.loads(TEXT_LAYER.read_text())
    for entry in data:
        page = entry.get("page_number")
        skus = entry.get("item_numbers") or []
        if page:
            for sku in skus:
                mapping[int(page)].append(str(sku))
    total = sum(len(v) for v in mapping.values())
    print(f"text_layer.json: {total} SKUs across {len(mapping)} pages")
    return dict(mapping)


# ── Image processing ───────────────────────────────────────────────────────────

def detect_blobs(img: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Return (content_strip, [(x,y,w,h), ...]) sorted top-left → bottom-right."""
    h, w = img.shape[:2]
    left = int(w * LEFT_TRIM_RATIO)
    content = img[:, left:]
    ch, cw = content.shape[:2]

    hsv = cv2.cvtColor(content, cv2.COLOR_BGR2HSV)
    sat_mask = (hsv[:, :, 1] > SAT_THRESH) & (hsv[:, :, 2] > VAL_THRESH)
    mask = sat_mask.astype(np.uint8) * 255

    kernel = np.ones((KERNEL_SIZE, KERNEL_SIZE), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=DILATE_ITER)
    mask = cv2.erode(mask, kernel, iterations=ERODE_ITER)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = ch * cw * MIN_AREA_RATIO

    blobs: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh < min_area:
            continue
        if x < 40 and bh > ch * 0.5:          # left decorative sidebar
            continue
        if x + bw > cw * 0.90 and bh > ch * 0.5:  # right decorative sidebar
            continue
        blobs.append((x, y, bw, bh))

    # Sort top-left → bottom-right in roughly page-height/3 row bands
    row_band = max(1, ch // 3)
    blobs.sort(key=lambda b: (b[1] // row_band, b[0]))
    return content, blobs


def crop_blob(content: np.ndarray, blob: tuple[int, int, int, int], pad: int = CROP_PAD) -> np.ndarray:
    ch, cw = content.shape[:2]
    x, y, bw, bh = blob
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(cw, x + bw + pad)
    y2 = min(ch, y + bh + pad)
    return content[y1:y2, x1:x2]


def save_png(bgr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(str(path))


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ISSUE_LOG.unlink(missing_ok=True)

    page_skus = load_page_skus()

    total_saved = 0
    total_skipped = 0
    pages_ok = 0
    pages_mismatch = 0

    for page_num in range(START_PAGE, END_PAGE + 1):
        page_path = PAGES_DIR / f"page_{page_num:03d}.jpg"
        if not page_path.exists():
            continue

        img = cv2.imread(str(page_path), cv2.IMREAD_COLOR)
        if img is None:
            continue

        content, blobs = detect_blobs(img)
        skus = page_skus.get(page_num, [])
        n_blobs = len(blobs)
        n_skus = len(skus)
        matched = n_blobs == n_skus

        if matched:
            pages_ok += 1
            status = "ok"
        else:
            pages_mismatch += 1
            status = f"MISMATCH: {n_blobs} blobs vs {n_skus} SKUs"
            with ISSUE_LOG.open("a") as f:
                f.write(f"Page {page_num:03d}: {n_blobs} blobs, {n_skus} SKUs\n")

        print(f"Page {page_num:03d}: {n_blobs} blobs | {n_skus} SKUs  {status}")

        for i, blob in enumerate(blobs):
            crop = crop_blob(content, blob)

            if i < n_skus:
                out_path = OUTPUT_DIR / f"{skus[i]}.png"
            else:
                out_path = OUTPUT_DIR / f"page_{page_num:03d}_extra_{i + 1}.png"

            if out_path.exists():
                total_skipped += 1
                continue

            save_png(crop, out_path)
            total_saved += 1

    print()
    print(f"Pages matched:   {pages_ok}")
    print(f"Pages mismatch:  {pages_mismatch}")
    print(f"Crops saved:     {total_saved}")
    print(f"Crops skipped:   {total_skipped} (already existed)")
    if ISSUE_LOG.exists():
        print(f"Issue log:       {ISSUE_LOG}")


if __name__ == "__main__":
    main()
