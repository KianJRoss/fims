from __future__ import annotations

import json
from pathlib import Path

import psycopg

TEXT_LAYER_PATH = Path(__file__).resolve().parent / "catalogs" / "jakes" / "2026" / "text_layer.json"


def main() -> None:
    if not TEXT_LAYER_PATH.exists():
        raise FileNotFoundError(f"Not found: {TEXT_LAYER_PATH}")

    data = json.loads(TEXT_LAYER_PATH.read_text(encoding="utf-8"))
    results = data.get("results", [])

    updated = 0
    already_set = 0
    not_found = 0

    with psycopg.connect("postgresql://fims:fims@localhost:5432/fims") as conn:
        with conn.cursor() as cur:
            for result in results:
                packing = result.get("packing")
                item_number = result.get("item_number")
                if packing is None or not item_number:
                    continue

                cur.execute("SELECT packing FROM products WHERE item_number = %s LIMIT 1", (item_number,))
                row = cur.fetchone()
                if row is None:
                    not_found += 1
                    continue

                if row[0] is not None:
                    already_set += 1
                    continue

                cur.execute(
                    "UPDATE products SET packing = %s WHERE item_number = %s AND packing IS NULL",
                    (packing, item_number),
                )
                updated += cur.rowcount

        conn.commit()

    print(f"updated={updated} already_set={already_set} not_found={not_found}")


if __name__ == "__main__":
    main()
