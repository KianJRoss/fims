from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import StoreDocument

router = APIRouter()
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/app/media")
DOCUMENT_ROOT = "documents"


class DocumentPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    notes: str | None = None
    supplier_name: str | None = None
    doc_date: str | None = None


def _sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "document"


def _serialize_document(document: StoreDocument) -> dict:
    return {
        "id": document.id,
        "name": document.name,
        "category": document.category,
        "file_path": document.file_path,
        "file_size": document.file_size,
        "mime_type": document.mime_type,
        "notes": document.notes,
        "source": document.source,
        "uploaded_at": document.uploaded_at,
        "supplier_name": document.supplier_name,
        "doc_date": document.doc_date,
    }


def _resolve_file_path(relative_path: str) -> str:
    media_root_abs = os.path.abspath(MEDIA_ROOT)
    full_path = os.path.abspath(os.path.normpath(os.path.join(media_root_abs, relative_path)))
    if os.path.commonpath([media_root_abs, full_path]) != media_root_abs:
        raise HTTPException(status_code=400, detail="Invalid document path")
    return full_path


@router.get("/")
def list_documents(category: str | None = None, db: Session = Depends(get_db)):
    query = db.query(StoreDocument)
    if category:
        query = query.filter(StoreDocument.category == category)
    documents = query.order_by(StoreDocument.uploaded_at.desc(), StoreDocument.id.desc()).all()
    return [_serialize_document(document) for document in documents]


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form("Other"),
    supplier_name: str | None = Form(None),
    doc_date: str | None = Form(None),
    notes: str | None = Form(None),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    stored_category = category or "Other"
    safe_category = _sanitize_segment(stored_category)
    safe_filename = _sanitize_segment(Path(file.filename or name).stem)
    suffix = Path(file.filename or name).suffix

    relative_dir = Path(DOCUMENT_ROOT) / safe_category
    absolute_dir = Path(MEDIA_ROOT) / relative_dir
    absolute_dir.mkdir(parents=True, exist_ok=True)

    candidate = absolute_dir / f"{safe_filename}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = absolute_dir / f"{safe_filename}_{counter}{suffix}"
        counter += 1

    content = await file.read()
    candidate.write_bytes(content)

    document = StoreDocument(
        name=name,
        category=stored_category,
        file_path=str((relative_dir / candidate.name).as_posix()),
        file_size=len(content),
        mime_type=file.content_type,
        notes=notes,
        supplier_name=supplier_name,
        doc_date=doc_date,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return _serialize_document(document)


@router.get("/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(StoreDocument).filter(StoreDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    full_path = _resolve_file_path(document.file_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Document file not found")

    return FileResponse(full_path, filename=os.path.basename(full_path))


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(StoreDocument).filter(StoreDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    full_path = _resolve_file_path(document.file_path)
    if os.path.exists(full_path):
        os.remove(full_path)

    db.delete(document)
    db.commit()
    return Response(status_code=204)


@router.patch("/{document_id}")
def update_document(document_id: int, payload: DocumentPatch, db: Session = Depends(get_db)):
    document = db.query(StoreDocument).filter(StoreDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    update_data = payload.model_dump(exclude_unset=True)
    previous_category = document.category
    previous_relative_path = document.file_path

    for key, value in update_data.items():
        setattr(document, key, value)

    if "category" in update_data and update_data["category"] and update_data["category"] != previous_category:
        old_full_path = _resolve_file_path(previous_relative_path)
        new_category = document.category or "Other"
        safe_category = _sanitize_segment(new_category)
        new_relative_dir = Path(DOCUMENT_ROOT) / safe_category
        new_absolute_dir = Path(MEDIA_ROOT) / new_relative_dir
        new_absolute_dir.mkdir(parents=True, exist_ok=True)
        new_absolute_path = new_absolute_dir / os.path.basename(old_full_path)
        shutil.move(old_full_path, new_absolute_path)
        document.file_path = str((new_relative_dir / new_absolute_path.name).as_posix())

    db.commit()
    db.refresh(document)
    return _serialize_document(document)
