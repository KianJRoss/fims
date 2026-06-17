from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.supplier import Supplier, SupplierProduct
from app.models.product import Product

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str
    code: str | None = None
    contact_info: dict | None = None
    notes: str | None = None


class SupplierPatch(BaseModel):
    name: str | None = None
    code: str | None = None
    contact_info: dict | None = None
    notes: str | None = None


class SupplierProductPatch(BaseModel):
    product_id: str | None = None


# ─── Serializers ──────────────────────────────────────────────────────────

def _serialize_supplier(supplier: Supplier, product_count: int = 0, unmatched_count: int = 0) -> dict:
    return {
        "id": supplier.id,
        "name": supplier.name,
        "code": supplier.code,
        "contact_info": supplier.contact_info,
        "notes": supplier.notes,
        "product_count": product_count,
        "unmatched_count": unmatched_count,
    }


def _serialize_supplier_product(sp: SupplierProduct) -> dict:
    return {
        "id": sp.id,
        "supplier_id": sp.supplier_id,
        "product_id": sp.product_id,
        "supplier_item_number": sp.supplier_item_number,
        "supplier_product_name": sp.supplier_product_name,
        "supplier_barcode": sp.supplier_barcode,
        "supplier_cost": float(sp.supplier_cost) if sp.supplier_cost is not None else None,
        "last_seen": sp.last_seen,
        "raw_data": sp.raw_data,
        "product_name": sp.product.name if sp.product else None,
        "product_item_number": sp.product.item_number if sp.product else None,
    }


# ─── Routes ───────────────────────────────────────────────────────────────

@router.get("/")
def list_suppliers(db: Session = Depends(get_db)):
    product_count = (
        select(func.count(SupplierProduct.id))
        .where(SupplierProduct.supplier_id == Supplier.id)
        .correlate(Supplier)
        .scalar_subquery()
    )
    unmatched_count = (
        select(func.count(SupplierProduct.id))
        .where(SupplierProduct.supplier_id == Supplier.id, SupplierProduct.product_id.is_(None))
        .correlate(Supplier)
        .scalar_subquery()
    )
    stmt = (
        select(Supplier, product_count.label("product_count"), unmatched_count.label("unmatched_count"))
        .order_by(func.lower(Supplier.name))
    )
    rows = db.execute(stmt).all()
    return [
        _serialize_supplier(supplier, int(product_count_value or 0), int(unmatched_count_value or 0))
        for supplier, product_count_value, unmatched_count_value in rows
    ]


@router.post("/")
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    supplier = Supplier(
        name=payload.name,
        code=payload.code,
        contact_info=payload.contact_info,
        notes=payload.notes,
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return _serialize_supplier(supplier)


@router.get("/{supplier_id}")
def get_supplier(
    supplier_id: int,
    unmatched_only: bool = False,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    query = db.query(SupplierProduct).filter(SupplierProduct.supplier_id == supplier_id)
    if unmatched_only:
        query = query.filter(SupplierProduct.product_id.is_(None))

    total = query.count()
    items = (
        query.order_by(SupplierProduct.last_seen.desc(), SupplierProduct.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    product_count = db.query(func.count(SupplierProduct.id)).filter(
        SupplierProduct.supplier_id == supplier_id
    ).scalar()
    unmatched_count = db.query(func.count(SupplierProduct.id)).filter(
        SupplierProduct.supplier_id == supplier_id, SupplierProduct.product_id.is_(None)
    ).scalar()

    return {
        **_serialize_supplier(supplier, int(product_count or 0), int(unmatched_count or 0)),
        "products": {
            "items": [_serialize_supplier_product(sp) for sp in items],
            "total": total,
            "skip": skip,
            "limit": limit,
        },
    }


@router.patch("/{supplier_id}")
def update_supplier(supplier_id: int, payload: SupplierPatch, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(supplier, key, value)

    db.commit()
    db.refresh(supplier)
    return _serialize_supplier(supplier)


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    has_products = db.query(SupplierProduct.id).filter(
        SupplierProduct.supplier_id == supplier_id
    ).first() is not None
    if has_products:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete supplier with linked supplier products. Remove or reassign them first.",
        )

    db.delete(supplier)
    db.commit()
    return Response(status_code=204)


@router.patch("/{supplier_id}/products/{supplier_product_id}")
def update_supplier_product_match(
    supplier_id: int,
    supplier_product_id: int,
    payload: SupplierProductPatch,
    db: Session = Depends(get_db),
):
    sp = (
        db.query(SupplierProduct)
        .filter(SupplierProduct.id == supplier_product_id, SupplierProduct.supplier_id == supplier_id)
        .first()
    )
    if not sp:
        raise HTTPException(status_code=404, detail="Supplier product not found")

    if payload.product_id is not None:
        product = db.get(Product, payload.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

    sp.product_id = payload.product_id
    db.commit()
    db.refresh(sp)
    return _serialize_supplier_product(sp)
