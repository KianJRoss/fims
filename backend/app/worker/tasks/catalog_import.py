from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app.worker.celery_app import celery_app

ITEM_CODE_RE = re.compile(r"^(?=[A-Z0-9]{3,12}$)(?=[^A-Z]*[A-Z])(?=[^0-9]*[0-9])[A-Z0-9]+$")
PACKING_RE = re.compile(r"^'\S+$|^\d+/\d+$")
PRICE_RE = re.compile(r"^\d+\.\d+$")
SHOT_RE = re.compile(r"(\d+)\s*[Ss]hots?")

DB_URL = "postgresql://fims:fims@postgres:5432/fims"


def is_item_code(line: str) -> bool:
    return bool(ITEM_CODE_RE.match(line.strip()))


def is_packing(line: str) -> bool:
    return bool(PACKING_RE.match(line.strip()))


def is_price(line: str) -> bool:
    return bool(PRICE_RE.match(line.strip()))


def is_category_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped != stripped.upper():
        return False
    if not re.search(r"\s", stripped):
        return False
    if not re.search(r"[A-Z]", stripped):
        return False
    return True


def parse_shot_count(description: str | None):
    if not description:
        return None
    match = SHOT_RE.search(description)
    if match:
        return int(match.group(1))
    return None


def extract_blocks_from_page(page_text: str):
    """
    Given raw page text, return:
      - category: str or None
      - products: list of parsed product dicts
    """
    lines = [line.strip() for line in page_text.split("\n")]
    item_code_positions = [i for i, line in enumerate(lines) if is_item_code(line)]
    if not item_code_positions:
        return None, []

    category = None
    for i in range(item_code_positions[0]):
        line = lines[i]
        if line and is_category_header(line):
            category = line

    products = []
    for idx, code_pos in enumerate(item_code_positions):
        name_lines = []
        i = code_pos - 1
        while i >= 0 and len(name_lines) < 2:
            line = lines[i]
            if not line:
                break
            if is_item_code(line) or is_price(line) or is_packing(line):
                break
            if any(c.islower() for c in line):
                break
            name_lines.insert(0, line)
            i -= 1

        name = " ".join(name_lines).strip()
        item_code = lines[code_pos]
        next_code = item_code_positions[idx + 1] if idx + 1 < len(item_code_positions) else len(lines)

        brand = None
        packing = None
        price = None
        desc_lines = []
        state = "brand"

        for j in range(code_pos + 1, next_code):
            line = lines[j]
            if not line:
                continue
            if state == "desc" and j >= next_code - 3:
                break
            if state == "brand":
                brand = line
                state = "packing_or_price"
            elif state == "packing_or_price":
                if is_packing(line):
                    packing = line
                    state = "price"
                elif is_price(line):
                    price = float(line)
                    state = "desc"
            elif state == "price":
                if is_price(line):
                    price = float(line)
                    state = "desc"
            elif state == "desc":
                if is_category_header(line):
                    category = line
                    break
                desc_lines.append(line)

        description = " ".join(desc_lines).strip()
        shot_count = parse_shot_count(description)

        if name and item_code and brand and price is not None:
            products.append(
                {
                    "name": name,
                    "item_code": item_code,
                    "brand": brand,
                    "packing": packing,
                    "price": price,
                    "description": description,
                    "shot_count": shot_count,
                    "category": category,
                }
            )
        else:
            products.append(
                {
                    "__invalid__": True,
                    "raw_name": name,
                    "item_code": item_code,
                    "brand": brand,
                    "price": price,
                    "desc_lines": desc_lines,
                    "packing": packing,
                    "description": description,
                    "shot_count": shot_count,
                    "category": category,
                }
            )

    return category, products


def parse_pdf(pdf_path: str):
    import fitz

    doc = fitz.open(pdf_path)
    all_products = []
    warnings = []
    current_category = None

    for page_num, page in enumerate(doc, start=1):
        if page_num <= 2:
            continue

        text = page.get_text("text")
        if not text.strip():
            continue

        category, products = extract_blocks_from_page(text)
        if category:
            current_category = category

        for product in products:
            if product.get("__invalid__"):
                warnings.append((page_num, product))
            else:
                if not product.get("category"):
                    product["category"] = current_category
                else:
                    current_category = product["category"]
            all_products.append((page_num, product))

    doc.close()
    return all_products, warnings


def _confidence_from_row(row: dict) -> float:
    if row.get("__invalid__"):
        if not (row.get("name") or row.get("raw_name")):
            return 0.5
        if row.get("price") is None:
            return 0.3
        return 0.5
    if not row.get("name"):
        return 0.5
    if row.get("price") is None:
        return 0.3
    return 1.0


def _ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _render_pages(pdf_path: str, media_root: str, job_id: int) -> None:
    import fitz

    output_dir = Path(media_root) / "import_review" / f"job_{job_id}"
    _ensure_dir(output_dir)

    doc = fitz.open(pdf_path)
    try:
        scale = 150 / 72
        matrix = fitz.Matrix(scale, scale)
        for page_index, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pixmap.save(str(output_dir / f"page_{page_index:03d}.jpg"))
    finally:
        doc.close()


