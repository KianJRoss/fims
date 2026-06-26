from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.pricing import PriceType, ProductPrice
from app.models.sales import Receipt, Sale, SaleItem
from app.services.receipt_printer import print_receipt, receipt_print_payload

router = APIRouter()
MONEY_CENT = Decimal("0.01")
MONEY_TOLERANCE = Decimal("0.01")
TAX_RATE = Decimal("0.12")  # 12% sales tax applied to taxable line totals


class SaleItemPayload(BaseModel):
    product_id: str
    quantity: int
    unit_price: float
    discount_amount: float = 0
    # Taxable by default; the cashier can flip this off per item via the
    # "No Tax" button on the Sales screen.
    taxable: bool = True


class SaleCreatePayload(BaseModel):
    items: list[SaleItemPayload] = Field(default_factory=list)
    subtotal: float
    total_discount: float
    tax_total: float = 0
    total: float
    payment_method: str | None = None
    card_last4: str | None = None
    applied_deal_ids: list[int] = Field(default_factory=list)


@dataclass(frozen=True)
class ValidatedSaleItem:
    product_id: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal
    taxable: bool


def _serialize_sale(sale: Sale) -> dict[str, Any]:
    return {
        "id": sale.id,
        "cashier_id": sale.cashier_id,
        "price_type_id": sale.price_type_id,
        "receipt_token": sale.receipt_token,
        "subtotal": float(sale.subtotal),
        "discount_total": float(sale.discount_total),
        "tax_total": float(sale.tax_total),
        "grand_total": float(sale.grand_total),
        "payment_method": sale.payment_method,
        "card_last4": sale.card_last4,
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


def _sale_query():
    return (
        select(Sale)
        .options(joinedload(Sale.items))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
    )


def _money(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def _validate_sale_payload(
    payload: SaleCreatePayload,
    db: Session,
) -> tuple[list[ValidatedSaleItem], Decimal, Decimal, Decimal, Decimal]:
    line_items: list[ValidatedSaleItem] = []
    expected_subtotal = Decimal("0.00")
    expected_discount = Decimal("0.00")
    expected_total = Decimal("0.00")
    expected_taxable_base = Decimal("0.00")
    product_ids = {item.product_id for item in payload.items}
    price_rows = (
        db.execute(
            select(ProductPrice.product_id, ProductPrice.amount).where(
                ProductPrice.product_id.in_(product_ids),
            )
        )
        .all()
        if product_ids
        else []
    )
    prices_by_product: dict[str, set[Decimal]] = {}
    for product_id, amount in price_rows:
        prices_by_product.setdefault(product_id, set()).add(_money(amount))

    for item in payload.items:
        quantity = int(item.quantity)
        unit_price = _money(item.unit_price)
        line_discount = max(Decimal("0.00"), _money(item.discount_amount))
        line_subtotal = _money(unit_price * quantity)
        line_total = max(Decimal("0.00"), _money(line_subtotal - line_discount))

        valid_prices = prices_by_product.get(item.product_id, set())
        if unit_price not in valid_prices:
            raise HTTPException(
                status_code=400,
                detail=f"Submitted unit price {unit_price} does not match any product price for product {item.product_id}",
            )

        expected_subtotal += line_subtotal
        expected_discount += line_discount
        expected_total += line_total
        if item.taxable:
            expected_taxable_base += line_total
        line_items.append(
            ValidatedSaleItem(
                product_id=item.product_id,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=line_discount,
                line_total=line_total,
                taxable=bool(item.taxable),
            )
        )

    expected_tax = _money(expected_taxable_base * TAX_RATE)
    expected_grand = _money(expected_total + expected_tax)

    submitted_subtotal = _money(payload.subtotal)
    submitted_discount = _money(payload.total_discount)
    submitted_tax = _money(payload.tax_total)
    submitted_total = _money(payload.total)
    if abs(expected_subtotal - submitted_subtotal) > MONEY_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=f"Submitted subtotal {submitted_subtotal} does not match line-item subtotal {expected_subtotal}",
        )
    if abs(expected_discount - submitted_discount) > MONEY_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=f"Submitted discount total {submitted_discount} does not match line-item discounts {expected_discount}",
        )
    if abs(expected_tax - submitted_tax) > MONEY_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=f"Submitted tax total {submitted_tax} does not match computed tax {expected_tax}",
        )
    if abs(expected_grand - submitted_total) > MONEY_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=f"Submitted total {submitted_total} does not match line-item total {expected_grand}",
        )
    return line_items, expected_subtotal, expected_discount, expected_tax, expected_grand


@router.post("/")
def create_sale(
    payload: SaleCreatePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    retail_price_type_id = db.execute(select(PriceType.id).where(PriceType.code == "RETAIL")).scalar_one_or_none()
    line_items, subtotal, discount_total, tax_total, grand_total = _validate_sale_payload(payload, db)

    sale = Sale(
        cashier_id=None,
        price_type_id=retail_price_type_id,
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        grand_total=grand_total,
        payment_method=payload.payment_method,
        card_last4=payload.card_last4 if payload.payment_method == "CARD" else None,
        status="completed",
        completed_at=now,
    )
    db.add(sale)
    db.flush()

    for item in line_items:
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                line_total=item.line_total,
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
            .options(
                joinedload(Sale.items).joinedload(SaleItem.product),
                joinedload(Sale.receipt),
            )
            .where(Sale.id == sale.id)
        )
        .unique()
        .scalar_one()
    )
    sale_for_print, items_for_print = receipt_print_payload(refreshed_sale)
    background_tasks.add_task(print_receipt, sale_for_print, items_for_print, "customer")
    if refreshed_sale.payment_method == "CARD":
        background_tasks.add_task(print_receipt, sale_for_print, items_for_print, "merchant")
    return _serialize_sale(refreshed_sale)


@router.get("/")
def list_sales(db: Session = Depends(get_db)):
    sales = db.execute(_sale_query().limit(50)).unique().scalars().all()
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
