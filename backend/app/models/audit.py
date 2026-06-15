"""Append-only audit log for price overrides, manager discounts, voided sales."""
from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    # PRICE_OVERRIDE, SALE_VOID, MANUAL_DISCOUNT, LOGIN, IMPORT_APPROVED, etc.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    authorizer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str | None] = mapped_column(String(60))  # Sale, Product, etc.
    entity_id: Mapped[str | None] = mapped_column(String(80))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
