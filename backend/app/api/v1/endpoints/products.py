from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.media import ProductVideo
from app.models.product import Product, ProductAlias, ProductBarcode, ProductBrand, ProductCategory

router = APIRouter()


class ProductVideoPatch(BaseModel):
    confirmed: bool | None = None
    is_primary: bool | None = None


class BarcodeAddRequest(BaseModel):
    barcode: str
    is_primary: bool = True


class ProductInStorePatch(BaseModel):
    in_store: bool


class ProductAliasCreate(BaseModel):
    alias_name: str
    source: str | None = None


class ProductCreateRequest(BaseModel):
    name: str
    item_number: str | None = None
    packing: str | None = None
    description: str | None = None
    notes: str | None = None
    category_name: str | None = None
    brand_name: str | None = None
    shot_count: int | None = None
    duration_seconds: int | None = None
    effects: str | None = None
    barcode: str | None = None
    in_store: bool = False
    needs_data_review: bool = False


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    item_number: str | None = None
    packing: str | None = None
    description: str | None = None
    notes: str | None = None
    category_name: str | None = None
    brand_name: str | None = None
    shot_count: int | None = None
    duration_seconds: int | None = None
    effects: str | None = None
    needs_data_review: bool | None = None


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


def _serialize_alias(alias: ProductAlias) -> dict:
    return {
        "id": alias.id,
        "product_id": alias.product_id,
        "alias_name": alias.alias_name,
        "source": alias.source,
        "created_at": alias.created_at,
    }


def _serialize_product_detail(product: Product) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "image_url": f"/media/{product.image_path}" if product.image_path else None,
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
        "needs_data_review": product.needs_data_review,
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


def _get_or_create_category(db: Session, name: str | None) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    category = db.execute(select(ProductCategory).where(ProductCategory.name == name)).scalars().first()
    if category:
        return category.id
    category = ProductCategory(name=name)
    db.add(category)
    db.flush()
    return category.id


