# pip install opencv-python rembg Pillow numpy
"""Extract product images from Jake's 2026 catalog pages."""

from __future__ import annotations

import io
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg import remove


SCRIPTS_DIR = Path(__file__).resolve().parent
CATALOG_DIR = SCRIPTS_DIR / "catalogs" / "jakes" / "2026"
PAGES_DIR = CATALOG_DIR / "pages"
TEXT_LAYER_PATH = CATALOG_DIR / "text_layer.json"
OUTPUT_DIR = CATALOG_DIR / "product_images"
ISSUE_LOG_PATH = OUTPUT_DIR / "crop_issues.txt"

START_PAGE = 11
END_PAGE = 163

RIGHT_TRIM_RATIO = 0.08
BOTTOM_TRIM_RATIO = 0.06
ALPHA_THRESHOLD = 10
MIN_BLOB_AREA_RATIO = 0.01
MERGE_DISTANCE_PX = 20
CROP_PADDING_PX = 10


@dataclass(frozen=True)
class Blob:
    left: int
    top: int
    width: int
    height: int
    centroid_x: float
    centroid_y: float
    area: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, a: int, b: int) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1


def build_page_sku_map(results: list[dict]) -> dict[int, list[str]]:
    page_to_skus: dict[int, list[str]] = defaultdict(list)
    for result in results:
        page = result.get("page")
        sku = result.get("item_number")
        if isinstance(page, int) and sku:
            page_to_skus[page].append(str(sku))
    return dict(page_to_skus)


def load_text_layer_map(text_layer_path: Path) -> dict[int, list[str]]:
    data = json.loads(text_layer_path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    if not isinstance(results, list):
        raise ValueError("text_layer.json does not contain a results list")
    return build_page_sku_map(results)


def trim_page_image(image_bgr: np.ndarray) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    trimmed_height = max(1, int(round(height * (1.0 - BOTTOM_TRIM_RATIO))))
    trimmed_width = max(1, int(round(width * (1.0 - RIGHT_TRIM_RATIO))))
    return image_bgr[:trimmed_height, :trimmed_width].copy()


def normalize_rgba_image(image: object) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGBA")
    if isinstance(image, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(image))).convert("RGBA")
    if isinstance(image, np.ndarray):
        array = image
    else:
        array = np.asarray(image)
    pil_image = Image.fromarray(array)
    return pil_image.convert("RGBA")


