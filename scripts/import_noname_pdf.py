"""
import_noname_pdf.py — Parse NoName2026.pdf and import products into FIMS PostgreSQL DB.
"""

import argparse
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PDF = r"C:\Users\batma\Fireworks Store\NoName2026.pdf"
DEFAULT_DB_URL = "postgresql://fims:fims@localhost:5432/fims"

ITEM_CODE_RE = re.compile(r"^(?=[A-Z0-9]{3,12}$)(?=[^A-Z]*[A-Z])(?=[^0-9]*[0-9])[A-Z0-9]+$")
PACKING_RE = re.compile(r"^'\S+$|^\d+/\d+$")
PRICE_RE = re.compile(r"^\d+\.\d+$")
SHOT_RE = re.compile(r"(\d+)\s*[Ss]hots?")


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
    # ALL CAPS, contains spaces, doesn't match item code
    if stripped != stripped.upper():
        return False
    if not re.search(r"\s", stripped):
        return False
    # Must contain letters
    if not re.search(r"[A-Z]", stripped):
        return False
    return True


def parse_shot_count(description: str):
    m = SHOT_RE.search(description)
    if m:
        return int(m.group(1))
    return None


def extract_blocks_from_page(page_text: str):
    """
    Given raw page text, return:
      - category: str or None (last ALL-CAPS spaced header before first item code)
      - products: list of parsed product dicts
    """
    lines = [l.strip() for l in page_text.split("\n")]

    # Find item code line positions
    item_code_positions = [i for i, l in enumerate(lines) if is_item_code(l)]
    if not item_code_positions:
        return None, []

    # Category: scan lines before the first item code, take last all-caps header
    category = None
    for i in range(item_code_positions[0]):
        l = lines[i]
        if l and is_category_header(l):
            category = l

    products = []

    for idx, code_pos in enumerate(item_code_positions):
        # ── Name: scan backwards from item code, stop at blank / price / packing /
        #    item code / lowercase text (description prose) / after 2 lines max
        name_lines = []
        i = code_pos - 1
        while i >= 0 and len(name_lines) < 2:
            l = lines[i]
            if not l:
                break
            if is_item_code(l) or is_price(l) or is_packing(l):
                break
            # Stop if line contains lowercase — that's description prose, not a product name
            if any(c.islower() for c in l):
                break
            name_lines.insert(0, l)
            i -= 1

        name = " ".join(name_lines).strip()
        item_code = lines[code_pos]

        # ── After item code: brand → [packing] → price → description
        # Stop before the next product's item code
        next_code = item_code_positions[idx + 1] if idx + 1 < len(item_code_positions) else len(lines)

        brand = None
        packing = None
        price = None
        desc_lines = []
        state = "brand"

        for j in range(code_pos + 1, next_code):
            l = lines[j]
            if not l:
                continue
            # Stop collecting description if we've entered the next product's name zone
            # (lines directly before next item code that aren't special are the next name)
            if state == "desc" and j >= next_code - 3:
                # Peek: if remaining lines look like a name block, stop
                break
            if state == "brand":
                brand = l
                state = "packing_or_price"
            elif state == "packing_or_price":
                if is_packing(l):
                    packing = l
                    state = "price"
                elif is_price(l):
                    price = float(l)
                    state = "desc"
            elif state == "price":
                if is_price(l):
                    price = float(l)
                    state = "desc"
            elif state == "desc":
                # If this line looks like a category header right before next product, stop
                if is_category_header(l):
                    category = l
                    break
                desc_lines.append(l)

        description = " ".join(desc_lines).strip()
        shot_count = parse_shot_count(description)

        if name and item_code and brand and price is not None:
            products.append({
                "name": name,
                "item_code": item_code,
                "brand": brand,
                "packing": packing,
                "price": price,
                "description": description,
                "shot_count": shot_count,
                "category": category,
            })
        else:
            products.append({
                "__invalid__": True,
                "raw_name": name,
                "item_code": item_code,
                "brand": brand,
                "price": price,
                "desc_lines": desc_lines,
            })

    return category, products


def parse_pdf(pdf_path: str):
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    all_products = []
    warnings = []
    current_category = None

    for page_num, page in enumerate(doc, start=1):
        # Skip cover and TOC
        if page_num <= 2:
            continue

        text = page.get_text("text")
        if not text.strip():
            continue

        cat, products = extract_blocks_from_page(text)
        if cat:
            current_category = cat

        for p in products:
            if p.get("__invalid__"):
                warnings.append((page_num, p))
                continue
            # Fill in running category if product has none
            if not p.get("category"):
                p["category"] = current_category
            else:
                current_category = p["category"]
            all_products.append((page_num, p))

    doc.close()
    return all_products, warnings


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_or_create_brand(cur, name: str) -> int:
    cur.execute(
        "SELECT id FROM product_brands WHERE LOWER(name) = LOWER(%s)", (name,)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO product_brands (name) VALUES (%s) RETURNING id", (name,)
    )
    return cur.fetchone()[0]