def _get_or_create_brand(db: Session, name: str | None) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    brand = db.execute(select(ProductBrand).where(ProductBrand.name == name)).scalars().first()
    if brand:
        return brand.id
    brand = ProductBrand(name=name)
    db.add(brand)
    db.flush()
    return brand.id


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
    video_status: str | None = None,
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
    candidate_count = (
        select(func.count(ProductVideo.id))
        .where(
            ProductVideo.product_id == Product.id,
            ProductVideo.confirmed.is_(False),
        )
        .correlate(Product)
        .scalar_subquery()
    )

    stmt = (
        select(
            Product,
            barcode_count.label("barcode_count"),
            video_count.label("video_count"),
            candidate_count.label("candidate_count"),
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
    if video_status is not None:
        has_confirmed_video = exists(
            select(1).select_from(ProductVideo).where(
                ProductVideo.product_id == Product.id,
                ProductVideo.confirmed.is_(True),
            )
        )
        has_any_video = exists(
            select(1).select_from(ProductVideo).where(ProductVideo.product_id == Product.id)
        )
        missing_photo = or_(Product.image_path.is_(None), Product.image_path == "")
        queue_base = [Product.in_store.is_(True), Product.no_video_confirmed.is_(False), missing_photo, ~has_confirmed_video]
        if video_status == "needs_search":
            stmt = stmt.where(*queue_base, ~has_any_video)
        elif video_status == "has_candidates":
            stmt = stmt.where(*queue_base, candidate_count > 0)
        else:
            raise HTTPException(status_code=400, detail="Invalid video_status")
    elif no_video:
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
            "image_url": f"/media/{product.image_path}" if product.image_path else None,
            "category_name": product.category.name if product.category else None,
            "brand_name": product.brand.name if product.brand else None,
            "barcode_count": int(barcode_count_value or 0),
            "video_count": int(video_count_value or 0),
            "candidate_count": int(candidate_count_value or 0),
            "in_store": product.in_store,
            "shot_count": product.shot_count,
            "catalog_page": product.catalog_page,
            "created_at": product.created_at,
        }
        for product, barcode_count_value, video_count_value, candidate_count_value in rows
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


@router.get("/all-categories")
def list_all_categories(db: Session = Depends(get_db)):
    return [
        {"id": row.id, "name": row.name}
        for row in db.execute(select(ProductCategory).order_by(ProductCategory.name.asc())).scalars().all()
    ]


@router.get("/all-brands")
def list_all_brands(db: Session = Depends(get_db)):
    return [
        {"id": row.id, "name": row.name}
        for row in db.execute(select(ProductBrand).order_by(ProductBrand.name.asc())).scalars().all()
    ]


@router.post("/")
def create_product(payload: ProductCreateRequest, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    product = Product(
        name=name,
        item_number=(payload.item_number or "").strip() or None,
        packing=(payload.packing or "").strip() or None,
        description=payload.description,
        notes=payload.notes,
        category_id=_get_or_create_category(db, payload.category_name),
        brand_id=_get_or_create_brand(db, payload.brand_name),
        shot_count=payload.shot_count,
        duration_seconds=payload.duration_seconds,
        effects=payload.effects,
        in_store=payload.in_store,
        needs_data_review=payload.needs_data_review,
    )
    db.add(product)
    db.flush()

    barcode = (payload.barcode or "").strip()
    if barcode:
        db.add(ProductBarcode(product_id=product.id, barcode=barcode, is_primary=True))

    db.commit()
    return _serialize_product_detail(_get_product_detail(db, product.id))


@router.patch("/{product_id}")
def update_product(product_id: str, payload: ProductUpdateRequest, db: Session = Depends(get_db)):
    product = _get_product_detail(db, product_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "category_name" in update_data:
        product.category_id = _get_or_create_category(db, update_data.pop("category_name"))
    if "brand_name" in update_data:
        product.brand_id = _get_or_create_brand(db, update_data.pop("brand_name"))
    if "name" in update_data:
        stripped = (update_data.pop("name") or "").strip()
        if not stripped:
            raise HTTPException(status_code=400, detail="Name is required")
        product.name = stripped
    if "item_number" in update_data:
        product.item_number = (update_data.pop("item_number") or "").strip() or None
    if "packing" in update_data:
        product.packing = (update_data.pop("packing") or "").strip() or None

    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    return _serialize_product_detail(_get_product_detail(db, product_id))


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


@router.post("/{product_id}/barcodes")
def add_barcode(product_id: str, payload: BarcodeAddRequest, db: Session = Depends(get_db)):
    """Add (or replace primary) barcode for a product. Used when linking an unknown scan."""
    product = db.execute(select(Product).where(Product.id == product_id)).scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    barcode = payload.barcode.strip()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode required")

    if payload.is_primary:
        # Demote all existing primary barcodes
        db.execute(
            select(ProductBarcode).where(ProductBarcode.product_id == product_id)
        )
        existing = db.execute(
            select(ProductBarcode).where(
                ProductBarcode.product_id == product_id,
                ProductBarcode.is_primary.is_(True),
            )
        ).scalars().all()
        for row in existing:
            row.is_primary = False

    # Upsert the new barcode
    existing_row = db.execute(
        select(ProductBarcode).where(
            ProductBarcode.product_id == product_id,
            ProductBarcode.barcode == barcode,
        )
    ).scalars().first()

    if existing_row:
        existing_row.is_primary = payload.is_primary
    else:
        db.add(ProductBarcode(product_id=product_id, barcode=barcode, is_primary=payload.is_primary))

    db.commit()
    return {"ok": True, "product_id": product_id, "barcode": barcode}


@router.delete("/{product_id}/barcodes/{barcode_id}")
def delete_barcode(product_id: str, barcode_id: int, db: Session = Depends(get_db)):
    """Unlink a barcode from a product (e.g. it was attached to the wrong item)."""
    row = db.execute(
        select(ProductBarcode).where(
            ProductBarcode.id == barcode_id,
            ProductBarcode.product_id == product_id,
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Barcode not found for this product")

    barcode_value = row.barcode
    db.delete(row)
    db.commit()
    return {"ok": True, "product_id": product_id, "barcode": barcode_value}


@router.get("/{product_id}/aliases")
def list_product_aliases(product_id: str, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    aliases = (
        db.execute(
            select(ProductAlias)
            .where(ProductAlias.product_id == product_id)
            .order_by(ProductAlias.alias_name.asc())
        )
        .scalars()
        .all()
    )
    return [_serialize_alias(alias) for alias in aliases]


@router.post("/{product_id}/aliases")
def add_product_alias(product_id: str, payload: ProductAliasCreate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    alias_name = payload.alias_name.strip()
    if not alias_name:
        raise HTTPException(status_code=400, detail="Alias name required")

    existing = db.execute(
        select(ProductAlias).where(
            ProductAlias.product_id == product_id,
            func.lower(ProductAlias.alias_name) == alias_name.lower(),
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Alias already exists for this product")

    alias = ProductAlias(product_id=product_id, alias_name=alias_name, source=payload.source)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return _serialize_alias(alias)


@router.delete("/{product_id}/aliases/{alias_id}")
def delete_product_alias(product_id: str, alias_id: int, db: Session = Depends(get_db)):
    alias = (
        db.execute(
            select(ProductAlias).where(
                ProductAlias.id == alias_id, ProductAlias.product_id == product_id
            )
        )
        .scalars()
        .first()
    )
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")

    db.delete(alias)
    db.commit()
    return Response(status_code=204)


@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = _get_product_detail(db, product_id)
    return _serialize_product_detail(product)
