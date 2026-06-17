"""
Product name matching helpers.

Used to resolve a free-text product name (as it appears on an invoice, price
list, or catalog) to an internal Product record, checking both the
canonical Product.name and any recorded ProductAlias rows.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductAlias


def _normalize(name: str) -> str:
    """Collapse whitespace and lowercase for case/whitespace-insensitive matching."""
    return re.sub(r"\s+", " ", name.strip()).lower()


def find_product_by_alias(db: Session, name: str) -> Product | None:
    """
    Look up a Product by exact name or by a recorded alias, normalizing
    whitespace and case (e.g. "Game On!", "Game On", "GAME ON" all match).
    Returns None if no match is found.
    """
    normalized = _normalize(name)
    if not normalized:
        return None

    product = db.execute(
        select(Product).where(func.lower(func.trim(Product.name)) == normalized)
    ).scalars().first()
    if product:
        return product

    alias = db.execute(
        select(ProductAlias).where(func.lower(func.trim(ProductAlias.alias_name)) == normalized)
    ).scalars().first()
    if alias:
        return alias.product

    return None
