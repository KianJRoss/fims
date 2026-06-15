"""
Kiosk API — lightweight endpoints for Raspberry Pi display client.
Pi polls /kiosk/scan/{barcode} and gets back what video to play.
No business logic runs on the Pi; it's stateless.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.models.media import ProductVideo
from app.models.pricing import ProductPrice, PriceType
from app.api.v1.endpoints._barcode import resolve_product_ids

router = APIRouter()


@router.get("/scan/{barcode}")
def scan_for_display(barcode: str, db: Session = Depends(get_db)):
    """
    Given a barcode, return product info + video URL for kiosk display.
    If multiple products map to the barcode, returns all (Pi can cycle through them).
    """
    product_ids = resolve_product_ids(db, barcode)
    if not product_ids:
        raise HTTPException(status_code=404, detail="Unknown barcode")

    results = []
    for product_id in product_ids:
        product = db.execute(
            select(Product).where(Product.id == product_id, Product.is_active.is_(True))
        ).scalars().first()
        if not product:
            continue

        videos = db.execute(
            select(ProductVideo).where(
                ProductVideo.product_id == product.id,
                ProductVideo.is_primary.is_(True),
            )
        ).scalars().all()

        retail_price = db.execute(
            select(ProductPrice)
            .join(PriceType)
            .where(
                ProductPrice.product_id == product.id,
                PriceType.code == "RETAIL",
                ProductPrice.is_active.is_(True),
            )
        ).scalars().first()

        results.append({
            "product_id": product.id,
            "name": product.name,
            "item_number": product.item_number,
            "retail_price": float(retail_price.amount) if retail_price else None,
            "shot_count": product.shot_count,
            "effects": product.effects,
            "videos": [
                {"url": f"/media/{v.file_path}", "duration": v.duration_seconds}
                for v in videos
            ],
        })

    return {"barcode": barcode, "products": results}
