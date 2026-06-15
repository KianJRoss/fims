"""
Deal / discount engine. Supports Buy X Get Y, bundles, category discounts, flat amount, percent.
Deals have conditions (what triggers them) and rewards (what they give).
"""
from datetime import datetime

from sqlalchemy import String, Numeric, Integer, ForeignKey, DateTime, Boolean, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    deal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # BXGY, BUNDLE, CATEGORY_PCT, FLAT_AMOUNT, PERCENT_OFF, CLEARANCE
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher = evaluated first
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_stackable: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    conditions: Mapped[list["DealCondition"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )
    rewards: Mapped[list["DealReward"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )


class DealCondition(Base):
    """What must be in the cart to trigger the deal."""
    __tablename__ = "deal_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), nullable=False)
    condition_type: Mapped[str] = mapped_column(String(30))  # PRODUCT, CATEGORY, MIN_QUANTITY, MIN_AMOUNT
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    min_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))

    deal: Mapped["Deal"] = relationship(back_populates="conditions")


class DealReward(Base):
    """What the customer gets when the deal triggers."""
    __tablename__ = "deal_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(30))  # FREE_ITEM, PERCENT_OFF, FLAT_OFF, CHEAPEST_FREE
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"))  # for FREE_ITEM
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"))
    percent_off: Mapped[float | None] = mapped_column(Numeric(5, 2))
    flat_off: Mapped[float | None] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    deal: Mapped["Deal"] = relationship(back_populates="rewards")
