"""
Import pipeline: PDF/CSV/Excel supplier documents go through a job with per-row
human review before any product matching is committed.
"""
from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    document_type: Mapped[str] = mapped_column(String(30))  # PRICE_LIST, INVOICE, SALES_ORDER
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending → parsing → review → approved → importing → done / failed
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ImportRow(Base):
    """One row from a parsed supplier document, awaiting human review/match."""
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False)  # original parsed row
    matched_product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    match_confidence: Mapped[float | None] = mapped_column()  # 0.0–1.0
    match_method: Mapped[str | None] = mapped_column(String(60))
    # INTERNAL_ID, ITEM_NUM_BRAND, BARCODE, NAME_BRAND, MANUAL
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending, approved, rejected, skipped
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    job: Mapped["ImportJob"] = relationship(back_populates="rows")