def remove_background(trimmed_bgr: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(trimmed_bgr, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    removed = remove(pil_image)
    rgba = normalize_rgba_image(removed)
    return np.array(rgba, dtype=np.uint8)


def extract_blobs_from_alpha(rgba_image: np.ndarray) -> list[Blob]:
    alpha = rgba_image[:, :, 3]
    mask = (alpha > ALPHA_THRESHOLD).astype(np.uint8)
    image_area = int(rgba_image.shape[0] * rgba_image.shape[1])
    min_area = max(1, int(image_area * MIN_BLOB_AREA_RATIO))

    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    blobs: list[Blob] = []
    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        centroid_x = float(centroids[label, 0])
        centroid_y = float(centroids[label, 1])
        blobs.append(Blob(left, top, width, height, centroid_x, centroid_y, area))
    return blobs


def boxes_within_merge_distance(first: Blob, second: Blob) -> bool:
    gap_x = max(0, first.left - second.right, second.left - first.right)
    gap_y = max(0, first.top - second.bottom, second.top - first.bottom)
    return gap_x < MERGE_DISTANCE_PX and gap_y < MERGE_DISTANCE_PX


def merge_blob_group(blobs: list[Blob]) -> Blob:
    left = min(blob.left for blob in blobs)
    top = min(blob.top for blob in blobs)
    right = max(blob.right for blob in blobs)
    bottom = max(blob.bottom for blob in blobs)
    total_area = sum(blob.area for blob in blobs)
    if total_area > 0:
        centroid_x = sum(blob.centroid_x * blob.area for blob in blobs) / total_area
        centroid_y = sum(blob.centroid_y * blob.area for blob in blobs) / total_area
    else:
        centroid_x = (left + right) / 2.0
        centroid_y = (top + bottom) / 2.0
    return Blob(left, top, right - left, bottom - top, centroid_x, centroid_y, total_area)


def merge_blobs(blobs: list[Blob]) -> list[Blob]:
    if len(blobs) <= 1:
        return blobs[:]

    union_find = UnionFind(len(blobs))
    for index, first in enumerate(blobs):
        for other_index in range(index + 1, len(blobs)):
            second = blobs[other_index]
            if boxes_within_merge_distance(first, second):
                union_find.union(index, other_index)

    groups: dict[int, list[Blob]] = defaultdict(list)
    for index, blob in enumerate(blobs):
        groups[union_find.find(index)].append(blob)

    merged = [merge_blob_group(group) for group in groups.values()]
    return merged


def sort_blobs_for_reading(blobs: list[Blob], image_height: int) -> list[Blob]:
    half_height = max(1.0, image_height / 2.0)
    return sorted(
        blobs,
        key=lambda blob: (int(blob.centroid_y // half_height), blob.centroid_x, blob.centroid_y),
    )


def crop_blob(rgba_image: np.ndarray, blob: Blob) -> np.ndarray:
    height, width = rgba_image.shape[:2]
    left = max(0, blob.left - CROP_PADDING_PX)
    top = max(0, blob.top - CROP_PADDING_PX)
    right = min(width, blob.right + CROP_PADDING_PX)
    bottom = min(height, blob.bottom + CROP_PADDING_PX)
    return rgba_image[top:bottom, left:right].copy()


def append_issue(message: str) -> None:
    ISSUE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ISSUE_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def save_png(rgba_image: np.ndarray, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba_image, mode="RGBA").save(output_path)


def format_sku_list(skus: list[str]) -> str:
    return "[" + ", ".join(skus) + "]"


def process_page(page_num: int, skus: list[str]) -> tuple[int, int, bool]:
    page_path = PAGES_DIR / f"page_{page_num:03d}.jpg"
    if not page_path.exists():
        print(f"Page {page_num:03d}: missing image, skipped")
        return 0, 0, False

    if not skus:
        print(f"Page {page_num:03d}: no SKUs, skipped")
        return 0, 0, False

    image_bgr = cv2.imread(str(page_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        append_issue(f"Page {page_num:03d}: failed to load image {page_path}")
        print(f"Page {page_num:03d}: failed to load image, skipped")
        return 0, 0, True

    trimmed = trim_page_image(image_bgr)
    rgba_image = remove_background(trimmed)
    blobs = extract_blobs_from_alpha(rgba_image)
    merged_blobs = merge_blobs(blobs)
    sorted_blobs = sort_blobs_for_reading(merged_blobs, rgba_image.shape[0])

    print(
        f"Page {page_num:03d}: found {len(sorted_blobs)} objects, {len(skus)} SKUs -> {format_sku_list(skus)}"
    )

    page_issue = False
    if len(sorted_blobs) != len(skus):
        page_issue = True
        append_issue(
            f"Page {page_num:03d}: blob count {len(sorted_blobs)} did not match SKU count {len(skus)}"
        )

    saved = 0
    skipped = 0

    # Take the N largest blobs where N = number of SKUs on this page.
    # This handles decorative elements (stars, stickers, text boxes) that
    # rembg leaves visible — the actual product box is always the largest object.
    n = len(skus)
    chosen_blobs = sorted(merged_blobs, key=lambda b: b.area, reverse=True)[:n]
    # Re-sort chosen blobs in reading order for positional matching.
    chosen_blobs = sort_blobs_for_reading(chosen_blobs, rgba_image.shape[0])

    for sku, blob in zip(skus, chosen_blobs):
        output_path = OUTPUT_DIR / f"{sku}.png"
        if output_path.exists():
            skipped += 1
            continue
        crop = crop_blob(rgba_image, blob)
        save_png(crop, output_path)
        saved += 1

    return saved, skipped, page_issue


def main() -> None:
    if not TEXT_LAYER_PATH.exists():
        raise FileNotFoundError(f"Missing text layer JSON: {TEXT_LAYER_PATH}")

    page_to_skus = load_text_layer_map(TEXT_LAYER_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pages_processed = 0
    total_saved = 0
    total_skipped = 0
    pages_with_issues: set[int] = set()

    for page_num in range(START_PAGE, END_PAGE + 1):
        skus = page_to_skus.get(page_num, [])
        if not skus:
            print(f"Page {page_num:03d}: no SKUs, skipped")
            continue

        page_path = PAGES_DIR / f"page_{page_num:03d}.jpg"
        if not page_path.exists():
            print(f"Page {page_num:03d}: missing image, skipped")
            continue

        pages_processed += 1
        saved, skipped, issue = process_page(page_num, skus)
        total_saved += saved
        total_skipped += skipped
        if issue:
            pages_with_issues.add(page_num)

    print()
    print("Summary")
    print(f"Pages processed: {pages_processed}")
    print(f"Total saved: {total_saved}")
    print(f"Total skipped: {total_skipped}")
    print(f"Pages with issues: {len(pages_with_issues)}")
    if ISSUE_LOG_PATH.exists():
        print(f"Issue log: {ISSUE_LOG_PATH}")


if __name__ == "__main__":
    main()
