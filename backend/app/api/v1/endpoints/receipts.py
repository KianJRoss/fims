from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.sales import Sale, SaleItem
from app.services.receipt_printer import (
    STORE_NAME,
    print_receipt,
    receipt_print_payload,
    render_receipt_text,
)

router = APIRouter()


def _sample_sale() -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    """A fake sale for previewing/iterating receipt layout without a real order."""
    items = [
        SimpleNamespace(product_id="demo-1", quantity=2, unit_price=24.99,
                        discount_amount=0, line_total=49.98,
                        product=SimpleNamespace(name="Excalibur 24-Shot Artillery")),
        SimpleNamespace(product_id="demo-2", quantity=1, unit_price=89.99,
                        discount_amount=10.0, line_total=79.99,
                        product=SimpleNamespace(name="500g Finale Cake - Grand Finale")),
    ]
    sale = SimpleNamespace(
        id="PREVIEW-0001", subtotal=139.98, discount_total=10.0, tax_total=0,
        grand_total=129.98, payment_method="CARD", card_last4="1234",
        created_at=datetime.utcnow(), completed_at=datetime.utcnow(),
    )
    return sale, items


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


@router.get("/preview/sample", response_class=Response)
def preview_sample_receipt(
    copy_type: Literal["customer", "merchant"] = Query("customer"),
):
    """Plaintext preview of a sample receipt -- for iterating layout/footer with no printer."""
    sale, items = _sample_sale()
    return Response(render_receipt_text(sale, items, copy_type), media_type="text/plain")


@router.get("/{token}/preview", response_class=Response)
def preview_receipt(
    token: str,
    copy_type: Literal["customer", "merchant"] = Query("customer"),
    db: Session = Depends(get_db),
):
    """Plaintext preview of a real sale's receipt (no print job sent)."""
    sale = _get_sale_by_receipt_token(token, db)
    if sale is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    sale_copy, item_copies = receipt_print_payload(sale)
    return Response(render_receipt_text(sale_copy, item_copies, copy_type), media_type="text/plain")


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
