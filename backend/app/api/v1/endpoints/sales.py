from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.pricing import PriceType
from app.models.sales import Receipt, Sale, SaleItem

router = APIRouter()


class SaleItemPayload(BaseModel):
    product_id: str
    quantity: int
    unit_price: float
    discount_amount: float = 0


class SaleCreatePayload(BaseModel):
    items: list[SaleItemPayload] = Field(default_factory=list)
    subtotal: float
    total_discount: float
    total: float
    payment_method: str | None = None
    applied_deal_ids: list[int] = Field(default_factory=list)


def _serialize_sale(sale: Sale) -> dict[str, Any]:
    return {
        "id": sale.id,
        "cashier_id": sale.cashier_id,
        "price_type_id": sale.price_type_id,
        "subtotal": float(sale.subtotal),
        "discount_total": float(sale.discount_total),
        "tax_total": float(sale.tax_total),
        "grand_total": float(sale.grand_total),
        "payment_method": sale.payment_method,
        "status": sale.status,
        "notes": sale.notes,
        "created_at": sale.created_at,
        "completed_at": sale.completed_at,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "override_price": float(item.override_price) if item.override_price is not None else None,
                "discount_amount": float(item.discount_amount),
                "line_total": float(item.line_total),
                "deal_id": item.deal_id,
                "override_reason": item.override_reason,
                "override_authorized_by": item.override_authorized_by,
            }
            for item in sale.items
        ],
        "item_count": len(sale.items),
    }


def _sale_query(db: Session):
    return (
        select(Sale)
        .options(joinedload(Sale.items))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
    )


@router.post("/")
def create_sale(payload: SaleCreatePayload, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    retail_price_type_id = db.execute(select(PriceType.id).where(PriceType.code == "RETAIL")).scalar_one_or_none()

    sale = Sale(
        cashier_id=None,
        price_type_id=retail_price_type_id,
        subtotal=payload.subtotal,
        discount_total=payload.total_discount,
        tax_total=0,
        grand_total=payload.total,
        payment_method=payload.payment_method,
        status="completed",
        completed_at=now,
    )
    db.add(sale)
    db.flush()

    for item in payload.items:
        line_discount = max(0.0, float(item.discount_amount))
        line_total = max(0.0, item.quantity * item.unit_price - line_discount)
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=line_discount,
                line_total=line_total,
            )
        )

    receipt = Receipt(
        sale_id=sale.id,
        receipt_number=f"R-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
        printed_at=None,
    )
    db.add(receipt)
    db.commit()

    refreshed_sale = (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.items), joinedload(Sale.receipt))
            .where(Sale.id == sale.id)
        )
        .unique()
        .scalar_one()
    )
    return _serialize_sale(refreshed_sale)


@router.get("/")
def list_sales(db: Session = Depends(get_db)):
    sales = db.execute(_sale_query(db).limit(50)).unique().scalars().all()
    return [_serialize_sale(sale) for sale in sales]


@router.get("/today")
def sales_today(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    midnight = datetime(now.year, now.month, now.day)
    sale_count = (
        db.execute(
            select(func.count(Sale.id)).where(Sale.created_at >= midnight, Sale.created_at <= now)
        ).scalar_one()
    )
    total = (
        db.execute(
            select(func.coalesce(func.sum(Sale.grand_total), 0)).where(
                Sale.created_at >= midnight,
                Sale.created_at <= now,
            )
        ).scalar_one()
    )
    items_sold = (
        db.execute(
            select(func.coalesce(func.sum(SaleItem.quantity), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.created_at >= midnight, Sale.created_at <= now)
        ).scalar_one()
    )
    count = int(sale_count or 0)
    total_value = float(total or 0)
    items_value = int(items_sold or 0)
    avg_ticket = total_value / count if count else 0.0
    return {
        "count": count,
        "total": total_value,
        "avg_ticket": avg_ticket,
        "items_sold": items_value,
    }
