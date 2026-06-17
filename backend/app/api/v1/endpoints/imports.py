from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.import_job import ImportJob, ImportRow
from app.models.pricing import PriceHistory, PriceType, ProductPrice
from app.models.product import Product, ProductBrand, ProductCategory
from app.worker.tasks.catalog_import import commit_approved_rows, parse_catalog_pdf
from app.worker.tasks.issuu_import import scrape_issuu_catalog
from app.worker.tasks.video_search import find_product_videos

router = APIRouter()


class IssuuImportRequest(BaseModel):
    url: str
    slug: str | None = None
    year: str | None = None


class ImportRowPatch(BaseModel):
    name: str | None = None
    item_code: str | None = None
    brand: str | None = None
    price: float | None = None
    shot_count: int | None = None
    description: str | None = None
    category: str | None = None
    packing: str | None = None
    review_status: str | None = None


def _media_root() -> str:
    return os.getenv("MEDIA_ROOT", "/app/media")


def _safe_filename(filename: str) -> str:
    return os.path.basename(filename or "import.pdf")


def _ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _serialize_row(row: ImportRow) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "row_index": row.row_index,
        "raw_data": row.raw_data,
        "matched_product_id": row.matched_product_id,
        "match_confidence": row.match_confidence,
        "match_method": row.match_method,
        "review_status": row.review_status,
        "reviewed_at": row.reviewed_at,
        "notes": row.notes,
    }


def _get_or_create_brand(db: Session, name: str | None) -> ProductBrand:
    brand_name = (name or "Unknown").strip() or "Unknown"
    brand = (
        db.query(ProductBrand)
        .filter(func.lower(ProductBrand.name) == brand_name.lower())
        .first()
    )
    if brand:
        return brand
    brand = ProductBrand(name=brand_name)
    db.add(brand)
    db.flush()
    return brand


def _get_or_create_category(db: Session, name: str | None) -> ProductCategory:
    category_name = (name or "Uncategorized").strip() or "Uncategorized"
    category = (
        db.query(ProductCategory)
        .filter(func.lower(ProductCategory.name) == category_name.lower())
        .first()
    )
    if category:
        return category
    category = ProductCategory(name=category_name)
    db.add(category)
    db.flush()
    return category


def _get_cost_price_type(db: Session) -> PriceType:
    price_type = db.query(PriceType).filter(PriceType.code == "COST").first()
    if not price_type:
        raise HTTPException(status_code=500, detail="Missing COST price type")
    return price_type


def _insert_product_from_row(db: Session, raw_data: dict) -> Product:
    brand = _get_or_create_brand(db, raw_data.get("brand"))
    category = _get_or_create_category(db, raw_data.get("category"))
    product = Product(
        name=raw_data.get("name") or raw_data.get("item_code") or "Imported Product",
        item_number=raw_data.get("item_code"),
        packing=raw_data.get("packing"),
        description=raw_data.get("description"),
        image_path=raw_data.get("image_path"),
        brand_id=brand.id,
        category_id=category.id,
        shot_count=raw_data.get("shot_count"),
    )
    db.add(product)
    db.flush()

    price = raw_data.get("price")
    if price not in (None, ""):
        amount = float(price)
        cost_type = _get_cost_price_type(db)
        now = datetime.utcnow()
        db.add(
            ProductPrice(
                product_id=product.id,
                price_type_id=cost_type.id,
                amount=amount,
                is_active=True,
                effective_from=now,
            )
        )
        db.add(
            PriceHistory(
                product_id=product.id,
                price_type_id=cost_type.id,
                old_amount=None,
                new_amount=amount,
                reason="Initial import from PDF catalog",
                changed_at=now,
            )
        )

    return product


@router.get("/")
def list_import_jobs(db: Session = Depends(get_db)):
    jobs = db.query(ImportJob).order_by(ImportJob.created_at.desc()).limit(100).all()
    return [
        {
            "job_id": job.id,
            "status": job.status,
            "document_type": job.document_type,
            "file_name": job.file_name,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message,
            "row_counts": None,
        }
        for job in jobs
    ]


