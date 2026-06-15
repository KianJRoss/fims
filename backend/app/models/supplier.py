from datetime import datetime

from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    contact_info: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)

    products: Mapped[list["SupplierProduct"]] = relationship(back_populates="supplier")


class SupplierProduct(Base):
    """
    Links a supplier's item number / barcode to an internal FIMS product.
    Multiple supplier records can map to one product (cross-supplier),
    or remain unlinked until the import review approves a match.
    """
    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))  # null until matched
    supplier_item_number: Mapped[str | None] = mapped_column(String(80))
    supplier_product_name: Mapped[str | None] = mapped_column(String(255))
    supplier_barcode: Mapped[str | None] = mapped_column(String(60))
    supplier_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict | None] = mapped_column(JSON)  # original row from import

    supplier: Mapped["Supplier"] = relationship(back_populates="products")
    product: Mapped["Product | None"] = relationship(back_populates="supplier_products")  # type: ignore[name-defined]
