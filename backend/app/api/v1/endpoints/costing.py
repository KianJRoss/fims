from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.costing import ProductCosting
from app.models.pricing import PriceType, ProductPrice
from app.models.product import Product

router = APIRouter()


class CostingUpsertPayload(BaseModel):
    product_id: str
    boxes_per_case: int = Field(gt=0)
    units_per_box: int = Field(gt=0)
    case_cost: Decimal
    markup_multiplier: Decimal


def _retail_price(case_cost: Decimal, boxes_per_case: int, units_per_box: int, markup_multiplier: Decimal) -> Decimal:
    unit_cost = case_cost / Decimal(boxes_per_case * units_per_box)
    return (Decimal(round(unit_cost * markup_multiplier)) - Decimal("0.05")).quantize(Decimal("0.01"))


def _serialize_row(product: Product, costing: ProductCosting | None, manual_retail: Decimal | None = None) -> dict[str, Any]:
    if manual_retail is not None:
        retail_price = manual_retail
        retail_source = "manual"
    elif costing and costing.retail_price is not None:
        retail_price = costing.retail_price
        retail_source = "costing"
    else:
        retail_price = None
        retail_source = None

    return {
        "product_id": product.id,
        "item_number": product.item_number,
        "image_url": f"/media/{product.image_path}" if product.image_path else None,
        "name": product.name,
        "packing": product.packing,
        "boxes_per_case": costing.boxes_per_case if costing else None,
        "units_per_box": costing.units_per_box if costing else None,
        "case_cost": float(costing.case_cost) if costing else None,
        "markup_multiplier": float(costing.markup_multiplier) if costing else None,
        "retail_price": float(retail_price) if retail_price is not None else None,
        "retail_source": retail_source,
        "category_name": product.category.name if product.category else None,
    }


def _get_retail_price_type_id(db: Session) -> int:
    price_type_id = (
        db.execute(
            select(PriceType.id).where(
                or_(func.upper(PriceType.name) == "RETAIL", func.upper(PriceType.code) == "RETAIL")
            )
        )
        .scalars()
        .first()
    )
    if price_type_id is None:
        raise HTTPException(status_code=404, detail="Retail price type not found")
    return price_type_id


@router.get("/")
def list_costing_rows(db: Session = Depends(get_db)):
    manual_retail_prices: dict[str, Decimal] = {}
    try:
        retail_price_type_id = _get_retail_price_type_id(db)
    except HTTPException:
        retail_price_type_id = None
    if retail_price_type_id is not None:
        manual_retail_prices = {
            product_id: amount
            for product_id, amount in db.execute(
                select(ProductPrice.product_id, ProductPrice.amount)
                .where(
                    ProductPrice.price_type_id == retail_price_type_id,
                    ProductPrice.is_active.is_(True),
                )
                .order_by(ProductPrice.effective_from.asc())
            )
        }

    rows = (
        db.execute(
            select(Product, ProductCosting)
            .select_from(Product)
            .options(joinedload(Product.category))
            .outerjoin(ProductCosting, ProductCosting.product_id == Product.id)
            .where(Product.is_active.is_(True), Product.in_store.is_(True))
            .order_by(func.lower(Product.name), func.lower(Product.item_number))
        )
        .unique()
        .all()
    )
    return [
        _serialize_row(product, costing, manual_retail=manual_retail_prices.get(product.id))
        for product, costing in rows
    ]


@router.post("/")
def upsert_costing(payload: CostingUpsertPayload, db: Session = Depends(get_db)):
    product = (
        db.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.id == payload.product_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    retail_price = _retail_price(payload.case_cost, payload.boxes_per_case, payload.units_per_box, payload.markup_multiplier)
    now = datetime.now(timezone.utc)

    costing = db.execute(select(ProductCosting).where(ProductCosting.product_id == payload.product_id)).scalar_one_or_none()
    if costing is None:
        costing = ProductCosting(
            product_id=payload.product_id,
            boxes_per_case=payload.boxes_per_case,
            units_per_box=payload.units_per_box,
            case_cost=payload.case_cost,
            markup_multiplier=payload.markup_multiplier,
            retail_price=retail_price,
            created_at=now,
            updated_at=now,
        )
        db.add(costing)
    else:
        costing.boxes_per_case = payload.boxes_per_case
        costing.units_per_box = payload.units_per_box
        costing.case_cost = payload.case_cost
        costing.markup_multiplier = payload.markup_multiplier
        costing.retail_price = retail_price
        costing.updated_at = now

    retail_price_type_id = _get_retail_price_type_id(db)
    price_row = (
        db.execute(
            select(ProductPrice)
            .where(
                ProductPrice.product_id == payload.product_id,
                ProductPrice.price_type_id == retail_price_type_id,
            )
            .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
        )
        .scalars()
        .first()
    )
    if price_row is None:
        db.add(
            ProductPrice(
                product_id=payload.product_id,
                price_type_id=retail_price_type_id,
                amount=retail_price,
                is_active=True,
                effective_from=now,
            )
        )
    else:
        price_row.amount = retail_price
        price_row.is_active = True
        price_row.effective_from = now

    db.commit()
    saved_product = (
        db.execute(
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.id == payload.product_id)
        )
        .unique()
        .scalar_one()
    )
    saved_costing = db.execute(select(ProductCosting).where(ProductCosting.product_id == payload.product_id)).scalar_one()
    return _serialize_row(saved_product, saved_costing)


@router.delete("/{product_id}")
def delete_costing(product_id: str, db: Session = Depends(get_db)):
    costing = db.execute(select(ProductCosting).where(ProductCosting.product_id == product_id)).scalar_one_or_none()
    if costing is None:
        raise HTTPException(status_code=404, detail="Costing not found")

    db.delete(costing)
    db.commit()
    return {"ok": True}
