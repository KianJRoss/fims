"""Payment-terminal endpoints (Dejavoo SPIn).

``GET /payments/terminal/status`` powers the UI's optional behavior: the
"Charge on terminal" affordance only appears when a terminal is actually present;
otherwise checkout falls back to today's manual card entry.

``POST /payments/terminal/sale`` is wired but deliberately returns 503 until the
SPIn SDK + Auth Key are in place, so no card can be run before the protocol is
implemented and tested.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.payment_terminal import (
    TerminalNotConfigured,
    run_sale,
    terminal_status,
)

router = APIRouter()


@router.get("/terminal/status")
def get_terminal_status():
    return asdict(terminal_status())


class TerminalSalePayload(BaseModel):
    amount: float
    reference: str | None = None


@router.post("/terminal/sale")
def terminal_sale(payload: TerminalSalePayload):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    try:
        return run_sale(Decimal(str(payload.amount)), reference=payload.reference)
    except TerminalNotConfigured as exc:
        # 503: terminal not available / SPIn not wired -> client falls back to manual.
        raise HTTPException(status_code=503, detail=str(exc))
