"""Product costing data tied to the active in-store catalog."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ProductCosting(Base):
    __tablename__ = "product_costing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    boxes_per_case: Mapped[int] = mapped_column(Integer, nullable=False)
    units_per_box: Mapped[int] = mapped_column(Integer, nullable=False)
    case_cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    markup_multiplier: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    retail_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    product: Mapped["Product"] = relationship(back_populates="costing")  # type: ignore[name-defined]
