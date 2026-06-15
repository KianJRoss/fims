from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.media import ProductVideo
from app.models.product import Product, ProductBarcode, ProductBrand, ProductCategory

router = APIRouter()


class ProductVideoPatch(BaseModel):
    confirmed: bool | None = None
    is_primary: bool | None = None


class ProductInStorePatch(BaseModel):
    in_store: bool


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
        "download_status": video.download_status,
        "original_filename": video.original_filename,
        "duration_seconds": video.duration_seconds,
        "is_primary": video.is_primary,
        "uploaded_at": video.uploaded_at,
        "downloaded": bool(video.file_path and video.confirmed),
    }


def _serialize_product_detail(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "description": product.description,
        "notes": product.notes,
        "category_id": product.category_id,
        "brand_id": product.brand_id,
        "category_name": product.category.name if product.category else None,
        "brand_name": product.brand.name if product.brand else None,
        "shot_count": product.shot_count,
        "duration_seconds": product.duration_seconds,
        "effects": product.effects,
        "catalog_page": product.catalog_page,
        "is_active": product.is_active,
        "in_store": product.in_store,
        "no_video_confirmed": product.no_video_confirmed,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "barcode_count": len(product.barcodes),
        "video_count": len(product.videos),
        "barcodes": [
            {
                "id": barcode.id,
                "barcode": barcode.barcode,
                "barcode_type": barcode.barcode_type,
                "is_primary": barcode.is_primary,
                "notes": barcode.notes,
            }
            for barcode in sorted(product.barcodes, key=lambda item: (not item.is_primary, item.id))
        ],
        "videos": [_serialize_video(video) for video in sorted(product.videos, key=lambda item: item.id)],
    }


def _get_product_detail(db: Session, product_id: str) -> Product:
    product = (
        db.execute(
            select(Product)
            .options(
                joinedload(Product.brand),
                joinedload(Product.category),
                joinedload(Product.barcodes),
                joinedload(Product.videos),
            )
            .where(Product.id == product_id, Product.is_active.is_(True))
        )
        .unique()
        .scalar_one_or_none()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/")
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    category: str | None = None,
    brand_id: list[int] = Query(default=[]),
    in_store: bool | None = None,
    no_video: bool | None = None,
    sort: str = "name",
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    barcode_count = (
        select(func.count(ProductBarcode.id))
        .where(ProductBarcode.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    video_count = (
        select(func.count(ProductVideo.id))
        .where(ProductVideo.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )

    stmt = (
        select(
            Product,
            barcode_count.label("barcode_count"),
            video_count.label("video_count"),
        )
        .options(joinedload(Product.brand), joinedload(Product.category))
        .where(Product.is_active.is_(True))
    )

    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.item_number.ilike(f"%{q}%")))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if category:
        stmt = stmt.where(Product.category.has(ProductCategory.name == category))
    if brand_id:
        stmt = stmt.where(Product.brand_id.in_(brand_id))
    if in_store is not None:
        stmt = stmt.where(Product.in_store.is_(in_store))
    if no_video:
        has_confirmed_video = exists(
            select(1).select_from(ProductVideo).where(
                ProductVideo.product_id == Product.id,
                ProductVideo.confirmed.is_(True),
            )
        )
        stmt = stmt.where(Product.no_video_confirmed.is_(False), ~has_confirmed_video)

    brand_sort = select(ProductBrand.name).where(ProductBrand.id == Product.brand_id).correlate(Product).scalar_subquery()
    if sort == "brand":
        stmt = stmt.order_by(
            func.lower(func.coalesce(brand_sort, "")),
            func.lower(Product.name),
        )
    elif sort == "recent":
        stmt = stmt.order_by(Product.created_at.desc(), func.lower(Product.name))
    elif sort == "catalog":
        stmt = stmt.order_by(
            Product.catalog_page.asc().nullslast(),
            func.lower(Product.name),
        )
    else:
        stmt = stmt.order_by(func.lower(Product.name), Product.created_at.desc())

    rows = db.execute(stmt.offset(skip).limit(limit)).all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "item_number": product.item_number,
            "category_name": product.category.name if product.category else None,
            "brand_name": product.brand.name if product.brand else None,
            "barcode_count": int(barcode_count_value or 0),
            "video_count": int(video_count_value or 0),
            "in_store": product.in_store,
            "shot_count": product.shot_count,
            "catalog_page": product.catalog_page,
            "created_at": product.created_at,
        }
        for product, barcode_count_value, video_count_value in rows
    ]


@router.get("/lookup/barcode/{barcode}")
def lookup_by_barcode(barcode: str, db: Session = Depends(get_db)):
    """Returns all products mapped to this barcode (may be more than one)."""
    from app.api.v1.endpoints._barcode import resolve_product_ids
    product_ids = resolve_product_ids(db, barcode)
    if not product_ids:
        raise HTTPException(status_code=404, detail="Barcode not found")
    products = (
        db.execute(
            select(Product)
            .options(joinedload(Product.brand), joinedload(Product.category))
            .where(Product.id.in_(product_ids))
        )
        .scalars()
        .all()
    )
    product_map = {product.id: product for product in products}
    return [
        {
            "id": product.id,
            "name": product.name,
            "item_number": product.item_number,
            "description": product.description,
            "notes": product.notes,
            "category_id": product.category_id,
            "brand_id": product.brand_id,
            "category_name": product.category.name if product.category else None,
            "brand_name": product.brand.name if product.brand else None,
            "shot_count": product.shot_count,
            "duration_seconds": product.duration_seconds,
            "effects": product.effects,
            "is_active": product.is_active,
            "in_store": product.in_store,
            "no_video_confirmed": product.no_video_confirmed,
            "created_at": product.created_at,
            "updated_at": product.updated_at,
        }
        for product_id in product_ids
        if (product := product_map.get(product_id))
    ]


@router.get("/categories")
def list_product_categories(db: Session = Depends(get_db)):
    return (
        db.execute(
            select(ProductCategory.name)
            .join(Product, Product.category_id == ProductCategory.id)
            .distinct()
            .order_by(ProductCategory.name.asc())
        )
        .scalars()
        .all()
    )


@router.patch("/{product_id}/in-store")
def set_product_in_store(
    product_id: str,
    payload: ProductInStorePatch,
    db: Session = Depends(get_db),
):
    product = _get_product_detail(db, product_id)
    product.in_store = payload.in_store
    db.commit()
    return _serialize_product_detail(_get_product_detail(db, product_id))


@router.get("/{product_id}/videos")
def list_product_videos(product_id: str, db: Session = Depends(get_db)):
    videos = (
        db.query(ProductVideo)
        .filter(ProductVideo.product_id == product_id)
        .order_by(ProductVideo.confirmed.desc(), ProductVideo.is_primary.desc(), ProductVideo.uploaded_at.desc())
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
    product = _get_product_detail(db, product_id)
    return _serialize_product_detail(product)
