from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.pricing import PriceHistory, PriceType, ProductPrice
from app.models.product import Product, ProductCategory

router = APIRouter()

STANDARD_PRICE_TYPES: list[dict[str, Any]] = [
    {"code": "RETAIL", "name": "Retail Price", "sort_order": 1, "requires_auth": False},
    {"code": "SALE", "name": "Sale Price", "sort_order": 2, "requires_auth": False},
    {"code": "WHOLE", "name": "Wholesale Price", "sort_order": 3, "requires_auth": False},
    {"code": "COST", "name": "Our Cost", "sort_order": 4, "requires_auth": True},
    {"code": "TENT", "name": "Tent Event Price", "sort_order": 5, "requires_auth": False},
]


class PriceUpdatePayload(BaseModel):
    amount: float
    reason: str | None = None


def _serialize_price_type(price_type: PriceType) -> dict[str, Any]:
    return {
        "id": price_type.id,
        "code": price_type.code,
        "name": price_type.name,
        "requires_auth": price_type.requires_auth,
        "sort_order": price_type.sort_order,
    }


def _serialize_price(product_price: ProductPrice) -> dict[str, Any]:
    return {
        "id": product_price.id,
        "price_type_code": product_price.price_type.code if product_price.price_type else None,
        "price_type_name": product_price.price_type.name if product_price.price_type else None,
        "amount": float(product_price.amount),
        "effective_from": product_price.effective_from,
    }


def _serialize_product_row(product: Product) -> dict[str, Any]:
    price_map: dict[str, ProductPrice] = {}
    for price in sorted(
        product.prices,
        key=lambda item: (
            item.price_type.sort_order if item.price_type else 999,
            item.effective_from or datetime.min,
            item.id,
        ),
    ):
        if not price.is_active or not price.price_type:
            continue
        current = price_map.get(price.price_type.code)
        if current is None or (price.effective_from or datetime.min) >= (current.effective_from or datetime.min):
            price_map[price.price_type.code] = price

    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "brand_name": product.brand.name if product.brand else None,
        "category_name": product.category.name if product.category else None,
        "brand_id": product.brand_id,
        "category_id": product.category_id,
        "in_store": product.in_store,
        "catalog_page": product.catalog_page,
        "prices": {
            price_type["code"]: (
                float(price_map[price_type["code"]].amount)
                if price_type["code"] in price_map
                else None
            )
            for price_type in STANDARD_PRICE_TYPES
        },
    }


def _serialize_product_detail(product: Product) -> dict[str, Any]:
    prices = [
        _serialize_price(price)
        for price in sorted(
            [price for price in product.prices if price.is_active and price.price_type],
            key=lambda item: (
                item.price_type.sort_order if item.price_type else 999,
                item.effective_from or datetime.min,
                item.id,
            ),
        )
    ]
    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "brand_name": product.brand.name if product.brand else None,
        "category_name": product.category.name if product.category else None,
        "brand_id": product.brand_id,
        "category_id": product.category_id,
        "in_store": product.in_store,
        "catalog_page": product.catalog_page,
        "prices": prices,
    }


