from __future__ import annotations

from datetime import date as date_type, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.sales import Sale, SaleItem

router = APIRouter()


def _serialize_transaction(sale: Sale) -> dict[str, Any]:
    return {
        "id": sale.id,
        "receipt_token": sale.receipt_token,
        "created_at": sale.created_at,
        "payment_method": sale.payment_method,
        "total": float(sale.grand_total),
        "item_count": len(sale.items),
    }


@router.get("/daily")
def get_daily_report(date: date_type | None = Query(default=None), db: Session = Depends(get_db)):
    report_date = date or date_type.today()
    start = datetime(report_date.year, report_date.month, report_date.day)
    end = start + timedelta(days=1)

    sales = (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.items))
            .where(Sale.created_at >= start, Sale.created_at < end)
            .order_by(Sale.created_at.desc(), Sale.id.desc())
        )
        .unique()
        .scalars()
        .all()
    )

    transaction_count = len(sales)
    revenue = sum(float(sale.grand_total) for sale in sales)
    discount_total = sum(float(sale.discount_total) for sale in sales)
    avg_sale = revenue / transaction_count if transaction_count else 0.0

    cash_sales = [sale for sale in sales if (sale.payment_method or "").upper() == "CASH"]
    card_sales = [sale for sale in sales if (sale.payment_method or "").upper() == "CARD"]

    return {
        "date": report_date.isoformat(),
        "transaction_count": transaction_count,
        "revenue": revenue,
        "discount_total": discount_total,
        "avg_sale": avg_sale,
        "cash_count": len(cash_sales),
        "card_count": len(card_sales),
        "cash_revenue": sum(float(sale.grand_total) for sale in cash_sales),
        "card_revenue": sum(float(sale.grand_total) for sale in card_sales),
        "transactions": [_serialize_transaction(sale) for sale in sales],
    }


@router.get("/transaction/{sale_id}")
def get_transaction_detail(sale_id: str, db: Session = Depends(get_db)):
    sale = (
        db.execute(
            select(Sale)
            .options(joinedload(Sale.items).joinedload(SaleItem.product))
            .where(Sale.id == sale_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "id": sale.id,
        "receipt_token": sale.receipt_token,
        "created_at": sale.created_at,
        "completed_at": sale.completed_at,
        "payment_method": sale.payment_method,
        "card_last4": sale.card_last4,
        "subtotal": float(sale.subtotal),
        "discount_total": float(sale.discount_total),
        "total": float(sale.grand_total),
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "item_number": item.product.item_number if item.product else None,
                "qty": item.quantity,
                "unit_price": float(item.unit_price),
                "override_price": float(item.override_price) if item.override_price is not None else None,
                "discount_amount": float(item.discount_amount),
                "line_total": float(item.line_total),
            }
            for item in sale.items
        ],
    }
