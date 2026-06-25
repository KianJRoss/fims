from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.email_crypto import encrypt_secret
from app.db.session import get_db
from app.models.monitoring import AiMonitorConfig
from app.services import ai_monitor
from app.worker.tasks.monitoring import analyze_and_notify

router = APIRouter()


class MonitoringConfigUpdate(BaseModel):
    enabled: bool
    backend_type: Literal["api_key", "cli"]
    provider: Literal["anthropic", "claude"]
    api_key: str | None = None


class MonitoringAlertRequest(BaseModel):
    subject: str = Field(min_length=1)
    detail: str = Field(min_length=1)


def _default_config() -> dict:
    return {
        "enabled": False,
        "backend_type": "api_key",
        "provider": "anthropic",
        "has_api_key": False,
        "last_test_status": None,
        "last_test_message": None,
    }


def _serialize_config(config: AiMonitorConfig) -> dict:
    return {
        "enabled": config.enabled,
        "backend_type": config.backend_type,
        "provider": config.provider,
        "has_api_key": bool(config.encrypted_api_key),
        "last_test_status": config.last_test_status,
        "last_test_message": config.last_test_message,
    }


def _load_config(db: Session, create: bool = False) -> AiMonitorConfig | None:
    config = db.execute(select(AiMonitorConfig).order_by(AiMonitorConfig.id.asc()).limit(1)).scalars().first()
    if config is None and create:
        config = AiMonitorConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    config = _load_config(db)
    return _serialize_config(config) if config else _default_config()


@router.put("/config")
def update_config(payload: MonitoringConfigUpdate, db: Session = Depends(get_db)):
    config = _load_config(db, create=True)
    if config is None:
        raise HTTPException(status_code=500, detail="Unable to load AI monitoring config")

    config.enabled = payload.enabled
    config.backend_type = payload.backend_type
    config.provider = payload.provider
    if payload.backend_type == "api_key" and payload.provider != "anthropic":
        raise HTTPException(status_code=400, detail="API key mode requires Anthropic")
    if payload.backend_type == "cli" and payload.provider != "claude":
        raise HTTPException(status_code=400, detail="CLI mode requires Claude")
    api_key = (payload.api_key or "").strip()
    if api_key:
        config.encrypted_api_key = encrypt_secret(api_key)

    db.commit()
    db.refresh(config)
    return _serialize_config(config)


@router.post("/test")
def test_config(db: Session = Depends(get_db)):
    config = _load_config(db, create=True)
    if config is None:
        raise HTTPException(status_code=500, detail="Unable to load AI monitoring config")

    success, message = ai_monitor.test_backend(config)
    config.last_test_status = "ok" if success else "error"
    config.last_test_message = message
    db.commit()
    db.refresh(config)
    return {"success": success, "message": message}


@router.post("/alert")
def queue_alert(payload: MonitoringAlertRequest):
    analyze_and_notify.delay(payload.subject, payload.detail)
    return {"queued": True}