def _get_product(db: Session, product_id: str) -> Product:
    product = (
        db.execute(
            select(Product)
            .options(
                joinedload(Product.brand),
                joinedload(Product.category),
                joinedload(Product.prices).joinedload(ProductPrice.price_type),
            )
            .where(Product.id == product_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def _get_price_type(db: Session, price_type_code: str) -> PriceType:
    price_type = (
        db.execute(select(PriceType).where(func.upper(PriceType.code) == price_type_code.upper()))
        .scalar_one_or_none()
    )
    if price_type is None:
        raise HTTPException(status_code=404, detail="Price type not found")
    return price_type


def _get_product_price(db: Session, product_id: str, price_type_id: int) -> ProductPrice | None:
    return (
        db.execute(
            select(ProductPrice)
            .options(joinedload(ProductPrice.price_type))
            .where(ProductPrice.product_id == product_id, ProductPrice.price_type_id == price_type_id)
            .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
        )
        .scalars()
        .first()
    )


@router.get("/types")
def list_price_types(db: Session = Depends(get_db)):
    price_types = (
        db.execute(select(PriceType).order_by(PriceType.sort_order.asc(), func.lower(PriceType.name)))
        .scalars()
        .all()
    )
    return [_serialize_price_type(price_type) for price_type in price_types]


@router.post("/seed-types")
def seed_price_types(db: Session = Depends(get_db)):
    existing = {
        price_type.code: price_type
        for price_type in db.execute(select(PriceType).where(PriceType.code.in_([item["code"] for item in STANDARD_PRICE_TYPES]))).scalars().all()
    }
    for item in STANDARD_PRICE_TYPES:
        price_type = existing.get(item["code"])
        if price_type is None:
            db.add(
                PriceType(
                    code=item["code"],
                    name=item["name"],
                    sort_order=item["sort_order"],
                    requires_auth=item["requires_auth"],
                )
            )
            continue
        price_type.name = item["name"]
        price_type.sort_order = item["sort_order"]
        price_type.requires_auth = item["requires_auth"]
    db.commit()
    return {"count": len(STANDARD_PRICE_TYPES)}


@router.get("/")
def list_pricing_products(
    q: str | None = None,
    category: str | None = None,
    category_id: int | None = None,
    brand_id: list[int] = Query(default=[]),
    in_store: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    stmt = (
        select(Product)
        .options(
            joinedload(Product.brand),
            joinedload(Product.category),
            joinedload(Product.prices).joinedload(ProductPrice.price_type),
        )
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

    stmt = stmt.order_by(func.lower(Product.name), Product.created_at.desc())
    products = db.execute(stmt.offset(skip).limit(limit)).unique().scalars().all()
    return [_serialize_product_row(product) for product in products]


@router.get("/{product_id}")
def get_product_prices(product_id: str, db: Session = Depends(get_db)):
    product = _get_product(db, product_id)
    return _serialize_product_detail(product)


@router.put("/{product_id}/{price_type_code}")
def set_product_price(
    product_id: str,
    price_type_code: str,
    payload: PriceUpdatePayload,
    db: Session = Depends(get_db),
):
    product = _get_product(db, product_id)
    price_type = _get_price_type(db, price_type_code)
    now = datetime.utcnow()
    existing = _get_product_price(db, product_id, price_type.id)

    if existing is not None:
        db.add(
            PriceHistory(
                product_id=product.id,
                price_type_id=price_type.id,
                old_amount=float(existing.amount) if existing.amount is not None else None,
                new_amount=payload.amount,
                reason=payload.reason,
                changed_at=now,
            )
        )
        existing.amount = payload.amount
        existing.is_active = True
        existing.effective_from = now
    else:
        db.add(
            PriceHistory(
                product_id=product.id,
                price_type_id=price_type.id,
                old_amount=None,
                new_amount=payload.amount,
                reason=payload.reason,
                changed_at=now,
            )
        )
        db.add(
            ProductPrice(
                product_id=product.id,
                price_type_id=price_type.id,
                amount=payload.amount,
                is_active=True,
                effective_from=now,
            )
        )

    db.commit()
    return _serialize_product_detail(_get_product(db, product_id))


@router.delete("/{product_id}/{price_type_code}")
def delete_product_price(product_id: str, price_type_code: str, db: Session = Depends(get_db)):
    product = _get_product(db, product_id)
    price_type = _get_price_type(db, price_type_code)
    price = _get_product_price(db, product_id, price_type.id)
    if price is None:
        raise HTTPException(status_code=404, detail="Product price not found")
    price.is_active = False
    db.commit()
    return _serialize_product_detail(_get_product(db, product_id))


@router.get("/{product_id}/history")
def list_price_history(product_id: str, db: Session = Depends(get_db)):
    history_rows = (
        db.execute(
            select(PriceHistory, PriceType.name.label("price_type_name"), PriceType.code.label("price_type_code"))
            .join(PriceType, PriceType.id == PriceHistory.price_type_id)
            .where(PriceHistory.product_id == product_id)
            .order_by(PriceHistory.changed_at.desc(), PriceHistory.id.desc())
        )
        .all()
    )
    return [
        {
            "id": history.id,
            "product_id": history.product_id,
            "price_type_id": history.price_type_id,
            "price_type_code": price_type_code,
            "price_type_name": price_type_name,
            "old_amount": float(history.old_amount) if history.old_amount is not None else None,
            "new_amount": float(history.new_amount),
            "reason": history.reason,
            "changed_by_user_id": history.changed_by_user_id,
            "changed_at": history.changed_at,
        }
        for history, price_type_name, price_type_code in history_rows
    ]
