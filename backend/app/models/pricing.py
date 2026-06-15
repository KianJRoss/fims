"""
Multi-price system with full history. Prices are never deleted — only superseded.
"""
from datetime import datetime

from sqlalchemy import String, Numeric, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class PriceType(Base):
    """Retail, Sale, Wholesale, Employee, Tent, Clearance, Manager Override, Cost"""
    __tablename__ = "price_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # RETAIL, SALE, WHOLE, etc.
    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProductPrice(Base):
    """Current active price for a product/price-type combination."""
    __tablename__ = "product_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    price_type_id: Mapped[int] = mapped_column(ForeignKey("price_types.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped["Product"] = relationship(back_populates="prices")  # type: ignore[name-defined]
    price_type: Mapped["PriceType"] = relationship()


class PriceHistory(Base):
    """Append-only log of every price change. Never updated, never deleted."""
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    price_type_id: Mapped[int] = mapped_column(ForeignKey("price_types.id"), nullable=False)
    old_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    new_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
