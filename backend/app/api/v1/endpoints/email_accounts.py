from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.email_crypto import encrypt_email_password
from app.db.session import get_db
from app.models.document import StoreDocument
from app.models.email_account import EmailAccount
from app.worker.tasks.email_sync import sync_email_account

router = APIRouter()

DEFAULT_KEYWORDS = "invoice,order,price list,catalog,fireworks,shipment"


class EmailAccountCreate(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    email_address: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    boss_email_filter: str | None = Field(default=None, max_length=255)
    keyword_filter: str = Field(default=DEFAULT_KEYWORDS, max_length=500)
    is_active: bool = True


class EmailAccountUpdate(BaseModel):
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    email_address: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1)
    boss_email_filter: str | None = Field(default=None, max_length=255)
    keyword_filter: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _serialize_account(account: EmailAccount) -> dict:
    return {
        "id": account.id,
        "host": account.host,
        "port": account.port,
        "email_address": account.email_address,
        "boss_email_filter": account.boss_email_filter,
        "keyword_filter": account.keyword_filter,
        "last_synced_at": account.last_synced_at,
        "is_active": account.is_active,
        "created_at": account.created_at,
    }


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


@router.get("/")
def list_email_accounts(db: Session = Depends(get_db)):
    result = db.execute(select(EmailAccount).order_by(EmailAccount.created_at.desc(), EmailAccount.id.desc()))
    return [_serialize_account(account) for account in result.scalars()]


@router.post("/")
def create_email_account(payload: EmailAccountCreate, db: Session = Depends(get_db)):
    account = EmailAccount(
        host=payload.host.strip(),
        port=payload.port,
        email_address=payload.email_address.strip(),
        encrypted_password=encrypt_email_password(payload.password),
        boss_email_filter=_clean_optional(payload.boss_email_filter),
        keyword_filter=payload.keyword_filter.strip() or DEFAULT_KEYWORDS,
        is_active=payload.is_active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.put("/{account_id}")
def update_email_account(account_id: int, payload: EmailAccountUpdate, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "host" in update_data and update_data["host"] is not None:
        account.host = update_data["host"].strip()
    if "port" in update_data and update_data["port"] is not None:
        account.port = update_data["port"]
    if "email_address" in update_data and update_data["email_address"] is not None:
        account.email_address = update_data["email_address"].strip()
    if "password" in update_data and update_data["password"]:
        account.encrypted_password = encrypt_email_password(update_data["password"])
    if "boss_email_filter" in update_data:
        account.boss_email_filter = _clean_optional(update_data["boss_email_filter"])
    if "keyword_filter" in update_data and update_data["keyword_filter"] is not None:
        account.keyword_filter = update_data["keyword_filter"].strip() or DEFAULT_KEYWORDS
    if "is_active" in update_data and update_data["is_active"] is not None:
        account.is_active = update_data["is_active"]

    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.delete("/{account_id}")
def delete_email_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")
    db.delete(account)
    db.commit()
    return Response(status_code=204)


@router.post("/{account_id}/sync-now")
def sync_now(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")
    task = sync_email_account.delay(account_id)
    return {"task_id": task.id, "queued_at": datetime.utcnow()}


@router.get("/{account_id}/sync-log")
def sync_log(account_id: int, limit: int = 25, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")

    result = db.execute(
        select(StoreDocument)
        .where(StoreDocument.source == "email")
        .where(StoreDocument.notes.like(f"%account={account_id} %"))
        .order_by(StoreDocument.uploaded_at.desc(), StoreDocument.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [_serialize_document(document) for document in result.scalars()]
