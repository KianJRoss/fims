"""
Pyromaniacs Wholesale catalog importer (pyro-stock.replit.app).

The source is already clean JSON (captured via the authenticated browser session
into scripts/catalogs/pyromaniacs/2026/products.json), so unlike jakes/noname
there is no PDF/OCR parsing -- we just map fields and stage rows for human review.

Pricing: per store decision, the single price the portal exposes to us is treated
as OUR COST for the product. The shared commit pipeline maps raw_data["price"] ->
the COST price type, so we put the catalog price there. (The portal labels it
"suggestedRetailPrice", but its real wholesale cost/case-cost is hidden from our
client role, so the store uses this figure as the cost basis.)

Curated videos: 282 of these products already carry a hand-picked YouTube URL.
We preserve it as raw_data["video_url"]; the standard commit path still fires the
yt-dlp *search* per product. A post-commit linker can attach the known URL
directly to product_videos and skip the search -- not done here (staging only).

Usage:
    python scripts/importers/pyromaniacs.py --dry-run              # preview JSON, no DB, no downloads
    python scripts/importers/pyromaniacs.py --download-images      # fetch product images to media/
    python scripts/importers/pyromaniacs.py                        # stage rows into import_jobs/import_rows
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent
CATALOG_JSON = ROOT_DIR / "scripts" / "catalogs" / "pyromaniacs" / "2026" / "products.json"
PREVIEW_JSON = ROOT_DIR / "scripts" / "catalogs" / "pyromaniacs" / "2026" / "staged_preview.json"
MEDIA_PRODUCT_DIR = ROOT_DIR / "media" / "product_images"

SUPPLIER_BRAND = "Pyromaniacs Wholesale"
SOURCE_NAME = "pyro-stock.replit.app"
SOURCE_BASE_URL = "https://pyro-stock.replit.app"

SHOT_RE = re.compile(r"(\d+)\s*shots?\b", re.IGNORECASE)
# A leading pack ratio like "18/1", "16/5", "3/4/6" at the start of the description.
PACKING_RE = re.compile(r"^\s*(\d+(?:/\d+)+)\b")


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Catalog JSON not found at {path}. Capture it from the authenticated "
            f"pyro-stock.replit.app session first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def parse_packing(description: str | None) -> str | None:
    if not description:
        return None
    match = PACKING_RE.search(description)
    return match.group(1) if match else None


def parse_shot_count(description: str | None) -> int | None:
    if not description:
        return None
    match = SHOT_RE.search(description)
    return int(match.group(1)) if match else None


def clean_video_url(value: str | None) -> str | None:
    """Source has a few junk values ('No', blanks) mixed in with real URLs."""
    if not value:
        return None
    candidate = value.strip()
    if candidate.lower().startswith(("http://", "https://")):
        return candidate
    return None


def image_basename(image_ref: str | None) -> str | None:
    """'/public-objects/products/<uuid>.webp' -> '<uuid>.webp'."""
    if not image_ref:
        return None
    return os.path.basename(image_ref.split("?", 1)[0]) or None


def confidence_for(product: dict[str, Any]) -> float:
    confidence = 1.0
    if not (product.get("name") or "").strip():
        confidence -= 0.4
    if not product.get("sku"):
        confidence -= 0.15
    if not product.get("category"):
        confidence -= 0.1
    if product.get("retail") in (None, "", "0", "0.00"):
        confidence -= 0.15
    if not product.get("img"):
        confidence -= 0.05
    return max(0.0, round(confidence, 2))


def build_row(product: dict[str, Any]) -> dict[str, Any]:
    description = (product.get("description") or "").strip() or None
    img_name = image_basename(product.get("img"))

    return {
        # --- fields the commit pipeline consumes ---
        "name": (product.get("name") or "").strip() or None,
        "item_code": (product.get("sku") or None),
        "brand": SUPPLIER_BRAND,
        "category": (product.get("category") or None),
        "description": description,
        "packing": parse_packing(description),
        "shot_count": parse_shot_count(description),
        "image_path": f"product_images/{img_name}" if img_name else None,
        # Catalog price -> COST price type on commit (store decision). See docstring.
        "price": product.get("retail"),
        # --- preserved for human review / later steps ---
        "catalog_price": product.get("retail"),
        "clearance_price": product.get("clearance"),
        "on_clearance": bool(product.get("onClearance")),
        "stock_quantity": product.get("stock"),
        "reorder_point": product.get("reorder"),
        "weight_kg": product.get("weightKg"),
        "active": bool(product.get("active", True)),
        "video_url": clean_video_url(product.get("video")),
        "image_ref": product.get("img"),
        "image_ref2": product.get("img2"),
        "image_ref3": product.get("img3"),
        "source": SOURCE_NAME,
        "source_id": product.get("id"),
        "source_category_id": product.get("categoryId"),
        "confidence": confidence_for(product),
    }


def build_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    products = catalog.get("products") or []
    rows = [build_row(product) for product in products]
    # Stable order: name then sku, so the review list reads alphabetically.
    rows.sort(key=lambda r: ((r.get("name") or "").lower(), r.get("item_code") or ""))
    return rows


def download_images(catalog: dict[str, Any]) -> tuple[int, int, list[str]]:
    """Fetch every product image (public webp, no auth) into media/product_images."""
    MEDIA_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
    refs: list[str] = []
    for product in catalog.get("products") or []:
        for key in ("img", "img2", "img3"):
            if product.get(key):
                refs.append(product[key])
    # De-dupe while preserving order.
    seen: set[str] = set()
    unique_refs = [r for r in refs if not (r in seen or seen.add(r))]

    downloaded = 0
    skipped = 0
    errors: list[str] = []
    for ref in unique_refs:
        name = image_basename(ref)
        if not name:
            continue
        dest = MEDIA_PRODUCT_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        url = ref if ref.startswith("http") else f"{SOURCE_BASE_URL}{ref}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "FIMS-importer"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
            dest.write_bytes(data)
            downloaded += 1
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{name}: {exc}")
        time.sleep(0.05)  # be polite to the Replit host
    return downloaded, skipped, errors


def write_preview(rows: list[dict[str, Any]]) -> None:
    PREVIEW_JSON.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_JSON.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def stage_rows(source_path: Path, rows: list[dict[str, Any]]) -> int:
    now = datetime.now(timezone.utc)
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO import_jobs (document_type, file_name, file_path, status, created_at)
                VALUES ('CATALOG', %s, %s, 'review', %s)
                RETURNING id
                """,
                ("pyromaniacs_2026.json", str(source_path), now),
            )
            job_id = int(cur.fetchone()[0])

            for idx, raw_data in enumerate(rows):
                cur.execute(
                    """
                    INSERT INTO import_rows
                        (job_id, row_index, raw_data, review_status, match_confidence)
                    VALUES (%s, %s, %s, 'pending', %s)
                    """,
                    (job_id, idx, Jsonb(raw_data), raw_data["confidence"]),
                )
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