def _get_or_create_id(cur, table: str, name: str) -> int:
    cur.execute(f"SELECT id FROM {table} WHERE LOWER(name) = LOWER(%s)", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(f"INSERT INTO {table} (name) VALUES (%s) RETURNING id", (name,))
    return cur.fetchone()[0]


def _get_cost_price_type_id(cur) -> int:
    cur.execute("SELECT id FROM price_types WHERE code = 'COST'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("price_types has no row with code='COST'")
    return row[0]


def _insert_product(cur, row: dict, brand_id: int, category_id: int) -> str:
    product_id = str(uuid.uuid4())
    now = datetime.utcnow()
    cur.execute(
        """
        INSERT INTO products
            (id, name, item_number, description, shot_count, brand_id, category_id,
             is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s)
        """,
        (
            product_id,
            row["name"],
            row["item_code"],
            row.get("description"),
            row.get("shot_count"),
            brand_id,
            category_id,
            now,
            now,
        ),
    )
    return product_id


def _insert_price(cur, product_id: str, price_type_id: int, amount: float) -> None:
    now = datetime.utcnow()
    cur.execute(
        """
        INSERT INTO product_prices
            (product_id, price_type_id, amount, is_active, effective_from)
        VALUES (%s, %s, %s, true, %s)
        """,
        (product_id, price_type_id, amount, now),
    )


def _insert_price_history(cur, product_id: str, price_type_id: int, amount: float) -> None:
    now = datetime.utcnow()
    cur.execute(
        """
        INSERT INTO price_history
            (product_id, price_type_id, old_amount, new_amount, reason, changed_at)
        VALUES (%s, %s, NULL, %s, %s, %s)
        """,
        (product_id, price_type_id, amount, "Initial import from PDF catalog", now),
    )


@celery_app.task(name="catalog_import.parse_pdf", bind=True, max_retries=3)
def parse_catalog_pdf(self, job_id: int, pdf_path: str, media_root: str):
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM import_jobs WHERE id = %s", (job_id,))
            if not cur.fetchone():
                raise RuntimeError(f"ImportJob {job_id} not found")
            cur.execute("UPDATE import_jobs SET status = 'parsing' WHERE id = %s", (job_id,))
        conn.commit()

        _render_pages(pdf_path, media_root, job_id)
        parsed_rows, _warnings = parse_pdf(pdf_path)

        output_rows = []
        for page_num, row in parsed_rows:
            name = row.get("name") or row.get("raw_name")
            description = row.get("description") or " ".join(row.get("desc_lines") or []).strip()
            confidence = _confidence_from_row(row)
            raw_data = {
                "name": name,
                "item_code": row.get("item_code"),
                "brand": row.get("brand"),
                "price": row.get("price"),
                "shot_count": row.get("shot_count"),
                "description": description,
                "category": row.get("category"),
                "packing": row.get("packing"),
                "page": page_num,
                "page_image_path": f"import_review/job_{job_id}/page_{page_num:03d}.jpg",
                "confidence": confidence,
            }
            output_rows.append((raw_data, "approved" if confidence == 1.0 else "pending"))

        with conn.cursor() as cur:
            for idx, (raw_data, review_status) in enumerate(output_rows):
                cur.execute(
                    """
                    INSERT INTO import_rows
                        (job_id, row_index, raw_data, review_status, match_confidence)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (job_id, idx, Jsonb(raw_data), review_status, raw_data["confidence"]),
                )
            cur.execute("UPDATE import_jobs SET status = 'review' WHERE id = %s", (job_id,))
        conn.commit()

        commit_approved_rows.delay(job_id)
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE import_jobs SET status = 'failed', error_message = %s WHERE id = %s",
                (str(exc), job_id),
            )
        conn.commit()
        raise self.retry(exc=exc, countdown=30)
    finally:
        conn.close()


@celery_app.task(name="catalog_import.commit_approved_rows")
def commit_approved_rows(job_id: int):
    from app.models.import_job import ImportJob
    from app.worker.tasks.video_search import find_product_videos

    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        search_jobs: list[tuple[str, str, str | None]] = []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, raw_data
                FROM import_rows
                WHERE job_id = %s
                  AND review_status = 'approved'
                  AND matched_product_id IS NULL
                ORDER BY row_index
                """,
                (job_id,),
            )
            rows = cur.fetchall()
            price_type_id = _get_cost_price_type_id(cur)

            for row_id, raw_data in rows:
                row = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                brand_name = row.get("brand") or "Unknown"
                category_name = row.get("category") or "Uncategorized"
                item_code = row.get("item_code")
                name = row.get("name") or item_code or "Imported Product"
                price = row.get("price")

                brand_id = _get_or_create_id(cur, "product_brands", brand_name)
                category_id = _get_or_create_id(cur, "product_categories", category_name)
                product_id = _insert_product(cur, row | {"name": name}, brand_id, category_id)
                if price not in (None, ""):
                    amount = float(price)
                    _insert_price(cur, product_id, price_type_id, amount)
                    _insert_price_history(cur, product_id, price_type_id, amount)
                cur.execute(
                    "UPDATE import_rows SET matched_product_id = %s WHERE id = %s",
                    (product_id, row_id),
                )
                search_jobs.append((product_id, name, item_code))

            cur.execute(
                "UPDATE import_jobs SET status = 'done', completed_at = %s WHERE id = %s",
                (datetime.utcnow(), job_id),
            )
        conn.commit()
        for args in search_jobs:
            find_product_videos.delay(*args)
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE import_jobs SET status = 'failed', error_message = %s WHERE id = %s",
                (str(exc), job_id),
            )
        conn.commit()
        raise
    finally:
        conn.close()
