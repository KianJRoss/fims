from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.brand_hierarchy import BrandImporter, BrandManufacturer, Importer, Manufacturer
from app.models.product import ProductBrand

brands_router = APIRouter()
importers_router = APIRouter()
manufacturers_router = APIRouter()

# Backward-compatible alias used by the existing router wiring.
router = brands_router


def _brand_counts_query():
    importer_count = (
        select(func.count(BrandImporter.id))
        .where(BrandImporter.brand_id == ProductBrand.id)
        .correlate(ProductBrand)
        .scalar_subquery()
    )
    manufacturer_count = (
        select(func.count(BrandManufacturer.id))
        .where(BrandManufacturer.brand_id == ProductBrand.id)
        .correlate(ProductBrand)
        .scalar_subquery()
    )
    return importer_count, manufacturer_count


def _serialize_brand(brand: ProductBrand) -> dict:
    return {
        "id": brand.id,
        "name": brand.name,
        "tier": brand.tier,
        "brand_type": brand.brand_type,
        "website": brand.website,
        "notes": brand.notes,
        "logo_url": brand.logo_url,
    }


@brands_router.get("/")
def list_brands(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    importer_count, manufacturer_count = _brand_counts_query()
    stmt = (
        select(
            ProductBrand,
            importer_count.label("importer_count"),
            manufacturer_count.label("manufacturer_count"),
        )
        .order_by(ProductBrand.name.asc())
        .offset(skip)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "id": brand.id,
            "name": brand.name,
            "tier": brand.tier,
            "brand_type": brand.brand_type,
            "importer_count": int(importer_count_value or 0),
            "manufacturer_count": int(manufacturer_count_value or 0),
        }
        for brand, importer_count_value, manufacturer_count_value in rows
    ]


@importers_router.get("/")
def list_importers(db: Session = Depends(get_db)):
    brand_count = (
        select(func.count(BrandImporter.id))
        .where(BrandImporter.importer_id == Importer.id)
        .correlate(Importer)
        .scalar_subquery()
    )
    importers = db.execute(
        select(Importer, brand_count.label("brand_count")).order_by(Importer.name.asc())
    ).all()
    return [
        {
            "id": importer.id,
            "name": importer.name,
            "short_name": importer.short_name,
            "website": importer.website,
            "hq_state": importer.hq_state,
            "notes": importer.notes,
            "created_at": importer.created_at,
            "brand_count": int(brand_count_value or 0),
        }
        for importer, brand_count_value in importers
    ]


@importers_router.get("/{importer_id}")
def get_importer(importer_id: int, db: Session = Depends(get_db)):
    importer = (
        db.query(Importer)
        .options(selectinload(Importer.brand_links).selectinload(BrandImporter.brand))
        .filter(Importer.id == importer_id)
        .first()
    )
    if not importer:
        raise HTTPException(status_code=404, detail="Importer not found")

    return {
        "id": importer.id,
        "name": importer.name,
        "short_name": importer.short_name,
        "website": importer.website,
        "hq_state": importer.hq_state,
        "notes": importer.notes,
        "created_at": importer.created_at,
        "brands": [
            {
                "id": link.brand.id,
                "name": link.brand.name,
                "tier": link.brand.tier,
                "brand_type": link.brand.brand_type,
                "website": link.brand.website,
                "notes": link.brand.notes,
                "logo_url": link.brand.logo_url,
                "relationship_type": link.relationship_type,
                "relationship_notes": link.notes,
            }
            for link in sorted(importer.brand_links, key=lambda item: item.brand.name.lower())
        ],
    }


@manufacturers_router.get("/")
def list_manufacturers(db: Session = Depends(get_db)):
    brand_count = (
        select(func.count(BrandManufacturer.id))
        .where(BrandManufacturer.manufacturer_id == Manufacturer.id)
        .correlate(Manufacturer)
        .scalar_subquery()
    )
    manufacturers = db.execute(
        select(Manufacturer, brand_count.label("brand_count")).order_by(Manufacturer.name.asc())
    ).all()
    return [
        {
            "id": manufacturer.id,
            "name": manufacturer.name,
            "country": manufacturer.country,
            "website": manufacturer.website,
            "notes": manufacturer.notes,
            "created_at": manufacturer.created_at,
            "brand_count": int(brand_count_value or 0),
        }
        for manufacturer, brand_count_value in manufacturers
    ]


@manufacturers_router.get("/{manufacturer_id}")
def get_manufacturer(manufacturer_id: int, db: Session = Depends(get_db)):
    manufacturer = (
        db.query(Manufacturer)
        .options(selectinload(Manufacturer.brand_links).selectinload(BrandManufacturer.brand))
        .filter(Manufacturer.id == manufacturer_id)
        .first()
    )
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")

    return {
        "id": manufacturer.id,
        "name": manufacturer.name,
        "country": manufacturer.country,
        "website": manufacturer.website,
        "notes": manufacturer.notes,
        "created_at": manufacturer.created_at,
        "brands": [
            {
                "id": link.brand.id,
                "name": link.brand.name,
                "tier": link.brand.tier,
                "brand_type": link.brand.brand_type,
                "website": link.brand.website,
                "notes": link.brand.notes,
                "logo_url": link.brand.logo_url,
                "relationship_notes": link.notes,
            }
            for link in sorted(manufacturer.brand_links, key=lambda item: item.brand.name.lower())
        ],
    }


@brands_router.get("/{brand_id}")
def get_brand(brand_id: int, db: Session = Depends(get_db)):
    brand = (
        db.query(ProductBrand)
        .options(
            selectinload(ProductBrand.importer_links).selectinload(BrandImporter.importer),
            selectinload(ProductBrand.manufacturer_links).selectinload(BrandManufacturer.manufacturer),
        )
        .filter(ProductBrand.id == brand_id)
        .first()
    )
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    return {
        **_serialize_brand(brand),
        "importers": [
            {
                "id": link.importer.id,
                "name": link.importer.name,
                "short_name": link.importer.short_name,
                "website": link.importer.website,
                "hq_state": link.importer.hq_state,
                "notes": link.importer.notes,
                "relationship_type": link.relationship_type,
                "relationship_notes": link.notes,
            }
            for link in sorted(brand.importer_links, key=lambda item: item.importer.name.lower())
        ],
        "manufacturers": [
            {
                "id": link.manufacturer.id,
                "name": link.manufacturer.name,
                "country": link.manufacturer.country,
                "website": link.manufacturer.website,
                "notes": link.manufacturer.notes,
                "relationship_notes": link.notes,
            }
            for link in sorted(brand.manufacturer_links, key=lambda item: item.manufacturer.name.lower())
        ],
    }
