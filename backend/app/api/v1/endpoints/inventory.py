from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.media import ProductVideo
from app.models.product import Product, ProductBarcode
from app.models.supplier import Supplier, SupplierProduct

router = APIRouter()


class InventoryScanRequest(BaseModel):
    barcode: str = Field(min_length=1)


class InventoryScanConfirmRequest(BaseModel):
    product_id: str = Field(min_length=1)


def _video_pi_url() -> str | None:
    value = os.environ.get("VIDEO_PI_URL", "").strip()
    return value.rstrip("/") if value else None


def _normalize_video_list(payload: object) -> list[str]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, str) and item.strip()]

    if isinstance(payload, dict):
        for key in ("videos", "files", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, str) and item.strip()]

    return []


def _serialize_product(product: Product, supplier_name: str | None, video_matches: list[str]) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "image_url": f"/media/{product.image_path}" if product.image_path else None,
        "brand": product.brand.name if product.brand else None,
        "supplier": supplier_name,
        "category": product.category.name if product.category else None,
        "in_store": product.in_store,
        "needs_data_review": product.needs_data_review,
        "video_matches": video_matches,
    }


def _get_product_by_barcode(db: Session, barcode: str) -> Product | None:
    from app.api.v1.endpoints._barcode import resolve_product
    return resolve_product(db, barcode)


def _get_supplier_name(db: Session, product_id: str) -> str | None:
    stmt = (
        select(Supplier.name)
        .join(SupplierProduct, SupplierProduct.supplier_id == Supplier.id)
        .where(SupplierProduct.product_id == product_id)
        .order_by(SupplierProduct.id.asc())
    )
    return db.execute(stmt).scalars().first()


def _get_product_video_filenames(db: Session, product_id: str) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT video_filename, file_path, original_filename
            FROM product_videos
            WHERE product_id = :product_id
            ORDER BY created_at DESC, uploaded_at DESC, id DESC
            """
        ),
        {"product_id": product_id},
    ).all()

    filenames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        candidates = [row.video_filename, row.original_filename, row.file_path]
        normalized = next((candidate for candidate in (_normalize_filename(value) for value in candidates) if candidate), None)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        filenames.append(normalized)
    return filenames


def _normalize_filename(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    return Path(candidate.replace("\\", "/")).name or candidate


def _fetch_remote_videos() -> list[str]:
    video_pi_url = _video_pi_url()
    if not video_pi_url:
        return []

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{video_pi_url}/videos")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []

    return _normalize_video_list(payload)


def _name_to_search_key(name: str) -> str:
    """Normalize a product name or filename for fuzzy matching."""
    import re
    # Strip file extension, leading codes like "WC ", "1-", "#300 ", etc.
    key = re.sub(r"\.[a-z0-9]{2,4}$", "", name, flags=re.IGNORECASE)
    key = re.sub(r"^[#\d\-\s]+", "", key)           # leading numbers/symbols
    key = re.sub(r"^(WC|RR|CE|BC)\s+", "", key, flags=re.IGNORECASE)  # supplier prefix
    key = re.sub(r"[^a-z0-9 ]", " ", key.lower())   # punctuation → space
    key = re.sub(r"\s+", " ", key).strip()
    return key


def _find_video_match(
    product_item_number: str | None,
    product_name: str | None,
    remote_videos: list[str],
) -> str | None:
    # Try item_number substring match first (fast, exact)
    if product_item_number:
        needle = product_item_number.strip().lower()
        for filename in remote_videos:
            if needle in filename.lower():
                return filename

    # Fall back to name-based match
    if not product_name or product_name.lower().startswith("item "):
        return None

    name_key = _name_to_search_key(product_name)
    if len(name_key) < 3:
        return None

    for filename in remote_videos:
        if name_key in _name_to_search_key(filename):
            return filename

    # Partial: all words in name appear in filename
    words = [w for w in name_key.split() if len(w) > 2]
    if words:
        for filename in remote_videos:
            file_key = _name_to_search_key(filename)
            if all(w in file_key for w in words):
                return filename

    return None


def _insert_video_pair(db: Session, product_id: str, video_filename: str) -> None:
    db.execute(
        text(
            """
            INSERT INTO product_videos (
                product_id,
                file_path,
                source,
                url,
                youtube_id,
                title,
                thumbnail_url,
                search_query,
                confirmed,
                download_status,
                original_filename,
                duration_seconds,
                is_primary,
                uploaded_at,
                video_filename,
                created_at
            )
            VALUES (
                :product_id,
                :file_path,
                'INVENTORY',
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                FALSE,
                'paired',
                :original_filename,
                NULL,
                FALSE,
                now(),
                :video_filename,
                now()
            )
            ON CONFLICT (product_id, video_filename) DO NOTHING
            """
        ),
        {
            "product_id": product_id,
            "file_path": video_filename,
            "original_filename": video_filename,
            "video_filename": video_filename,
        },
    )


def _pairing_exists(db: Session, product_id: str, video_filename: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM product_videos
            WHERE product_id = :product_id
              AND (
                lower(coalesce(video_filename, '')) = :filename
                OR lower(coalesce(original_filename, '')) = :filename
                OR lower(coalesce(file_path, '')) LIKE :filename_like
              )
            LIMIT 1
            """
        ),
        {
            "product_id": product_id,
            "filename": video_filename.lower(),
            "filename_like": f"%{video_filename.lower()}%",
        },
    ).first()
    return row is not None


