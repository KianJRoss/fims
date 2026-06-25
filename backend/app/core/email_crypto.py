from __future__ import annotations

import logging

from cryptography.fernet import Fernet

from app.core.config import settings

log = logging.getLogger(__name__)
_generated_key: bytes | None = None


def _key() -> bytes:
    global _generated_key
    if settings.EMAIL_ENCRYPTION_KEY:
        return settings.EMAIL_ENCRYPTION_KEY.encode("utf-8")
    if _generated_key is None:
        _generated_key = Fernet.generate_key()
        log.warning(
            "EMAIL_ENCRYPTION_KEY is not set; generated a temporary key. "
            "Stored email passwords will not survive process restarts."
        )
    return _generated_key


def encrypt_secret(value: str) -> str:
    return Fernet(_key()).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_value: str) -> str:
    return Fernet(_key()).decrypt(encrypted_value.encode("utf-8")).decode("utf-8")


def encrypt_email_password(password: str) -> str:
    return encrypt_secret(password)


def decrypt_email_password(encrypted_password: str) -> str:
    return decrypt_secret(encrypted_password)