YOUTUBE_ID_RE = re.compile(r"(?:youtu\.be/|/shorts/|[?&]v=|/embed/|/live/)([A-Za-z0-9_-]{6,})")


def youtube_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def _get_or_create_id(cur, table: str, name: str) -> int:
    cur.execute(f"SELECT id FROM {table} WHERE lower(name) = lower(%s)", (name,))
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(f"INSERT INTO {table} (name) VALUES (%s) RETURNING id", (name,))
    return int(cur.fetchone()[0])


def commit_job(job_id: int) -> dict[str, int]:
    """Commit a staged job's rows directly into the catalog.

    Products are created with in_store=FALSE (catalog reference, not stocked), the
    catalog price is filed under COST, and any curated YouTube URL is attached as a
    confirmed primary video (so the 15-min auto-search leaves those products alone).
    Bypasses the per-product yt-dlp *search* the standard commit path would trigger.
    """
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        created = priced = videos = 0
        now = datetime.utcnow()
        with conn.cursor() as cur:
            # Realign serial sequences with existing data so inserts can't collide
            # (sequences drift out of sync after a dump/restore). Only ever moves a
            # sequence forward to MAX(id); never touches existing rows.
            for table in (
                "product_categories",
                "product_brands",
                "product_prices",
                "price_history",
                "product_videos",
            ):
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table + "), 1), "
                    "(SELECT MAX(id) FROM " + table + ") IS NOT NULL)",
                    (table,),
                )

            cur.execute("SELECT id FROM price_types WHERE code = 'COST'")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("COST price type missing")
            cost_type_id = int(row[0])

            brand_id = _get_or_create_id(cur, "product_brands", SUPPLIER_BRAND)
            category_cache: dict[str, int] = {}

            cur.execute(
                """
                SELECT id, raw_data FROM import_rows
                WHERE job_id = %s AND matched_product_id IS NULL
                ORDER BY row_index
                """,
                (job_id,),
            )
            rows = cur.fetchall()
            if not rows:
                raise RuntimeError(f"No uncommitted rows for job {job_id}")

            for row_id, raw in rows:
                data = json.loads(raw) if isinstance(raw, str) else raw

                category_id = None
                cat_name = data.get("category")
                if cat_name:
                    if cat_name not in category_cache:
                        category_cache[cat_name] = _get_or_create_id(
                            cur, "product_categories", cat_name
                        )
                    category_id = category_cache[cat_name]

                product_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO products
                        (id, name, item_number, packing, description, category_id,
                         brand_id, shot_count, image_path, is_active, in_store,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s, %s)
                    """,
                    (
                        product_id,
                        data.get("name") or data.get("item_code") or "Imported Product",
                        data.get("item_code"),
                        data.get("packing"),
                        data.get("description"),
                        category_id,
                        brand_id,
                        data.get("shot_count"),
                        data.get("image_path"),
                        bool(data.get("active", True)),
                        now,
                        now,
                    ),
                )
                created += 1

                price = data.get("price")
                if price not in (None, ""):
                    amount = float(price)
                    cur.execute(
                        """
                        INSERT INTO product_prices
                            (product_id, price_type_id, amount, is_active, effective_from)
                        VALUES (%s, %s, %s, true, %s)
                        """,
                        (product_id, cost_type_id, amount, now),
                    )
                    cur.execute(
                        """
                        INSERT INTO price_history
                            (product_id, price_type_id, old_amount, new_amount, reason, changed_at)
                        VALUES (%s, %s, NULL, %s, %s, %s)
                        """,
                        (
                            product_id,
                            cost_type_id,
                            amount,
                            "Initial import from Pyromaniacs Wholesale catalog (cost)",
                            now,
                        ),
                    )
                    priced += 1

                video_url = data.get("video_url")
                if video_url:
                    yt_id = youtube_id_from_url(video_url)
                    cur.execute(
                        """
                        INSERT INTO product_videos
                            (product_id, file_path, source, url, youtube_id, confirmed,
                             is_primary, download_status, video_filename, uploaded_at)
                        VALUES (%s, %s, 'YOUTUBE', %s, %s, true, true, 'pending', %s, %s)
                        """,
                        (product_id, "", video_url, yt_id, yt_id or "", now),
                    )
                    videos += 1

                cur.execute(
                    """
                    UPDATE import_rows
                    SET matched_product_id = %s, review_status = 'approved', reviewed_at = %s
                    WHERE id = %s
                    """,
                    (product_id, now, row_id),
                )

            cur.execute(
                "UPDATE import_jobs SET status = 'done', completed_at = %s WHERE id = %s",
                (now, job_id),
            )
        conn.commit()
        return {"products": created, "cost_prices": priced, "videos": videos}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "with_sku": sum(1 for r in rows if r["item_code"]),
        "with_image": sum(1 for r in rows if r["image_path"]),
        "with_video": sum(1 for r in rows if r["video_url"]),
        "with_price": sum(1 for r in rows if r["price"]),
        "on_clearance": sum(1 for r in rows if r["on_clearance"]),
        "active": sum(1 for r in rows if r["active"]),
    }


def load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import the Pyromaniacs Wholesale catalog.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write a preview JSON of the staged rows without touching the database.",
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="Download product images (public webp) into media/product_images/.",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Override path to the captured catalog JSON.",
    )
    parser.add_argument(
        "--commit",
        type=int,
        metavar="JOB_ID",
        default=None,
        help="Commit a staged job's rows into the catalog (in_store=FALSE, price->COST, "
        "curated videos attached). Skips staging/parsing.",
    )
    return parser.parse_args()


def main() -> int:
    args = load_args()

    if args.commit is not None:
        result = commit_job(args.commit)
        print(
            "Committed job {job}: {products} products (in_store=FALSE), "
            "{cost_prices} COST prices, {videos} curated videos.".format(
                job=args.commit, **result
            )
        )
        return 0

    source_path = Path(args.json) if args.json else CATALOG_JSON
    catalog = load_catalog(source_path)
    rows = build_rows(catalog)
    stats = summarize(rows)

    print(f"Source: {source_path}")
    print(f"Captured at: {catalog.get('capturedAt')}")
    print(
        "Rows: {total} | sku {with_sku} | img {with_image} | video {with_video} | "
        "cost {with_price} | clearance {on_clearance} | active {active}".format(**stats)
    )

    if args.download_images:
        downloaded, skipped, errors = download_images(catalog)
        print(f"Images: downloaded {downloaded}, already-present {skipped}, errors {len(errors)}")
        for err in errors[:20]:
            print(f"  ! {err}")

    if args.dry_run:
        write_preview(rows)
        print(f"Dry-run preview written to {PREVIEW_JSON} (no DB writes)")
        return 0

    job_id = stage_rows(source_path, rows)
    print(f"Created ImportJob {job_id} with {len(rows)} rows staged for review (status='review').")
    print("Review at the Documents -> Catalog Import UI, then approve/commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