def _mark_in_store_and_pair_video(db: Session, product: Product) -> dict | None:
    """Marks the product in_store and attempts a video pairing. Returns the video_match dict (or None)."""
    product.in_store = True

    remote_videos = _fetch_remote_videos()
    video_match_filename = _find_video_match(product.item_number, product.name, remote_videos)
    if video_match_filename and not _pairing_exists(db, product.id, video_match_filename):
        _insert_video_pair(db, product.id, video_match_filename)

    db.commit()
    return {"filename": video_match_filename} if video_match_filename else None


@router.post("/scan")
def scan_inventory(payload: InventoryScanRequest, db: Session = Depends(get_db)):
    barcode = payload.barcode.strip()
    product = _get_product_by_barcode(db, barcode)
    if not product:
        return {"found": False, "barcode": barcode}

    supplier_name = _get_supplier_name(db, product.id)

    if not product.in_store:
        # Catalog match found, but not yet confirmed as physically in the store —
        # ask the operator to confirm before marking in_store / pairing video.
        return {
            "found": True,
            "needs_confirmation": True,
            "barcode": barcode,
            "product": _serialize_product(product, supplier_name, video_matches=[]),
            "video_match": None,
            "newly_marked": False,
        }

    video_matches = _get_product_video_filenames(db, product.id)
    # Already in store — re-affirm and opportunistically (re)pair video, but no confirmation needed.
    video_match = _mark_in_store_and_pair_video(db, product)

    return {
        "found": True,
        "needs_confirmation": False,
        "barcode": barcode,
        "product": _serialize_product(product, supplier_name, video_matches),
        "video_match": video_match,
        "newly_marked": False,
    }


@router.post("/scan/confirm")
def confirm_scan(payload: InventoryScanConfirmRequest, db: Session = Depends(get_db)):
    """Operator confirmed 'yes, this is the correct product' on a needs_confirmation scan."""
    product = db.execute(select(Product).where(Product.id == payload.product_id)).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    newly_marked = not product.in_store
    video_match = _mark_in_store_and_pair_video(db, product)

    supplier_name = _get_supplier_name(db, product.id)
    video_matches = _get_product_video_filenames(db, product.id)

    return {
        "found": True,
        "needs_confirmation": False,
        "barcode": None,
        "product": _serialize_product(product, supplier_name, video_matches),
        "video_match": video_match,
        "newly_marked": newly_marked,
    }


@router.get("/summary")
def inventory_summary(db: Session = Depends(get_db)):
    total_products = db.execute(select(func.count(Product.id)).where(Product.is_active.is_(True))).scalar_one()
    in_store_count = db.execute(
        select(func.count(Product.id)).where(Product.is_active.is_(True), Product.in_store.is_(True))
    ).scalar_one()
    in_store_with_video = db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True),
            Product.in_store.is_(True),
            exists(select(1).select_from(ProductVideo).where(ProductVideo.product_id == Product.id)),
        )
    ).scalar_one()
    needs_review_count = db.execute(
        select(func.count(Product.id)).where(Product.is_active.is_(True), Product.needs_data_review.is_(True))
    ).scalar_one()

    return {
        "total_products": int(total_products or 0),
        "in_store_count": int(in_store_count or 0),
        "in_store_with_video": int(in_store_with_video or 0),
        "in_store_without_video": int((in_store_count or 0) - (in_store_with_video or 0)),
        "needs_review_count": int(needs_review_count or 0),
    }


@router.post("/pair-videos")
def bulk_pair_videos(db: Session = Depends(get_db)):
    """Match every product to a video by name and insert pairings. Returns counts."""
    remote_videos = _fetch_remote_videos()
    if not remote_videos:
        return {"status": "no_videos", "paired": 0, "skipped": 0}

    products = db.execute(
        select(Product)
        .options(joinedload(Product.brand))
        .where(Product.is_active.is_(True))
    ).scalars().all()

    paired = 0
    skipped = 0
    for product in products:
        match = _find_video_match(product.item_number, product.name, remote_videos)
        if not match:
            skipped += 1
            continue
        if _pairing_exists(db, product.id, match):
            skipped += 1
            continue
        _insert_video_pair(db, product.id, match)
        paired += 1

    db.commit()
    return {"status": "ok", "paired": paired, "skipped": skipped}


@router.get("/products")
def inventory_products(
    in_store: bool | None = None,
    needs_data_review: bool | None = None,
    sort: str = "name",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * size

    stmt = (
        select(Product)
        .options(joinedload(Product.brand), joinedload(Product.category))
        .where(Product.is_active.is_(True))
    )
    if sort == "recent":
        stmt = stmt.order_by(Product.updated_at.desc(), Product.id.asc())
    else:
        stmt = stmt.order_by(Product.name.asc(), Product.id.asc())
    if in_store is not None:
        stmt = stmt.where(Product.in_store.is_(in_store))
    if needs_data_review is not None:
        stmt = stmt.where(Product.needs_data_review.is_(needs_data_review))

    products = db.execute(stmt.offset(offset).limit(size)).scalars().all()
    items = []
    for product in products:
        items.append(
            {
                "id": product.id,
                "name": product.name,
                "item_number": product.item_number,
                "image_url": f"/media/{product.image_path}" if product.image_path else None,
                "brand": product.brand.name if product.brand else None,
                "supplier": _get_supplier_name(db, product.id),
                "category": product.category.name if product.category else None,
                "in_store": product.in_store,
                "needs_data_review": product.needs_data_review,
                "video_matches": _get_product_video_filenames(db, product.id),
            }
        )

    return items


@router.delete("/product/{product_id}/in_store")
def clear_inventory_status(product_id: str, db: Session = Depends(get_db)):
    product = db.execute(select(Product).where(Product.id == product_id)).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product.in_store = False
    db.commit()
    return {"ok": True, "product_id": product.id, "in_store": product.in_store}
