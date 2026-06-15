from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg


DB_URL = "postgresql://fims:fims@localhost:5432/fims"
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
DEFAULT_TEXT_LAYER = SCRIPTS_DIR / "catalogs" / "redrhino" / "2026" / "text_layer.json"
BRAND_NAME = "Red Rhino"

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
BARCODE_RE = re.compile(r"BARCODE[:\s]*(\d{8,14})", re.IGNORECASE)
PACKING_RE = re.compile(r"PACKING[:\s]*([0-9/]+)", re.IGNORECASE)


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


def page_segments(page: dict) -> list[str]:
    if "text" in page:
        return split_segments(page.get("text"))
    return [re.sub(r"\s+", " ", str(part)).strip() for part in page.get("raw_segments") or [] if str(part).strip()]


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


def first_name_before_sku(segments: list[str], sku_idx: int, limit: int = 5) -> str | None:
    start = max(0, sku_idx - limit)
    for idx in range(sku_idx - 1, start - 1, -1):
        if looks_like_name(segments[idx]):
            return re.sub(r"\s+", " ", segments[idx]).strip()
    return None


def first_name_after_sku(segments: list[str], sku_idx: int, next_sku_idx: int) -> str | None:
    for segment in segments[sku_idx + 1 : next_sku_idx]:
        if looks_like_name(segment):
            return re.sub(r"\s+", " ", segment).strip()
    return None


def name_score(name: str | None, position: str) -> tuple[int, int]:
    if not name:
        return (-1, -1)
    words = name.split()
    score = len(words)
    if position == "after":
        score += 2
    if len(words) > 1:
        score += 1
    return (score, len(name))


def choose_name(before: str | None, after: str | None) -> str | None:
    before_score = name_score(before, "before")
    after_score = name_score(after, "after")
    if after_score > before_score:
        return after
    if before_score > after_score:
        return before
    return after or before


def extract_description(segments: list[str], sku_idx: int, next_sku_idx: int) -> str | None:
    window = segments[sku_idx + 1 : next_sku_idx]
    description_parts: list[str] = []
    capturing = False

    for segment in window:
        text = segment.strip()
        if not text:
            continue
        if text.upper().startswith("DESCRIPTION:"):
            capturing = True
            description_parts.append(re.sub(r"^DESCRIPTION:\s*", "", text, flags=re.IGNORECASE).strip())
            continue
        if capturing:
            if text.upper().startswith("SKU:") or SKU_RE.fullmatch(text):
                break
            description_parts.append(text)

    description = " ".join(part for part in description_parts if part).strip()
    return description or None


def get_existing_columns(cur) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'products'
        """
    )
    return {row[0] for row in cur.fetchall()}


def get_brand_id(cur, brand_name: str) -> int:
    cur.execute("SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", (brand_name,))
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT INTO product_brands (name, tier, brand_type) VALUES (%s, 'tier1', 'house_brand') RETURNING id",
        (brand_name,),
    )
    return int(cur.fetchone()[0])


def parse_text_layer(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing text layer file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("pages") or data.get("results") or []


def extract_products(pages: list[dict]) -> list[dict]:
    seen: set[str] = set()
    products: list[dict] = []

    for page in pages:
        segments = page_segments(page)
        if not segments:
            continue

        sku_positions = find_sku_positions(segments)
        if not sku_positions:
            continue

        for pos_idx, (sku_idx, item_number) in enumerate(sku_positions):
            if not item_number or item_number in seen:
                continue

            next_sku_idx = sku_positions[pos_idx + 1][0] if pos_idx + 1 < len(sku_positions) else len(segments)
            before = first_name_before_sku(segments, sku_idx)
            after = first_name_after_sku(segments, sku_idx, next_sku_idx)
            name = choose_name(before, after)
            description = extract_description(segments, sku_idx, next_sku_idx)
            packing = None
            barcode = None
            window_text = " | ".join(segments[sku_idx:next_sku_idx])
            pack_match = PACKING_RE.search(window_text)
            if pack_match:
                packing = pack_match.group(1)
            barcode_match = BARCODE_RE.search(window_text)
            if barcode_match:
                barcode = barcode_match.group(1)

            seen.add(item_number)
            products.append(
                {
                    "item_number": item_number,
                    "name": name,
                    "description": description,
                    "packing": packing,
                    "barcode": barcode,
                    "page": page.get("page"),
                }
            )

    return products


def load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Red Rhino catalog products.")
    parser.add_argument(
        "text_layer",
        nargs="?",
        default=str(DEFAULT_TEXT_LAYER),
        help="Path to text_layer.json",
    )
    return parser.parse_args()


def main() -> int:
    args = load_args()
    pages = parse_text_layer(Path(args.text_layer))
    products = extract_products(pages)

    conn = psycopg.connect(DB_URL, autocommit=False)
    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            columns = get_existing_columns(cur)
            brand_id = get_brand_id(cur, BRAND_NAME)

            for product in products:
                item_number = product["item_number"]
                name = product["name"] or f"Item {item_number}"
                description = product["description"]
                page_num = product.get("page")
                barcode = product.get("barcode")

                cur.execute("SELECT id, name FROM products WHERE item_number = %s ORDER BY id LIMIT 1", (item_number,))
                existing = cur.fetchone()

                if existing:
                    product_id = existing[0]
                    set_parts = ["name=%s", "description=%s", "updated_at=%s"]
                    values: list[object] = [name, description, now]
                    if "brand_id" in columns:
                        set_parts.append("brand_id=%s")
                        values.append(brand_id)
                    if "brand" in columns:
                        set_parts.append("brand=%s")
                        values.append(BRAND_NAME)
                    if "catalog_page" in columns:
                        set_parts.append("catalog_page=%s")
                        values.append(page_num)
                    values.append(product_id)
                    cur.execute(
                        f"UPDATE products SET {', '.join(set_parts)} WHERE id=%s",
                        values,
                    )
                    updated += 1
                else:
                    product_id = str(uuid.uuid4())
                    insert_cols = ["id", "name", "item_number", "description", "created_at", "updated_at"]
                    insert_vals: list[object] = [product_id, name, item_number, description, now, now]
                    placeholders = ["%s"] * len(insert_cols)
                    if "brand_id" in columns:
                        insert_cols.append("brand_id")
                        insert_vals.append(brand_id)
                        placeholders.append("%s")
                    if "brand" in columns:
                        insert_cols.append("brand")
                        insert_vals.append(BRAND_NAME)
                        placeholders.append("%s")
                    if "catalog_page" in columns:
                        insert_cols.append("catalog_page")
                        insert_vals.append(page_num)
                        placeholders.append("%s")
                    cur.execute(
                        f"INSERT INTO products ({', '.join(insert_cols)}) VALUES ({', '.join(placeholders)})",
                        insert_vals,
                    )
                    inserted += 1

                if barcode:
                    cur.execute(
                        """
                        INSERT INTO product_barcodes (product_id, barcode, barcode_type, is_primary)
                        VALUES (%s, %s, 'UPC', true)
                        ON CONFLICT DO NOTHING
                        """,
                        (product_id, barcode),
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Found: {len(products)}")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
