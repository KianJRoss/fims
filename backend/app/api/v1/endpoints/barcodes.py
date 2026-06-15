from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

from barcode import Code128
from barcode.writer import ImageWriter
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pricing import PriceType, ProductPrice
from app.models.product import Product, ProductBarcode

router = APIRouter()

TEMPLATES: dict[str, dict[str, int]] = {
    "avery5160": {
        "cols": 3,
        "rows": 10,
        "label_w": 189,
        "label_h": 72,
        "margin_left": 13,
        "margin_top": 36,
        "gap_x": 0,
        "gap_y": 0,
    },
    "avery5163": {
        "cols": 2,
        "rows": 5,
        "label_w": 288,
        "label_h": 144,
        "margin_left": 18,
        "margin_top": 36,
        "gap_x": 0,
        "gap_y": 0,
    },
    "avery5167": {
        "cols": 4,
        "rows": 20,
        "label_w": 126,
        "label_h": 36,
        "margin_left": 13,
        "margin_top": 36,
        "gap_x": 0,
        "gap_y": 0,
    },
}

LABEL_SIZES: dict[str, dict[str, int]] = {
    "small": {"label_w": 144, "label_h": 72, "cols": 2, "rows": 5},
    "medium": {"label_w": 216, "label_h": 144, "cols": 1, "rows": 1},
    "large": {"label_w": 288, "label_h": 216, "cols": 1, "rows": 1},
}


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_product_ids(product_ids: str) -> list[str]:
    ids = [part.strip() for part in product_ids.split(",") if part.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="product_ids is required")
    return ids


def _truncate_text(text: str, font_name: str, font_size: float, max_width: float) -> str:
    if stringWidth(text, font_name, font_size) <= max_width:
        return text

    ellipsis = "..."
    while text and stringWidth(text + ellipsis, font_name, font_size) > max_width:
        text = text[:-1]
    return f"{text}{ellipsis}" if text else ellipsis


@lru_cache(maxsize=1024)
def _barcode_png_bytes(value: str) -> bytes:
    writer = ImageWriter()
    barcode = Code128(value, writer=writer)
    buffer = io.BytesIO()
    barcode.write(
        buffer,
        {
            "write_text": False,
            "quiet_zone": 2.0,
            "module_width": 0.25,
            "module_height": 12.0,
            "font_size": 8,
            "text_distance": 1,
            "dpi": 300,
        },
    )
    return buffer.getvalue()


def _barcode_png_resized(value: str, width_px: int) -> bytes:
    source = Image.open(io.BytesIO(_barcode_png_bytes(value))).convert("RGB")
    if width_px <= 0:
        width_px = 300
    ratio = width_px / float(source.width)
    resized = source.resize((width_px, max(1, int(source.height * ratio))), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    resized.save(out, format="PNG")
    return out.getvalue()


def _fetch_products(db: Session, product_ids: list[str]) -> list[dict[str, Any]]:
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    product_map = {product.id: product for product in products}

    barcode_rows = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.product_id.in_(product_ids))
        .order_by(ProductBarcode.product_id, ProductBarcode.is_primary.desc(), ProductBarcode.id.asc())
        .all()
    )
    barcode_map: dict[str, str] = {}
    for row in barcode_rows:
        barcode_map.setdefault(row.product_id, row.barcode)
        if row.is_primary:
            barcode_map[row.product_id] = row.barcode

    retail_prices = (
        db.query(ProductPrice.product_id, ProductPrice.amount)
        .join(PriceType, PriceType.id == ProductPrice.price_type_id)
        .filter(
            ProductPrice.product_id.in_(product_ids),
            ProductPrice.is_active == True,  # noqa: E712
            PriceType.code == "RETAIL",
        )
        .order_by(ProductPrice.product_id, ProductPrice.effective_from.desc())
        .all()
    )
    price_map: dict[str, float] = {}
    for product_id, amount in retail_prices:
        price_map.setdefault(product_id, float(amount))

    ordered: list[dict[str, Any]] = []
    for product_id in product_ids:
        product = product_map.get(product_id)
        if not product or not product.is_active:
            continue
        barcode_value = _normalize_value(barcode_map.get(product_id) or product.item_number or product.id)
        ordered.append(
            {
                "id": product.id,
                "name": product.name,
                "item_number": product.item_number,
                "barcode": barcode_value,
                "price": price_map.get(product_id),
            }
        )
    if not ordered:
        raise HTTPException(status_code=404, detail="No matching products found")
    return ordered