@router.post("/issuu")
def start_issuu_import(payload: IssuuImportRequest, db: Session = Depends(get_db)):
    import re as _re
    url = payload.url.strip()
    slug = (payload.slug or "").strip() or "catalog"
    year = (payload.year or "").strip() or str(__import__("datetime").date.today().year)

    # Extract CDN ID from Issuu URL or accept raw CDN ID
    cdn_id: str | None = None
    doc_slug: str | None = None
    issuu_match = _re.search(r"issuu\.com/([^/]+)/docs/([^/?#]+)", url)
    if issuu_match:
        doc_slug = issuu_match.group(2)
    elif _re.match(r"^\d{12}-[a-f0-9]{32}$", url):
        cdn_id = url
    else:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(status_code=422, detail="Provide a full Issuu URL or a raw CDN ID (format: 260506140512-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)")

    file_name = f"issuu_{slug}_{year}.scrape"
    job = ImportJob(
        document_type="CATALOG",
        file_name=file_name,
        file_path="",
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    scrape_issuu_catalog.delay(job.id, cdn_id, doc_slug, slug, year)
    return {"job_id": job.id, "status": "pending", "message": "Issuu scrape queued"}


@router.post("/pdf")
def upload_pdf_import(
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    filename = _safe_filename(pdf.filename or "import.pdf")
    media_root = _media_root()
    import_dir = Path(media_root) / "imports"
    _ensure_dir(import_dir)
    file_path = import_dir / filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)

    job = ImportJob(
        document_type="PRICE_LIST",
        file_name=filename,
        file_path=str(file_path),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    parse_catalog_pdf.delay(job.id, str(file_path), media_root)
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}")
def get_import_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")

    counts = (
        db.query(ImportRow.review_status, func.count(ImportRow.id))
        .filter(ImportRow.job_id == job_id)
        .group_by(ImportRow.review_status)
        .all()
    )
    row_counts = {status: count for status, count in counts}
    row_counts["total"] = sum(row_counts.values())

    return {
        "job_id": job.id,
        "status": job.status,
        "document_type": job.document_type,
        "file_name": job.file_name,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "row_counts": row_counts,
    }


@router.get("/{job_id}/rows")
def list_import_rows(
    job_id: int,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(ImportRow).filter(ImportRow.job_id == job_id)
    if status:
        query = query.filter(ImportRow.review_status == status)

    total = query.count()
    rows = (
        query.order_by(ImportRow.row_index)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": [_serialize_row(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
    }


@router.patch("/{job_id}/rows/{row_id}")
def update_import_row(
    job_id: int,
    row_id: int,
    payload: ImportRowPatch,
    db: Session = Depends(get_db),
):
    row = (
        db.query(ImportRow)
        .filter(ImportRow.job_id == job_id, ImportRow.id == row_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Import row not found")

    update_data = payload.model_dump(exclude_unset=True)
    review_status = update_data.pop("review_status", None)

    raw_data = dict(row.raw_data or {})
    raw_data.update(update_data)
    row.raw_data = raw_data

    search_args: tuple[str, str, str | None] | None = None
    if review_status:
        row.review_status = review_status

    row.reviewed_at = datetime.utcnow()

    if row.review_status == "approved" and not row.matched_product_id:
        product = _insert_product_from_row(db, raw_data)
        row.matched_product_id = product.id
        row.match_confidence = 1.0
        search_args = (product.id, product.name, product.item_number)

    db.commit()
    db.refresh(row)
    if search_args:
        find_product_videos.delay(*search_args)
    return _serialize_row(row)


@router.post("/{job_id}/commit")
def commit_import_rows(job_id: int, db: Session = Depends(get_db)):
    count = (
        db.query(ImportRow)
        .filter(
            ImportRow.job_id == job_id,
            ImportRow.review_status == "approved",
            ImportRow.matched_product_id.is_(None),
        )
        .count()
    )
    commit_approved_rows.delay(job_id)
    return {"job_id": job_id, "queued": count}
