from __future__ import annotations

import email
import imaplib
import logging
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings
from app.core.email_crypto import decrypt_email_password
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".xls", ".xlsx", ".csv"}
EMAIL_IMPORT_DIR = Path("documents") / "imports" / "email"


def _db_url() -> str:
    return settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "attachment"


def _decode_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for raw, charset in decode_header(value):
        if isinstance(raw, bytes):
            parts.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts)


def _message_datetime(message: Message) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(message.get("Date"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _message_id(message: Message) -> str:
    return (message.get("Message-ID") or "").strip()


def _message_text(message: Message) -> str:
    chunks: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if content_type == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        chunks.append(text)
    return "\n".join(chunks)


def _keywords(value: str | None) -> list[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _contains_keyword(subject: str, body: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = f"{subject}\n{body}".lower()
    return any(keyword in haystack for keyword in keywords)


def _detect_category(filename: str, subject: str) -> str:
    haystack = f"{filename} {subject}".lower()
    if "invoice" in haystack:
        return "Invoices"
    if "price" in haystack or "pricelist" in haystack or "price_list" in haystack:
        return "Price Lists"
    if "sales order" in haystack or "sale order" in haystack or "order" in haystack:
        return "Sale Orders"
    if "catalog" in haystack or "catalogue" in haystack:
        return "Catalogs"
    return "Other"


def _attachment_parts(message: Message) -> list[tuple[str, bytes]]:
    attachments: list[tuple[str, bytes]] = []
    for part in message.walk():
        filename = _decode_value(part.get_filename())
        if not filename:
            continue
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        attachments.append((filename, payload))
    return attachments


def _unique_path(directory: Path, filename: str) -> Path:
    safe_name = _safe_filename(Path(filename).stem)
    suffix = Path(filename).suffix.lower()
    candidate = directory / f"{safe_name}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{safe_name}_{counter}{suffix}"
        counter += 1
    return candidate


def _imap_since(last_synced_at: datetime | None) -> datetime:
    return last_synced_at or (datetime.utcnow() - timedelta(days=30))


def _search_criteria(account: dict, since: datetime) -> list[str]:
    criteria = ["SINCE", since.strftime("%d-%b-%Y")]
    boss_filter = account.get("boss_email_filter")
    if boss_filter:
        criteria.extend(["FROM", f'"{boss_filter}"'])
    return criteria


def _fetch_message(client: imaplib.IMAP4, uid: bytes) -> Message | None:
    status, payload = client.fetch(uid, "(RFC822)")
    if status != "OK":
        return None
    for item in payload:
        if isinstance(item, tuple):
            return email.message_from_bytes(item[1])
    return None


def _document_exists(cur, message_id: str, original_filename: str) -> bool:
    if not message_id:
        return False
    cur.execute(
        """
        SELECT 1
        FROM store_documents
        WHERE source = 'email'
          AND notes LIKE %s
          AND notes LIKE %s
        LIMIT 1
        """,
        (f"%message_id={message_id}%", f"%filename={original_filename}%"),
    )
    return cur.fetchone() is not None


def _insert_document(cur, account: dict, message: Message, subject: str, filename: str, stored_path: Path, relative_path: Path) -> None:
    message_id = _message_id(message)
    category = _detect_category(filename, subject)
    mime_type = mimetypes.guess_type(stored_path.name)[0]
    notes = (
        f"email-import account={account['id']} "
        f"message_id={message_id or 'unknown'} "
        f"filename={filename} "
        f"subject={subject[:180]}"
    )
    cur.execute(
        """
        INSERT INTO store_documents
            (name, category, file_path, file_size, mime_type, notes, source, uploaded_at)
        VALUES (%s, %s, %s, %s, %s, %s, 'email', %s)
        """,
        (
            Path(filename).stem[:255],
            category,
            relative_path.as_posix(),
            stored_path.stat().st_size,
            mime_type,
            notes,
            datetime.utcnow(),
        ),
    )


def _sync_account(conn, account: dict) -> dict:
    imported = 0
    skipped = 0
    since = _imap_since(account.get("last_synced_at"))
    keywords = _keywords(account.get("keyword_filter"))
    media_root = Path(settings.MEDIA_ROOT)
    absolute_dir = media_root / EMAIL_IMPORT_DIR
    absolute_dir.mkdir(parents=True, exist_ok=True)

    client_cls = imaplib.IMAP4_SSL if account["port"] == 993 else imaplib.IMAP4
    client = client_cls(account["host"], account["port"])
    try:
        client.login(account["email_address"], decrypt_email_password(account["encrypted_password"]))
        client.select("INBOX")
        status, data = client.search(None, *_search_criteria(account, since))
        if status != "OK":
            raise RuntimeError(f"IMAP search failed for account {account['id']}")

        for uid in data[0].split():
            message = _fetch_message(client, uid)
            if message is None:
                skipped += 1
                continue

            message_dt = _message_datetime(message)
            if account.get("last_synced_at") and message_dt and message_dt <= account["last_synced_at"]:
                skipped += 1
                continue

            subject = _decode_value(message.get("Subject"))
            body = _message_text(message)
            if not _contains_keyword(subject, body, keywords):
                skipped += 1
                continue

            attachments = _attachment_parts(message)
            if not attachments:
                skipped += 1
                continue

            with conn.cursor() as cur:
                for filename, payload in attachments:
                    if _document_exists(cur, _message_id(message), filename):
                        skipped += 1
                        continue
                    stored_path = _unique_path(absolute_dir, filename)
                    stored_path.write_bytes(payload)
                    relative_path = EMAIL_IMPORT_DIR / stored_path.name
                    _insert_document(cur, account, message, subject, filename, stored_path, relative_path)
                    imported += 1

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_accounts SET last_synced_at = %s WHERE id = %s",
                (datetime.utcnow(), account["id"]),
            )
        conn.commit()
        return {"account_id": account["id"], "imported": imported, "skipped": skipped}
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _load_accounts(conn, account_id: int | None = None) -> list[dict]:
    where = "WHERE is_active = true"
    params: tuple = ()
    if account_id is not None:
        where = "WHERE id = %s"
        params = (account_id,)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, host, port, email_address, encrypted_password, boss_email_filter,
                   keyword_filter, last_synced_at, is_active
            FROM email_accounts
            {where}
            ORDER BY id
            """,
            params,
        )
        return list(cur.fetchall())


@celery_app.task(name="app.worker.tasks.email_sync.sync_email_accounts")
def sync_email_accounts() -> dict:
    conn = psycopg.connect(_db_url(), autocommit=False)
    results = []
    try:
        for account in _load_accounts(conn):
            try:
                results.append(_sync_account(conn, account))
            except Exception as exc:
                log.exception("Email sync failed for account %s", account["id"])
                results.append({"account_id": account["id"], "error": str(exc)})
        return {"results": results}
    finally:
        conn.close()


@celery_app.task(name="app.worker.tasks.email_sync.sync_email_account")
def sync_email_account(account_id: int) -> dict:
    conn = psycopg.connect(_db_url(), autocommit=False)
    try:
        accounts = _load_accounts(conn, account_id)
        if not accounts:
            return {"account_id": account_id, "error": "Email account not found"}
        return _sync_account(conn, accounts[0])
    finally:
        conn.close()
