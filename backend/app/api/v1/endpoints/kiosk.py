"""
Kiosk API — lightweight endpoints for Raspberry Pi display client.
Pi polls /kiosk/scan/{barcode} and gets back what video to play.
No business logic runs on the Pi; it's stateless.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product, ProductBarcode
from app.models.media import ProductVideo
from app.models.pricing import ProductPrice, PriceType

router = APIRouter()


@router.get("/scan/{barcode}")
def scan_for_display(barcode: str, db: Session = Depends(get_db)):
    """
    Given a barcode, return product info + video URL for kiosk display.
    If multiple products map to the barcode, returns all (Pi can cycle through them).
    """
    barcode_rows = db.query(ProductBarcode).filter(ProductBarcode.barcode == barcode).all()
    if not barcode_rows:
        raise HTTPException(status_code=404, detail="Unknown barcode")

    results = []
    for br in barcode_rows:
        product = db.query(Product).filter(Product.id == br.product_id).first()
        if not product or not product.is_active:
            continue

        videos = (
            db.query(ProductVideo)
            .filter(ProductVideo.product_id == product.id, ProductVideo.is_primary == True)
            .all()
        )
        retail_price = (
            db.query(ProductPrice)
            .join(PriceType)
            .filter(
                ProductPrice.product_id == product.id,
                PriceType.code == "RETAIL",
                ProductPrice.is_active == True,
            )
            .first()
        )

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
