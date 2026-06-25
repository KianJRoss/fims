from __future__ import annotations

import logging

import httpx
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.monitoring import AiMonitorConfig
from app.services import ai_monitor
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

NTFY_URL = "https://ntfy.sh/fims-kianpotpi-4e7f4b852168"


def _load_config() -> AiMonitorConfig | None:
    db = SessionLocal()
    try:
        statement = select(AiMonitorConfig).order_by(AiMonitorConfig.id.asc()).limit(1)
        return db.execute(statement).scalars().first()
    finally:
        db.close()


def _build_prompt(subject: str, detail: str) -> str:
    return (
        "You are helping monitor FIMS, a small fireworks retail store's backend system "
        "running on a Raspberry Pi.\n"
        "Read the alert summary below and explain in plain English what is likely happening "
        "and what the store owner should do next, if anything.\n"
        "Write 2-3 sentences. Keep it non-technical and practical.\n\n"
        f"Subject: {subject.strip()}\n"
        f"Details:\n{detail.strip()}"
    )


@celery_app.task(name="app.worker.tasks.monitoring.analyze_and_notify")
def analyze_and_notify(subject: str, detail: str) -> None:
    try:
        config = _load_config()
        if config is None or not config.enabled:
            return

        prompt = _build_prompt(subject, detail)
        insight = ai_monitor.analyze(config, prompt).strip()
        if not insight:
            raise RuntimeError("AI monitoring returned an empty response")

        response = httpx.post(
            NTFY_URL,
            content=insight.encode("utf-8"),
            headers={"Title": "FIMS AI Insight"},
            timeout=10.0,
        )
        response.raise_for_status()
    except Exception:
        log.exception("AI monitoring notification failed")
