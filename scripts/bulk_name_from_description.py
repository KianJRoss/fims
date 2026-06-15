from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg


DB_URL = "postgresql://fims:fims@localhost:5432/fims"
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.worker.tasks.issuu_import import extract_name_from_description  # noqa: E402


def is_placeholder_name(name: str | None, item_number: str | None) -> bool:
    if not name:
        return True
    if not item_number:
        return name.strip().lower().startswith("item ")
    return name.strip().lower() == f"item {str(item_number).strip().lower()}"


def main() -> int:
    conn = psycopg.connect(DB_URL, autocommit=False)
    updated = 0
    skipped = 0

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, item_number, name, description
                FROM products
                WHERE name LIKE 'Item %%'
                ORDER BY item_number
                """
            )
            rows = cur.fetchall()

            for product_id, item_number, current_name, description in rows:
                extracted = extract_name_from_description(description)
                if not extracted or is_placeholder_name(extracted, item_number):
                    skipped += 1
                    continue

                if extracted == current_name:
                    skipped += 1
                    continue

                cur.execute(
                    "UPDATE products SET name=%s, updated_at=%s WHERE id=%s",
                    (extracted, datetime.now(timezone.utc), product_id),
                )
                updated += 1
                print(f"updated {item_number}: {current_name!r} -> {extracted!r}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
