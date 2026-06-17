from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StoreDocument(Base):
    __tablename__ = "store_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="Other")
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(60))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    doc_date: Mapped[str | None] = mapped_column(String(20))
