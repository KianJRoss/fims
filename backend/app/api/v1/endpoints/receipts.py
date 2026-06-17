from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.sales import Sale, SaleItem
from app.services.receipt_printer import STORE_NAME, print_receipt, receipt_print_payload

router = APIRouter()


def _get_sale_by_receipt_token(token: str, db: Session) -> Sale | None:
    return (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.items).joinedload(SaleItem.product))
            .where(Sale.receipt_token == token)
        )
        .unique()
        .scalar_one_or_none()
    )


@router.get("/{token}")
def get_receipt(token: str, db: Session = Depends(get_db)):
    sale = _get_sale_by_receipt_token(token, db)
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
        "store_name": STORE_NAME,
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


@router.post("/{token}/print")
def print_receipt_copy(
    token: str,
    background_tasks: BackgroundTasks,
    copy_type: Literal["customer", "merchant"] = Query("customer"),
    db: Session = Depends(get_db),
):
    sale = _get_sale_by_receipt_token(token, db)
    if sale is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if copy_type == "merchant" and sale.payment_method != "CARD":
        raise HTTPException(status_code=400, detail="Merchant receipt copies are only available for card payments")

    sale_for_print, items_for_print = receipt_print_payload(sale)
    background_tasks.add_task(print_receipt, sale_for_print, items_for_print, copy_type)
    return {
        "status": "queued",
        "copy_type": copy_type,
        "receipt_token": sale.receipt_token,
    }
