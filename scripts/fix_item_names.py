from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg


DB_URL = "postgresql://fims:fims@localhost:5432/fims"
SCRIPT_DIR = Path(__file__).resolve().parent
VISION_PATH = SCRIPT_DIR / "catalogs" / "jakes" / "2026" / "vision.json"


def load_vision_name_map() -> dict[str, list[dict[str, str]]]:
    if not VISION_PATH.exists():
        raise FileNotFoundError(f"Missing vision file: {VISION_PATH}")

    data = json.loads(VISION_PATH.read_text(encoding="utf-8"))
    items: dict[str, list[dict[str, str]]] = defaultdict(list)

    for page in data.get("pages", []):
        page_num = page.get("page")
        for product in page.get("products", []):
            item_number = str(product.get("item_number") or "").strip()
            name = str(product.get("name") or "").strip()
            if item_number:
                items[item_number].append(
                    {
                        "name": name,
                        "page": str(page_num) if page_num is not None else "",
                    }
                )

    return items


def clean_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", str(name)).strip(" -_|\t\r\n")
    if not cleaned:
        return None
    if cleaned.lower().startswith("item "):
        return None
    return cleaned


def pick_vision_name(candidates: list[dict[str, str]]) -> str | None:
    for candidate in candidates:
        name = clean_name(candidate.get("name"))
        if name:
            return name
    return None


def main() -> int:
    vision_map = load_vision_name_map()

    conn = psycopg.connect(DB_URL, autocommit=False)
    updated = 0

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.item_number, p.name, b.name
                FROM products p
                JOIN product_brands b ON b.id = p.brand_id
                WHERE p.name LIKE 'Item %%'
                  AND (b.name ILIKE '%%World Class%%' OR b.name ILIKE '%%Jake%%')
                ORDER BY p.item_number
                """
            )
            rows = cur.fetchall()

            for product_id, item_number, current_name, brand_name in rows:
                item_number = str(item_number or "").strip()
                if not item_number:
                    print(f"missing item_number for product {product_id} ({current_name})")
                    continue

                candidates = vision_map.get(item_number, [])
                new_name = pick_vision_name(candidates)
                if new_name and new_name != current_name:
                    cur.execute(
                        "UPDATE products SET name=%s, updated_at=%s WHERE id=%s",
                        (new_name, datetime.now(timezone.utc), product_id),
                    )
                    updated += 1
                    print(f"updated {item_number}: {current_name!r} -> {new_name!r} [{brand_name}]")
                    continue

                printable = [
                    {
                        "name": candidate.get("name"),
                        "page": candidate.get("page"),
                    }
                    for candidate in candidates
                ]
                print(f"no usable vision name for {item_number} ({brand_name}); candidates={printable}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    with psycopg.connect(DB_URL, autocommit=True) as verify_conn:
        with verify_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM products p
                JOIN product_brands b ON b.id = p.brand_id
                WHERE p.name LIKE 'Item %%'
                  AND (b.name ILIKE '%%World Class%%' OR b.name ILIKE '%%Jake%%')
                """
            )
            remaining = cur.fetchone()[0]

    print(f"Updated: {updated}")
    print(f"Still have no name: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
