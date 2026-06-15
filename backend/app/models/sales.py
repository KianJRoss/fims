from datetime import datetime
import uuid

from sqlalchemy import String, Numeric, Integer, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cashier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    price_type_id: Mapped[int | None] = mapped_column(ForeignKey("price_types.id"))
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    discount_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    tax_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    payment_method: Mapped[str | None] = mapped_column(String(30))  # CASH, CARD, CHECK
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, completed, voided
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    receipt: Mapped["Receipt | None"] = relationship(back_populates="sale", uselist=False)


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # original price
    override_price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # if cashier overrode
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)  # from deals
    line_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"))
    override_reason: Mapped[str | None] = mapped_column(String(255))
    override_authorized_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    sale: Mapped["Sale"] = relationship(back_populates="items")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"), unique=True)
    receipt_number: Mapped[str] = mapped_column(String(30), unique=True)
    printed_at: Mapped[datetime | None] = mapped_column(DateTime)
    emailed_to: Mapped[str | None] = mapped_column(String(255))

    sale: Mapped["Sale"] = relationship(back_populates="receipt")
