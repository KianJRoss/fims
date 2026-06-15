from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.media import ProductVideo
from app.models.product import Product, ProductBarcode

router = APIRouter()


class ProductVideoPatch(BaseModel):
    confirmed: bool | None = None
    is_primary: bool | None = None


@router.get("/")
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    brand_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Product).filter(Product.is_active == True)
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.item_number.ilike(f"%{q}%")
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if brand_id:
        query = query.filter(Product.brand_id == brand_id)
    return query.offset(skip).limit(limit).all()


@router.get("/lookup/barcode/{barcode}")
def lookup_by_barcode(barcode: str, db: Session = Depends(get_db)):
    """Returns all products mapped to this barcode (may be more than one)."""
    rows = db.query(ProductBarcode).filter(ProductBarcode.barcode == barcode).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Barcode not found")
    product_ids = [r.product_id for r in rows]
    return db.query(Product).filter(Product.id.in_(product_ids)).all()


def _serialize_video(video: ProductVideo) -> dict:
    return {
        "id": video.id,
        "product_id": video.product_id,
        "file_path": video.file_path,
        "source": video.source,
        "url": video.url,
        "youtube_id": video.youtube_id,
        "title": video.title,
        "thumbnail_url": video.thumbnail_url,
        "search_query": video.search_query,
        "confirmed": video.confirmed,
        "original_filename": video.original_filename,
        "duration_seconds": video.duration_seconds,
        "is_primary": video.is_primary,
        "uploaded_at": video.uploaded_at,
    }


@router.get("/{product_id}/videos")
def list_product_videos(product_id: str, db: Session = Depends(get_db)):
    videos = (
        db.query(ProductVideo)
        .filter(ProductVideo.product_id == product_id)
        .order_by(ProductVideo.confirmed.desc(), ProductVideo.is_primary.desc())
        .all()
    )
    return [_serialize_video(video) for video in videos]


@router.patch("/{product_id}/videos/{video_id}")
def update_product_video(
    product_id: str,
    video_id: int,
    payload: ProductVideoPatch,
    db: Session = Depends(get_db),
):
    video = (
        db.query(ProductVideo)
        .filter(ProductVideo.product_id == product_id, ProductVideo.id == video_id)
        .first()
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(video, key, value)
    db.commit()
    db.refresh(video)
    return _serialize_video(video)


@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
