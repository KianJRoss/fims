"""Shared barcode resolution with fuzzy fallback for mis-scanned 1s."""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.models.product import Product, ProductBarcode


def resolve_product_ids(db: Session, barcode: str) -> tuple[list[str], bool]:
    """
    Return product_ids for a barcode.  Tries exact match first, then falls back
    to stripping all '1' digits from both the scanned barcode and stored barcodes
    (the text-layer OCR often drops/duplicates '1' because they look like lines).
    Returns a list because one barcode can legitimately map to several products.
    The boolean is true when the result came from the stripped-'1' fallback.
    """
    rows = db.execute(
        select(ProductBarcode.product_id)
        .join(Product, Product.id == ProductBarcode.product_id)
        .where(ProductBarcode.barcode == barcode, Product.is_active.is_(True))
    ).scalars().all()

    if rows:
        return list(rows), False

    # Fuzzy: compare with '1's removed
    stripped = barcode.replace("1", "")
    if not stripped:
        return [], False

    fuzzy_rows = db.execute(
        text(
            """
            SELECT DISTINCT pb.product_id
            FROM product_barcodes pb
            JOIN products p ON p.id = pb.product_id
            WHERE p.is_active = TRUE
              AND replace(pb.barcode, '1', '') = :stripped
            """
        ),
        {"stripped": stripped},
    ).scalars().all()

    return list(fuzzy_rows), bool(fuzzy_rows)


def resolve_product(db: Session, barcode: str) -> Product | None:
    """Return the single best-matching active product for a barcode, or None."""
    product_ids, _ = resolve_product_ids(db, barcode)
    if not product_ids:
        return None

    return db.execute(
        select(Product)
        .options(joinedload(Product.brand), joinedload(Product.category))
        .where(Product.id == product_ids[0], Product.is_active.is_(True))
        .order_by(Product.id)
    ).scalars().first()
