from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
JSON_INPUT = SCRIPT_DIR / "jakes_catalog.json"
SQL_OUTPUT = SCRIPT_DIR / "jakes_seed.sql"
DEFAULT_API_URL = "http://localhost:8000"
BRAND_NAME = "Jake's Fireworks"


def load_catalog() -> list[dict[str, Any]]:
    with JSON_INPUT.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("jakes_catalog.json must contain a JSON array")
    return [item for item in data if isinstance(item, dict)]


def q_escape(value: str) -> str:
    return value.replace("'", "''")


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str) and not value.strip():
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    return f"'{q_escape(str(value))}'"


def join_effects(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        joined = ",".join(str(item) for item in value if str(item).strip())
        return joined or None
    text = str(value).strip()
    return text or None


def build_seed_sql(products: list[dict[str, Any]]) -> str:
    lines: list[str] = ["CREATE EXTENSION IF NOT EXISTS pgcrypto;", "BEGIN;"]
    lines.append(
        "INSERT INTO product_brands (name) VALUES ('Jake''s Fireworks') ON CONFLICT (name) DO NOTHING;"
    )

    for product in products:
        name = str(product.get("name") or "").strip()
        if not name:
            continue

        item_number = product.get("item_number")
        description = product.get("description")
        effects = join_effects(product.get("effects"))
        shot_count = product.get("shot_count")
        duration_seconds = product.get("duration_seconds")

        values = [
            "gen_random_uuid()",
            sql_literal(name),
            sql_literal(item_number),
            sql_literal(description),
            sql_literal(effects),
            sql_literal(shot_count),
            sql_literal(duration_seconds),
            "TRUE",
            "NOW()",
            "NOW()",
        ]
        lines.append(
            "INSERT INTO products (id, name, item_number, description, effects, shot_count, duration_seconds, is_active, created_at, updated_at) "
            f"VALUES ({', '.join(values)}) ON CONFLICT (id) DO NOTHING;"
        )

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def product_exists(session: requests.Session, api_url: str, item_number: str) -> bool:
    response = session.get(f"{api_url.rstrip('/')}/v1/products/", params={"q": item_number}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return False
    for item in payload:
        if isinstance(item, dict) and str(item.get("item_number") or "") == item_number:
            return True
    return False


def create_product(session: requests.Session, api_url: str, product: dict[str, Any]) -> requests.Response:
    payload = {
        "name": product.get("name"),
        "item_number": product.get("item_number"),
        "description": product.get("description"),
        "effects": join_effects(product.get("effects")),
        "shot_count": product.get("shot_count"),
        "duration_seconds": product.get("duration_seconds"),
        "category_name": product.get("category"),
        "brand_name": BRAND_NAME,
        "source_url": product.get("url"),
        "image_url": product.get("image_url"),
    }
    return session.post(f"{api_url.rstrip('/')}/v1/products/", json=payload, timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Jake's catalog into FIMS and generate SQL.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="FIMS API base URL.")
    parser.add_argument("--dry-run", action="store_true", help="Skip POST requests and only print actions.")
    parser.add_argument("--sql-only", action="store_true", help="Skip API calls and only generate SQL.")
    args = parser.parse_args()

    products = load_catalog()
    sql_output = build_seed_sql(products)
    SQL_OUTPUT.write_text(sql_output, encoding="utf-8")

    created = 0
    skipped = 0
    errors = 0

    if args.sql_only:
        print(f"SQL generated: {SQL_OUTPUT}")
        print(f"Final summary: total scraped={len(products)}, created=0, skipped={sum(1 for p in products if not str(p.get('name') or '').strip())}, errors=0")
        return 0

    session = requests.Session()

    for product in products:
        name = str(product.get("name") or "").strip()
        if not name:
            skipped += 1
            continue

        item_number = str(product.get("item_number") or "").strip()
        if not item_number:
            item_number = ""

        try:
            exists = False
            if item_number:
                exists = product_exists(session, args.api_url, item_number)

            if exists:
                print(f"Skipped (exists): {name}")
                skipped += 1
                continue

            if args.dry_run:
                print(f"Would create: {name}")
                created += 1
                continue

            response = create_product(session, args.api_url, product)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text.strip()}")

            print(f"Created: {name}")
            created += 1
        except Exception as exc:
            errors += 1
            print(f"Error: {name} — {exc}")

    print(f"Final summary: total scraped={len(products)}, created={created}, skipped={skipped}, errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
