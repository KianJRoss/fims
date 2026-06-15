"""
Background import pipeline tasks.
1. parse_document — extract rows from PDF/CSV/Excel via pdfplumber/openpyxl
2. run_auto_match — score each row against existing products using priority rules
3. commit_approved_rows — write approved matches to supplier_products table
"""
import logging

from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.worker.tasks.imports.parse_document", bind=True, max_retries=3)
def parse_document(self, import_job_id: int):
    """Parse uploaded file and populate import_rows for human review."""
    from app.db.session import SessionLocal
    from app.models.import_job import ImportJob

    db = SessionLocal()
    try:
        job = db.query(ImportJob).filter(ImportJob.id == import_job_id).first()
        if not job:
            log.error("ImportJob %s not found", import_job_id)
            return

        job.status = "parsing"
        db.commit()

        rows = _parse_file(job.file_path, job.document_type)

        from app.models.import_job import ImportRow
        for idx, raw in enumerate(rows):
            db.add(ImportRow(job_id=job.id, row_index=idx, raw_data=raw))

        job.status = "review"
        db.commit()
        log.info("Parsed %d rows for job %s", len(rows), import_job_id)
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


def _parse_file(file_path: str, document_type: str) -> list[dict]:
    """Route to the right parser based on file extension."""
    import os
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext in (".xlsx", ".xls"):
        return _parse_excel(file_path)
    elif ext == ".csv":
        return _parse_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _parse_pdf(file_path: str) -> list[dict]:
    import pdfplumber
    rows = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                header = [str(h or "").strip() for h in table[0]]
                for row in table[1:]:
                    rows.append(dict(zip(header, [str(c or "").strip() for c in row])))
    return rows


def _parse_excel(file_path: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows_iter)]
    return [dict(zip(header, [str(c or "").strip() for c in row])) for row in rows_iter]


def _parse_csv(file_path: str) -> list[dict]:
    import csv
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@celery_app.task(name="app.worker.tasks.imports.run_auto_match")
def run_auto_match(import_job_id: int):
    """Score each ImportRow against existing products using the priority match rules."""
    # Priority: Internal ID → Item# + Brand → Item# + Supplier → Barcode → Name + Brand → Manual
    from app.db.session import SessionLocal
    from app.models.import_job import ImportRow, ImportJob
    from app.models.product import Product, ProductBarcode

    db = SessionLocal()
    try:
        rows = db.query(ImportRow).filter(
            ImportRow.job_id == import_job_id,
            ImportRow.review_status == "pending",
        ).all()

        for row in rows:
            product_id, confidence, method = _match_row(db, row.raw_data)
            row.matched_product_id = product_id
            row.match_confidence = confidence
            row.match_method = method

        db.commit()
    finally:
        db.close()


def _match_row(db, raw: dict):
    from app.models.product import Product, ProductBarcode
    from app.models.supplier import SupplierProduct

    # 1. Exact internal ID
    if pid := raw.get("fims_id") or raw.get("internal_id"):
        p = db.query(Product).filter(Product.id == pid).first()
        if p:
            return p.id, 1.0, "INTERNAL_ID"

    # 2. Barcode
    if bc := raw.get("barcode") or raw.get("upc"):
        pb = db.query(ProductBarcode).filter(ProductBarcode.barcode == bc).first()
        if pb:
            return pb.product_id, 0.95, "BARCODE"

    # 3. Item number + brand name
    item_num = raw.get("item_number") or raw.get("item#") or raw.get("sku")
    brand = raw.get("brand") or raw.get("manufacturer")
    if item_num and brand:
        from app.models.product import ProductBrand
        brand_row = db.query(ProductBrand).filter(
            ProductBrand.name.ilike(brand)
        ).first()
        if brand_row:
            p = db.query(Product).filter(
                Product.item_number == item_num,
                Product.brand_id == brand_row.id,
            ).first()
            if p:
                return p.id, 0.9, "ITEM_NUM_BRAND"

    return None, 0.0, "MANUAL"
