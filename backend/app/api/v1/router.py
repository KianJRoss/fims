from fastapi import APIRouter

from app.api.v1.endpoints import (
    products,
    barcodes,
    pricing,
    suppliers,
    imports,
    sales,
    deals,
    inventory,
    media,
    users,
    reports,
    kiosk,
    videos,
    documents,
)
from app.api.v1.endpoints.brands import brands_router, importers_router, manufacturers_router

api_router = APIRouter()

api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(barcodes.router, prefix="/barcodes", tags=["Barcodes"])
api_router.include_router(pricing.router, prefix="/pricing", tags=["Pricing"])
api_router.include_router(brands_router, prefix="/brands", tags=["Brands"])
api_router.include_router(importers_router, prefix="/importers", tags=["Importers"])
api_router.include_router(manufacturers_router, prefix="/manufacturers", tags=["Manufacturers"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["Suppliers"])
api_router.include_router(imports.router, prefix="/imports", tags=["Import Pipeline"])
api_router.include_router(sales.router, prefix="/sales", tags=["Sales"])
api_router.include_router(deals.router, prefix="/deals", tags=["Deals"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["Inventory"])
api_router.include_router(media.router, prefix="/media", tags=["Media"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(kiosk.router, prefix="/kiosk", tags=["Kiosk (Pi)"])
api_router.include_router(videos.router, prefix="/videos", tags=["Videos"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
