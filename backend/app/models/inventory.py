"""
Event-based inventory. Never store a running total — derive it from events.
Events: received, sold, damaged, adjusted, counted, transferred.
"""
from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # RECEIVED, SOLD, DAMAGED, ADJUSTED, COUNTED, RETURNED, TRANSFERRED
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # positive = stock added, negative = stock removed
    unit_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    reference_id: Mapped[str | None] = mapped_column(String(80))  # sale_id, PO number, etc.
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped["Product"] = relationship(back_populates="inventory_events")  # type: ignore[name-defined]