def _draw_label(
    pdf: canvas.Canvas,
    left: float,
    bottom: float,
    width: float,
    height: float,
    product: dict[str, Any],
    barcode_value: str,
    show_name: bool,
    show_price: bool,
) -> None:
    padding = 6
    top_space = 14 if show_name else 0
    bottom_space = 12 if show_price else 0

    name = product["name"]
    price = product.get("price")
    name_font = "Helvetica-Bold"
    price_font = "Helvetica"

    if show_name:
        pdf.setFont(name_font, 8)
        text = _truncate_text(name, name_font, 8, width - padding * 2)
        pdf.drawCentredString(left + width / 2, bottom + height - 11, text)

    if show_price and price is not None:
        pdf.setFont(price_font, 7.5)
        pdf.drawCentredString(left + width / 2, bottom + 5, f"${price:,.2f}")

    barcode_png = _barcode_png_bytes(barcode_value)
    image = ImageReader(io.BytesIO(barcode_png))
    barcode_w = width - padding * 2
    barcode_h = height - padding * 2 - top_space - bottom_space

    if barcode_h <= 0:
        barcode_h = height - padding * 2

    img_w = image.getSize()[0]
    img_h = image.getSize()[1]
    scale = min(barcode_w / img_w, barcode_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    draw_x = left + (width - draw_w) / 2
    draw_y = bottom + (height - draw_h) / 2 + (0 if show_name else 2) - (6 if show_price else 0)
    pdf.drawImage(image, draw_x, draw_y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")


def _build_sheet_pdf(
    products: list[dict[str, Any]],
    template_name: str,
    copies: int,
    show_name: bool,
    show_price: bool,
) -> bytes:
    template = TEMPLATES[template_name]
    page_w, page_h = letter
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    items = []
    for product in products:
        for _ in range(copies):
            items.append(product)

    capacity = template["cols"] * template["rows"]
    label_w = template["label_w"]
    label_h = template["label_h"]

    for index, product in enumerate(items):
        if index and index % capacity == 0:
            pdf.showPage()

        slot = index % capacity
        col = slot % template["cols"]
        row = slot // template["cols"]
        left = template["margin_left"] + col * (label_w + template["gap_x"])
        bottom = page_h - template["margin_top"] - label_h - row * (label_h + template["gap_y"])
        _draw_label(pdf, left, bottom, label_w, label_h, product, product["barcode"], show_name, show_price)

    pdf.save()
    return buffer.getvalue()


def _build_label_pdf(
    product: dict[str, Any],
    size: str,
    copies: int,
    show_name: bool,
    show_price: bool,
) -> bytes:
    layout = LABEL_SIZES[size]
    page_w, page_h = letter
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    if size == "small":
        cols, rows = 2, 5
        cell_w = page_w / cols
        cell_h = page_h / rows
        for index in range(copies):
            if index and index % (cols * rows) == 0:
                pdf.showPage()
            slot = index % (cols * rows)
            col = slot % cols
            row = slot // cols
            left = col * cell_w + (cell_w - layout["label_w"]) / 2
            bottom = page_h - (row + 1) * cell_h + (cell_h - layout["label_h"]) / 2
            _draw_label(pdf, left, bottom, layout["label_w"], layout["label_h"], product, product["barcode"], show_name, show_price)
    else:
        for index in range(copies):
            if index:
                pdf.showPage()
            left = (page_w - layout["label_w"]) / 2
            bottom = (page_h - layout["label_h"]) / 2
            _draw_label(pdf, left, bottom, layout["label_w"], layout["label_h"], product, product["barcode"], show_name, show_price)

    pdf.save()
    return buffer.getvalue()


def _get_product_by_id(db: Session, product_id: str) -> dict[str, Any]:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found")

    barcode_row = (
        db.query(ProductBarcode)
        .filter(ProductBarcode.product_id == product.id)
        .order_by(ProductBarcode.is_primary.desc(), ProductBarcode.id.asc())
        .first()
    )

    retail_price = (
        db.query(ProductPrice.amount)
        .join(PriceType, PriceType.id == ProductPrice.price_type_id)
        .filter(
            ProductPrice.product_id == product.id,
            ProductPrice.is_active == True,  # noqa: E712
            PriceType.code == "RETAIL",
        )
        .order_by(ProductPrice.effective_from.desc())
        .first()
    )

    return {
        "id": product.id,
        "name": product.name,
        "item_number": product.item_number,
        "barcode": _normalize_value((barcode_row.barcode if barcode_row else None) or product.item_number or product.id),
        "price": float(retail_price[0]) if retail_price else None,
    }


@router.get("/sheet")
def sheet_pdf(
    product_ids: str = Query(..., description="Comma-separated product UUIDs"),
    copies: int = Query(1, ge=1, le=10),
    template: str = Query("avery5160", pattern="^(avery5160|avery5163|avery5167)$"),
    show_name: bool = Query(True),
    show_price: bool = Query(False),
    db: Session = Depends(get_db),
):
    ids = _parse_product_ids(product_ids)
    products = _fetch_products(db, ids)
    pdf_bytes = _build_sheet_pdf(products, template, copies, show_name, show_price)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=barcodes_sheet.pdf"},
    )


@router.get("/label/{product_id}")
def label_pdf(
    product_id: str,
    size: str = Query("medium", pattern="^(small|medium|large)$"),
    copies: int = Query(1, ge=1, le=100),
    show_name: bool = Query(True),
    show_price: bool = Query(False),
    db: Session = Depends(get_db),
):
    product = _get_product_by_id(db, product_id)
    pdf_bytes = _build_label_pdf(product, size, copies, show_name, show_price)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="barcode_label_{product_id}.pdf"'},
    )


@router.get("/preview/{product_id}")
def preview_png(product_id: str, width: int = Query(300, ge=50, le=2000), db: Session = Depends(get_db)):
    product = _get_product_by_id(db, product_id)
    png_bytes = _barcode_png_resized(product["barcode"], width)
    return Response(content=png_bytes, media_type="image/png")
