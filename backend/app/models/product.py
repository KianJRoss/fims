"""
Core product model. Internal Product ID is the true identifier.
Barcodes are many-to-many: one product → many barcodes, one barcode → many products.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class ProductBrand(Base):
    __tablename__ = "product_brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="brand")


class Product(Base):
    __tablename__ = "products"

    # Internal ID — true unique identifier, never changes
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Display / search fields
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_number: Mapped[str | None] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # Classification
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("product_brands.id"))

    # Fireworks-specific
    shot_count: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    effects: Mapped[str | None] = mapped_column(Text)  # comma-separated tags

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    category: Mapped["ProductCategory | None"] = relationship(back_populates="products")
    brand: Mapped["ProductBrand | None"] = relationship(back_populates="products")
    barcodes: Mapped[list["ProductBarcode"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    prices: Mapped[list["ProductPrice"]] = relationship(back_populates="product")  # type: ignore[name-defined]
    videos: Mapped[list["ProductVideo"]] = relationship(back_populates="product")  # type: ignore[name-defined]
    case_packs: Mapped[list["CasePack"]] = relationship(back_populates="product")  # type: ignore[name-defined]
    supplier_products: Mapped[list["SupplierProduct"]] = relationship(back_populates="product")  # type: ignore[name-defined]
    inventory_events: Mapped[list["InventoryEvent"]] = relationship(back_populates="product")  # type: ignore[name-defined]


class ProductBarcode(Base):
    """
    Many-to-many: a barcode can map to multiple products (same item, different packaging)
    and a product can have multiple barcodes (repackaged, variant SKUs).
    """
    __tablename__ = "product_barcodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    barcode: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    barcode_type: Mapped[str] = mapped_column(String(20), default="UPC")  # UPC, EAN, QR, CUSTOM
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(255))

    product: Mapped["Product"] = relationship(back_populates="barcodes")
