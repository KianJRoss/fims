"""Product videos — barcode scan triggers playback on connected display / Pi kiosk."""
from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ProductVideo(Base):
    __tablename__ = "product_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)  # relative to MEDIA_ROOT
    source: Mapped[str] = mapped_column(String(20), default="LOCAL")
    url: Mapped[str | None] = mapped_column(String(1024))
    youtube_id: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    search_query: Mapped[str | None] = mapped_column(String(512))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped["Product"] = relationship(back_populates="videos")  # type: ignore[name-defined]
