from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.product import ProductBrand


class Importer(Base):
    __tablename__ = "importers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(60))
    website: Mapped[str | None] = mapped_column(String(255))
    hq_state: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    brand_links: Mapped[list["BrandImporter"]] = relationship(back_populates="importer")


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="China")
    website: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    brand_links: Mapped[list["BrandManufacturer"]] = relationship(back_populates="manufacturer")


class BrandImporter(Base):
    __tablename__ = "brand_importers"
    __table_args__ = (UniqueConstraint("brand_id", "importer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("product_brands.id", ondelete="CASCADE"), nullable=False)
    importer_id: Mapped[int] = mapped_column(ForeignKey("importers.id", ondelete="CASCADE"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False, default="carries")
    notes: Mapped[str | None] = mapped_column(Text)

    brand: Mapped["ProductBrand"] = relationship(back_populates="importer_links")
    importer: Mapped["Importer"] = relationship(back_populates="brand_links")


class BrandManufacturer(Base):
    __tablename__ = "brand_manufacturers"
    __table_args__ = (UniqueConstraint("brand_id", "manufacturer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("product_brands.id", ondelete="CASCADE"), nullable=False)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    brand: Mapped["ProductBrand"] = relationship(back_populates="manufacturer_links")
    manufacturer: Mapped["Manufacturer"] = relationship(back_populates="brand_links")
