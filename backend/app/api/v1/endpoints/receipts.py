from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.sales import Sale, SaleItem

router = APIRouter()


@router.get("/{token}")
def get_receipt(token: str, db: Session = Depends(get_db)):
    sale = (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.items).joinedload(SaleItem.product))
            .where(Sale.receipt_token == token)
        )
        .unique()
        .scalar_one_or_none()
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {
        "id": sale.id,
        "created_at": sale.created_at,
        "payment_method": sale.payment_method,
        "card_last4": sale.card_last4,
        "receipt_token": sale.receipt_token,
        "subtotal": float(sale.subtotal),
        "discount_total": float(sale.discount_total),
        "total": float(sale.grand_total),
        "store_name": "Main Street Fireworks",
        "items": [
            {
                "name": item.product.name if item.product else None,
                "item_number": item.product.item_number if item.product else None,
                "qty": item.quantity,
                "unit_price": float(item.unit_price),
                "line_total": float(item.line_total),
            }
            for item in sale.items
        ],
    }
