#!/usr/bin/env python3
"""Enrich in-store products from local scraped evidence.

Report mode proposes fills for currently-missing product fields and writes JSON
and Markdown review artifacts. Apply mode recomputes the same proposals,
writes a reversible backup, and updates only the proposed fields.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql


DSN = "postgresql://fims:fims@100.73.208.99:5432/fims"

ROOT_DIR = Path(__file__).resolve().parents[2]
AUDIT_DIR = Path(__file__).resolve().parent

JAKES_CATALOG_PATH = ROOT_DIR / "scripts" / "jakes_catalog.json"
JAKES_VISION_PATH = ROOT_DIR / "scripts" / "catalogs" / "jakes" / "2026" / "vision.json"
GOTFIREWORKS_PATH = (
    ROOT_DIR / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_scraped.json"
)
PYROMANIACS_PATH = ROOT_DIR / "scripts" / "catalogs" / "pyromaniacs" / "2026" / "products.json"

REPORT_JSON_PATH = AUDIT_DIR / "enrich_instore.json"
REPORT_MD_PATH = AUDIT_DIR / "enrich_instore.md"
BACKUP_JSON_PATH = AUDIT_DIR / "enrich_instore_backup.json"

FIELD_ORDER = (
    "shot_count",
    "duration_seconds",
    "effects",
    "packing",
    "description",
    "category_id",
)

WORLD_CLASS_BRAND_ID = 45
RM_BRAND_IDS = {1, 5}
RM_BRAND_NAMES = {
    "no name",
    "sunwing",
    "pyro box",
    "suns",
    "supreme",
    "miracle",
    "top gun",
}

CATEGORY_KEY_RE = re.compile(r"\s+")
PACKING_CODE_RE = re.compile(r"^\d+/\d+$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_item_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def normalize_category_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("-", " ").replace("_", " ")
    text = CATEGORY_KEY_RE.sub(" ", text)
    return text.strip()


def category_variants(value: Any) -> set[str]:
    normalized = normalize_category_key(value)
    if not normalized:
        return set()
    variants = {normalized}
    if normalized.endswith("s"):
        variants.add(normalized[:-1].rstrip())
    return {item for item in variants if item}


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def clean_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def load_json_list(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def load_json_object(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}


def flatten_vision_products(payload: dict[str, Any]) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for page in payload.get("pages", []):
        if not isinstance(page, dict):
            continue
        for product in page.get("products", []):
            if isinstance(product, dict):
                products.append(product)
    return products


def index_records(records: list[dict[str, Any]], key_field: str) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = normalize_item_key(record.get(key_field))
        if key:
            indexed[key].append(record)
    return dict(indexed)


def load_evidence() -> dict[str, dict[str, list[dict[str, Any]]]]:
    jakes_catalog = load_json_list(JAKES_CATALOG_PATH)
    jakes_vision = flatten_vision_products(load_json_object(JAKES_VISION_PATH))
    gotfireworks = load_json_list(GOTFIREWORKS_PATH)
    pyromaniacs_payload = load_json_object(PYROMANIACS_PATH)
    pyromaniacs = [item for item in pyromaniacs_payload.get("products", []) if isinstance(item, dict)]

    return {
        "jakes_catalog": index_records(jakes_catalog, "item_number"),
        "jakes_vision": index_records(jakes_vision, "item_number"),
        "gotfireworks": index_records(gotfireworks, "sku"),
        "pyromaniacs": index_records(pyromaniacs, "sku"),
    }


def fetch_products_and_categories() -> tuple[list[dict[str, Any]], dict[str, int]]:
    sql_text = """
        SELECT
            p.id::text AS id,
            p.item_number::text AS item_number,
            p.name AS name,
            p.description AS description,
            p.category_id AS category_id,
            p.brand_id AS brand_id,
            b.name AS brand_name,
            p.shot_count AS shot_count,
            p.duration_seconds AS duration_seconds,
            p.effects AS effects,
            p.packing AS packing
        FROM products p
        LEFT JOIN product_brands b
            ON b.id = p.brand_id
        WHERE p.in_store = true
        ORDER BY p.name, p.id
    """
    category_sql = """
        SELECT id, name
        FROM product_categories
    """

    with psycopg.connect(DSN) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql_text)
            products = [
                {
                    "id": row[0],
                    "item_number": row[1],
                    "name": row[2],
                    "description": row[3],
                    "category_id": row[4],
                    "brand_id": row[5],
                    "brand_name": row[6],
                    "shot_count": row[7],
                    "duration_seconds": row[8],
                    "effects": row[9],
                    "packing": row[10],
                }
                for row in cur.fetchall()
            ]

            cur.execute(category_sql)
            category_map: dict[str, int] = {}
            for category_id, category_name in cur.fetchall():
                for variant in category_variants(category_name):
                    category_map.setdefault(variant, int(category_id))

    return products, category_map


def brand_group(product: dict[str, Any]) -> str:
    brand_id = product.get("brand_id")
    brand_name = normalize_category_key(product.get("brand_name"))
    if brand_id == WORLD_CLASS_BRAND_ID:
        return "world_class"
    if brand_id in RM_BRAND_IDS or brand_name in RM_BRAND_NAMES:
        return "rm"
    return "default"


def evidence_records(
    evidence: dict[str, dict[str, list[dict[str, Any]]]],
    source: str,
    product_key: str,
) -> list[dict[str, Any]]:
    return evidence.get(source, {}).get(product_key, [])


def valid_description(text: Any) -> str | None:
    description = clean_text(text)
    if not description:
        return None
    if len(description) < 20:
        return None
    if PACKING_CODE_RE.fullmatch(description):
        return None
    return description


def clean_packing(value: Any) -> str | None:
    """Normalize a packing code: strip Excel text-marker apostrophes/whitespace and
    accept only real codes like ``18/1`` / ``24/6``. Rejects values like ``49 shot``."""
    text = clean_text(value)
    if not text:
        return None
    text = text.lstrip("'\"").strip()
    if re.fullmatch(r"\d+\s*/\s*\d+", text):
        return re.sub(r"\s+", "", text)
    return None


def join_effects(record: dict[str, Any]) -> str | None:
    pieces: list[str] = []
    seen: set[str] = set()
    for key in ("colors", "effects"):
        values = record.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            text = clean_text(value)
            if not text:
                continue
            marker = text.lower()
            if marker in seen:
                continue
            seen.add(marker)
            pieces.append(text)
    if not pieces:
        return None
    return ", ".join(pieces)


def extract_candidate(
    source: str,
    field: str,
    record: dict[str, Any],
    category_map: dict[str, int],
) -> tuple[Any | None, str | None]:
    if field == "shot_count":
        if source == "jakes_catalog":
            return clean_int(record.get("shot_count")), "jakes_catalog.shot_count"
        if source == "jakes_vision":
            return clean_int(record.get("shell_count")), "jakes_vision.shell_count"
        if source == "gotfireworks":
            return clean_int(record.get("shot_count")), "gotfireworks.shot_count"
        if source == "pyromaniacs":
            return clean_int(record.get("shot_count")), "pyromaniacs.shot_count"
    elif field == "duration_seconds":
        if source == "jakes_catalog":
            return clean_int(record.get("duration_seconds")), "jakes_catalog.duration_seconds"
        if source == "gotfireworks":
            return clean_int(record.get("duration_seconds")), "gotfireworks.duration_seconds"
        if source == "pyromaniacs":
            return clean_int(record.get("duration_seconds")), "pyromaniacs.duration_seconds"
    elif field == "effects":
        if source == "jakes_catalog":
            return join_effects(record), "jakes_catalog.colors/effects"
    elif field == "packing":
        if source == "jakes_vision":
            return clean_packing(record.get("packing")), "jakes_vision.packing"
        if source == "gotfireworks":
            return clean_packing(record.get("case_packing")), "gotfireworks.case_packing"
        if source == "pyromaniacs":
            return clean_packing(record.get("description")), "pyromaniacs.description"
    elif field == "description":
        if source == "jakes_catalog":
            return valid_description(record.get("description")), "jakes_catalog.description"
        if source == "jakes_vision":
            return valid_description(record.get("description")), "jakes_vision.description"
        if source == "gotfireworks":
            return valid_description(record.get("description")), "gotfireworks.description"
    elif field == "category_id":
        if source == "jakes_catalog":
            raw = clean_text(record.get("category"))
            if not raw:
                return None, None
            for variant in category_variants(raw):
                mapped = category_map.get(variant)
                if mapped is not None:
                    return mapped, "jakes_catalog.category"
            return raw, "jakes_catalog.category"
        if source == "pyromaniacs":
            raw = clean_text(record.get("category"))
            if not raw:
                return None, None
            for variant in category_variants(raw):
                mapped = category_map.get(variant)
                if mapped is not None:
                    return mapped, "pyromaniacs.category"
            return raw, "pyromaniacs.category"
    return None, None


SOURCE_ORDERS: dict[str, dict[str, list[str]]] = {
    "world_class": {
        "shot_count": ["jakes_catalog", "jakes_vision", "gotfireworks", "pyromaniacs"],
        "duration_seconds": ["jakes_catalog", "gotfireworks", "pyromaniacs", "jakes_vision"],
        "effects": ["jakes_catalog"],
        "packing": ["jakes_vision", "gotfireworks", "pyromaniacs"],
        "description": ["jakes_catalog", "jakes_vision", "gotfireworks"],
        "category_id": ["jakes_catalog", "pyromaniacs"],
    },
    "rm": {
        "shot_count": ["gotfireworks", "pyromaniacs", "jakes_catalog", "jakes_vision"],
        "duration_seconds": ["gotfireworks", "pyromaniacs", "jakes_catalog", "jakes_vision"],
        "effects": ["jakes_catalog"],
        "packing": ["gotfireworks", "pyromaniacs", "jakes_vision"],
        "description": ["gotfireworks", "jakes_catalog", "jakes_vision"],
        "category_id": ["pyromaniacs", "jakes_catalog"],
    },
    "default": {
        "shot_count": ["jakes_catalog", "jakes_vision", "gotfireworks", "pyromaniacs"],
        "duration_seconds": ["jakes_catalog", "gotfireworks", "pyromaniacs", "jakes_vision"],
        "effects": ["jakes_catalog"],
        "packing": ["jakes_vision", "gotfireworks", "pyromaniacs"],
        "description": ["jakes_catalog", "jakes_vision", "gotfireworks"],
        "category_id": ["jakes_catalog", "pyromaniacs"],
    },
}


def select_proposals(
    product: dict[str, Any],
    evidence: dict[str, dict[str, list[dict[str, Any]]]],
    category_map: dict[str, int],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    group = brand_group(product)
    orders = SOURCE_ORDERS[group]
    product_key = normalize_item_key(product.get("item_number"))
    proposed: dict[str, dict[str, Any]] = {}
    unmapped_category: str | None = None

    for field in FIELD_ORDER:
        current = product.get(field)
        if not is_missing(current):
            continue

        if field == "category_id":
            for source in orders[field]:
                for record in evidence_records(evidence, source, product_key):
                    candidate, candidate_source = extract_candidate(source, field, record, category_map)
                    if candidate_source is None:
                        continue
                    if isinstance(candidate, int):
                        proposed[field] = {
                            "current": current,
                            "value": candidate,
                            "source": candidate_source,
                        }
                    else:
                        unmapped_category = str(candidate)
                    break
                if field in proposed or unmapped_category is not None:
                    break
            continue

        for source in orders[field]:
            for record in evidence_records(evidence, source, product_key):
                candidate, candidate_source = extract_candidate(source, field, record, category_map)
                if candidate_source is None or candidate is None:
                    continue
                proposed[field] = {
                    "current": current,
                    "value": candidate,
                    "source": candidate_source,
                }
                break
            if field in proposed:
                break

    return proposed, unmapped_category


def build_report(
    products: list[dict[str, Any]],
    evidence: dict[str, dict[str, list[dict[str, Any]]]],
    category_map: dict[str, int],
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    unmapped_counts: Counter[str] = Counter()

    for product in products:
        proposed, unmapped_category = select_proposals(product, evidence, category_map)
        if not proposed:
            continue

        for field in proposed:
            field_counts[field] += 1
        if unmapped_category:
            unmapped_counts[unmapped_category] += 1

        entry: dict[str, Any] = {
            "id": product["id"],
            "item_number": product["item_number"],
            "name": product["name"],
            "brand_id": product["brand_id"],
            "proposed": proposed,
        }
        if unmapped_category:
            entry["unmapped_category"] = unmapped_category
        rows.append(entry)

    return rows, field_counts, unmapped_counts


def render_markdown(
    rows: list[dict[str, Any]],
    field_counts: Counter[str],
    unmapped_counts: Counter[str],
) -> str:
    lines: list[str] = []
    lines.append("# enrich_instore")
    lines.append("")
    lines.append(f"- Total products with proposals: {len(rows)}")
    lines.append("")
    lines.append("## Per-field fill counts")
    lines.append("")
    lines.append("| field | count |")
    lines.append("| --- | ---: |")
    for field in FIELD_ORDER:
        lines.append(f"| {field} | {field_counts.get(field, 0)} |")
    lines.append("")
    lines.append("## Unmapped categories")
    lines.append("")
    if unmapped_counts:
        lines.append("| category string | count |")
        lines.append("| --- | ---: |")
        for category, count in sorted(unmapped_counts.items(), key=lambda item: (-item[1], item[0].lower())):
            lines.append(f"| {escape_md(category)} | {count} |")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Products")
    lines.append("")
    lines.append("| item_number | name | fields being filled |")
    lines.append("| --- | --- | --- |")
    for row in rows:
        fields = ", ".join(row["proposed"].keys())
        lines.append(
            f"| {escape_md(row['item_number'])} | {escape_md(row['name'])} | {escape_md(fields)} |"
        )
    lines.append("")
    return "\n".join(lines)


def escape_md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build_updates(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    backup_rows: list[dict[str, Any]] = []
    field_count = 0
    for row in rows:
        for field, proposed in row["proposed"].items():
            backup_rows.append(
                {
                    "id": row["id"],
                    "item_number": row["item_number"],
                    "field": field,
                    "old_value": proposed["current"],
                }
            )
            field_count += 1
    return backup_rows, field_count


def apply_updates(rows: list[dict[str, Any]]) -> tuple[int, int]:
    product_count = 0
    field_count = 0

    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            for row in rows:
                fields = [field for field in FIELD_ORDER if field in row["proposed"]]
                if not fields:
                    continue
                assignments = [sql.SQL("{} = %s").format(sql.Identifier(field)) for field in fields]
                assignments.append(sql.SQL("updated_at = now()"))
                statement = sql.SQL("UPDATE products SET {} WHERE id = %s").format(
                    sql.SQL(", ").join(assignments)
                )
                params = [row["proposed"][field]["value"] for field in fields] + [row["id"]]
                cur.execute(statement, params)
                product_count += 1
                field_count += len(fields)
        conn.commit()

    return product_count, field_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich in-store products from local evidence")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write reversible updates to the database instead of report-only output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = load_evidence()
    products, category_map = fetch_products_and_categories()
    rows, field_counts, unmapped_counts = build_report(products, evidence, category_map)

    if args.apply:
        backup_rows, _ = build_updates(rows)
        write_json(BACKUP_JSON_PATH, backup_rows)
        product_count, field_count = apply_updates(rows)
        print(f"products updated: {product_count}")
        print(f"fields updated: {field_count}")
        return

    REPORT_JSON_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    REPORT_MD_PATH.write_text(render_markdown(rows, field_counts, unmapped_counts), encoding="utf-8")
    print(f"total products with proposals: {len(rows)}")
    for field in FIELD_ORDER:
        print(f"{field}: {field_counts.get(field, 0)}")
if __name__ == "__main__":
    main()
