from __future__ import annotations

import json
import re
from pathlib import Path

import psycopg

try:
    from bulk_name_from_description import extract_name_from_description
except ModuleNotFoundError:  # pragma: no cover - local execution fallback
    import sys

    SCRIPT_DIR = Path(__file__).resolve().parent
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from bulk_name_from_description import extract_name_from_description


DB_URL = "postgresql://fims:fims@localhost:5432/fims"
SCRIPT_DIR = Path(__file__).resolve().parent
VISION_PATH = SCRIPT_DIR / "catalogs" / "jakes" / "2026" / "vision.json"

SKIP_NAMES = {
    "ASSORTMENTS",
    "ARTILLERY SHELLS",
    "ARTILLERY SHELL",
    "500 GRAM CAKES",
    "200 GRAM CAKES",
    "Z CAKES",
    "3 INCH 500 GRAM CAKES",
    "SATURN MISSILES",
    "SATURN MISSILE",
    "FOUNTAINS",
    "FIRECRACKERS",
    "SMOKE",
    "NOVELTIES",
    "PARACHUTES",
    "ROCKETS",
    "MISSILES",
    "ROMAN CANDLES",
    "SPARKLERS",
    "SHOW TO GO CARTONS",
    "WARNING",
    "WORLD-CLASS",
    "WORLD CLASS",
    "NEW FOR 2026",
    "PACKING",
    "BARCODE",
    "DESCRIPTION",
    "UNIT SIZE",
    "UNITSIZE",
}

SKU_RE = re.compile(r"SKU:\s*(\d{5,10})", re.IGNORECASE)
LONG_DIGITS_RE = re.compile(r"^\d{5,10}$")
NON_ALPHA_RE = re.compile(r"^[^A-Za-z]+$")


def split_segments(text: str | None) -> list[str]:
    raw = str(text or "")
    if " | " in raw:
        parts = raw.split(" | ")
    else:
        parts = raw.split("|")
    return [re.sub(r"\s+", " ", part).strip() for part in parts if part and part.strip()]


def has_all_caps_alpha(text: str) -> bool:
    alpha_chars = [ch for ch in text if ch.isalpha()]
    return bool(alpha_chars) and all(ch.isupper() for ch in alpha_chars)


def looks_like_name(segment: str) -> bool:
    candidate = re.sub(r"\s+", " ", segment).strip(" \t\r\n|")
    if not candidate or len(candidate) < 2 or len(candidate) > 50:
        return False
    if candidate[0].isdigit():
        return False
    if ":" in candidate:
        return False
    if NON_ALPHA_RE.fullmatch(candidate):
        return False
    if candidate.upper() in SKIP_NAMES:
        return False
    if not has_all_caps_alpha(candidate):
        return False
    words = candidate.split()
    return 1 <= len(words) <= 6


def page_item_numbers(page: dict) -> set[str]:
    item_numbers: set[str] = set()
    for product in page.get("products", []) or []:
        item_number = str(product.get("item_number") or "").strip()
        if item_number:
            item_numbers.add(item_number)
    return item_numbers


def find_sku_positions(segments: list[str]) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    for idx, segment in enumerate(segments):
        sku_match = SKU_RE.search(segment)
        if sku_match:
            positions.append((idx, sku_match.group(1)))
            continue

        compact = segment.replace(" ", "")
        if not LONG_DIGITS_RE.fullmatch(compact):
            continue

        nearby = " ".join(segments[max(0, idx - 2) : min(len(segments), idx + 3)]).upper()
        if "PACKING" in nearby or "BARCODE" in nearby or "DESCRIPTION" in nearby:
            positions.append((idx, compact))
    return positions


def find_name_after_sku(segments: list[str], sku_idx: int, next_sku_idx: int) -> str | None:
    for segment in segments[sku_idx + 1 : next_sku_idx]:
        if looks_like_name(segment):
            return re.sub(r"\s+", " ", segment).strip()
    return None


def build_name_map(pages: list[dict]) -> dict[str, str]:
    name_map: dict[str, str] = {}
    for page in pages:
        segments = split_segments(page.get("text"))
        if not segments:
            continue

        allowed_items = page_item_numbers(page)
        if not allowed_items:
            continue

        sku_positions = find_sku_positions(segments)
        for pos_idx, (sku_idx, item_number) in enumerate(sku_positions):
            if item_number in name_map or item_number not in allowed_items:
                continue

            next_sku_idx = sku_positions[pos_idx + 1][0] if pos_idx + 1 < len(sku_positions) else len(segments)
            name = find_name_after_sku(segments, sku_idx, next_sku_idx)
            if name:
                name_map[item_number] = name

    return name_map


def is_placeholder_name(name: str | None, item_number: str | None) -> bool:
    if not name:
        return True
    if not item_number:
        return name.strip().lower().startswith("item ")
    return name.strip().lower() == f"item {str(item_number).strip().lower()}"


def main() -> int:
    if not VISION_PATH.exists():
        raise FileNotFoundError(f"Missing vision file: {VISION_PATH}")

    data = json.loads(VISION_PATH.read_text(encoding="utf-8"))
    pages = data.get("pages") or data.get("results") or []
    name_map = build_name_map(pages)

    conn = psycopg.connect(DB_URL, autocommit=False)
    updated = 0

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM products
                WHERE name LIKE 'Item %%' AND item_number IS NOT NULL
                """
            )
            total_placeholder_products = int(cur.fetchone()[0])

            for item_number, name in sorted(name_map.items()):
                cur.execute(
                    "UPDATE products SET name=%s WHERE item_number=%s AND name LIKE 'Item %%'",
                    (name, item_number),
                )
                updated += cur.rowcount

            cur.execute(
                """
                SELECT id, item_number, name, description
                FROM products
                WHERE name LIKE 'Item %%' AND item_number IS NOT NULL
                """
            )
            remaining_rows = cur.fetchall()

            for product_id, item_number, current_name, description in remaining_rows:
                extracted = extract_name_from_description(description)
                if not extracted or is_placeholder_name(extracted, item_number):
                    continue
                if extracted == current_name:
                    continue

                cur.execute(
                    "UPDATE products SET name=%s WHERE id=%s",
                    (extracted, product_id),
                )
                updated += cur.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Updated {updated} / {total_placeholder_products} products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