def get_or_create_category(cur, name: str) -> int:
    if not name:
        name = "Uncategorized"
    cur.execute(
        "SELECT id FROM product_categories WHERE LOWER(name) = LOWER(%s)", (name,)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO product_categories (name) VALUES (%s) RETURNING id", (name,)
    )
    return cur.fetchone()[0]


def get_cost_price_type_id(cur) -> int:
    cur.execute("SELECT id FROM price_types WHERE code = 'COST'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("price_types has no row with code='COST'")
    return row[0]


def product_exists(cur, item_number: str) -> bool:
    cur.execute(
        "SELECT 1 FROM products WHERE item_number = %s", (item_number,)
    )
    return cur.fetchone() is not None


def insert_product(cur, product: dict, brand_id: int, category_id: int) -> str:
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO products
            (id, name, item_number, description, shot_count, brand_id, category_id,
             is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s)
        """,
        (
            pid,
            product["name"],
            product["item_code"],
            product["description"],
            product["shot_count"],
            brand_id,
            category_id,
            now,
            now,
        ),
    )
    return pid


def insert_price(cur, product_id: str, price_type_id: int, amount: float):
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO product_prices
            (product_id, price_type_id, amount, is_active, effective_from)
        VALUES (%s, %s, %s, true, %s)
        """,
        (product_id, price_type_id, amount, now),
    )


def insert_price_history(cur, product_id: str, price_type_id: int, amount: float):
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO price_history
            (product_id, price_type_id, old_amount, new_amount, reason, changed_at)
        VALUES (%s, %s, NULL, %s, %s, %s)
        """,
        (product_id, price_type_id, amount, "Initial import from NoName2026.pdf", now),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import NoName2026.pdf into FIMS DB")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print, no DB writes")
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="Path to PDF file")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL connection URL")
    args = parser.parse_args()

    print(f"Parsing: {args.pdf}")
    all_products, warnings = parse_pdf(args.pdf)

    inserted = 0
    skipped = 0
    warn_count = len(warnings)

    for page_num, w in warnings:
        snippet = str(w)[:120]
        print(f"WARN      page {page_num} — could not parse block: {snippet}")

    if args.dry_run:
        for page_num, p in all_products:
            shots = f"{p['shot_count']}shots" if p["shot_count"] else "?shots"
            print(
                f"DRY-RUN   {p['item_code']:<12} \"{p['name']}\"  ({p['brand']})  "
                f"${p['price']:.4f}  {shots}  [{p.get('category', 'N/A')}]"
            )
        print(f"\nDry run complete. Found: {len(all_products)}  Warnings: {warn_count}")
        return

    import psycopg

    with psycopg.connect(args.db_url, autocommit=False) as conn:
        cost_price_type_id = None
        with conn.cursor() as cur:
            cost_price_type_id = get_cost_price_type_id(cur)

        for page_num, p in all_products:
            item_code = p["item_code"]
            name = p["name"]
            brand_name = p["brand"]
            price = p["price"]
            shot_count = p["shot_count"]
            category_name = p.get("category") or "Uncategorized"

            try:
                with conn.cursor() as cur:
                    if product_exists(cur, item_code):
                        shots = f"{shot_count}shots" if shot_count else "?shots"
                        print(f"SKIPPED   {item_code:<12} \"{name}\"  — already exists")
                        skipped += 1
                        continue

                    brand_id = get_or_create_brand(cur, brand_name)
                    category_id = get_or_create_category(cur, category_name)
                    product_id = insert_product(cur, p, brand_id, category_id)
                    insert_price(cur, product_id, cost_price_type_id, price)
                    insert_price_history(cur, product_id, cost_price_type_id, price)

                conn.commit()
                shots = f"{shot_count}shots" if shot_count else "?shots"
                print(
                    f"INSERTED  {item_code:<12} \"{name}\"  ({brand_name})  "
                    f"${price:.4f}  {shots}"
                )
                inserted += 1

            except Exception as exc:
                conn.rollback()
                print(f"WARN      page {page_num} — DB error for {item_code}: {exc}")
                warn_count += 1

    print(f"\nInserted: {inserted}  Skipped: {skipped}  Warnings: {warn_count}")


if __name__ == "__main__":
    main()
