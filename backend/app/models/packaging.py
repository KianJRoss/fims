"""Case pack / packaging hierarchy. Cases break into units; cost per unit calculated from case cost."""
from sqlalchemy import String, Numeric, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class PackagingUnit(Base):
    __tablename__ = "packaging_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)  # EACH, PACK, CASE, DISPLAY


class CasePack(Base):
    """
    Defines how a product is packaged. A product may have multiple pack configs
    (e.g., sold as EACH or as a CASE of 12).
    cost_per_unit = case_cost / units_per_case
    """
    __tablename__ = "case_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    packaging_unit_id: Mapped[int] = mapped_column(ForeignKey("packaging_units.id"))
    units_per_case: Mapped[int] = mapped_column(Integer, default=1)
    case_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped["Product"] = relationship(back_populates="case_packs")  # type: ignore[name-defined]
    packaging_unit: Mapped["PackagingUnit"] = relationship()

    @property
    def cost_per_unit(self) -> float | None:
        if self.case_cost is None or self.units_per_case == 0:
            return None
        return float(self.case_cost) / self.units_per_case
