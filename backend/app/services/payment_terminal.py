"""Dejavoo (Castles) payment-terminal integration -- detection + (stubbed) SPIn.

Design goal: this is *optional and graceful*. When no terminal is configured or
present, ``terminal_status()`` reports ``available=False`` and ``run_sale()``
raises ``TerminalNotConfigured`` -- callers fall back to today's manual card
entry, so checkout behaves exactly as before.

Transport is abstracted so we can drive the terminal over USB serial (what is
physically connected now) or over the network (SPIn HTTP) later without changing
callers. The live transaction is intentionally NOT implemented yet: it requires
Dejavoo's SPIn SDK + the terminal's Auth Key / Register ID (requested from the
processor). Until that lands we never write to the terminal, so we cannot
accidentally start or lock a card transaction.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Dejavoo Z-series terminals enumerate as Castles Technology USB CDC serial.
DEJAVOO_VID = 0x0CA6
DEJAVOO_PID = 0xA050


class TerminalNotConfigured(Exception):
    """Raised when a card cannot be driven on the terminal; caller should fall back."""


@dataclass
class TerminalInfo:
    available: bool
    transport: str  # "serial" | "network" | "disabled"
    port: Optional[str] = None
    description: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None
    detail: Optional[str] = None  # human note / reason it is unavailable


def _detect_serial_port() -> Optional[dict]:
    """First attached Dejavoo terminal (or an explicit override port). Never raises."""
    try:
        from serial.tools import list_ports
    except Exception as exc:  # pyserial not installed -> treat as no terminal
        logger.debug("pyserial unavailable, cannot detect serial terminal: %s", exc)
        return None

    vid = settings.PAYMENT_TERMINAL_VID or DEJAVOO_VID
    pid = settings.PAYMENT_TERMINAL_PID or DEJAVOO_PID
    want_port = (settings.PAYMENT_TERMINAL_PORT or "").strip().upper()

    try:
        ports = list(list_ports.comports())
    except Exception as exc:
        logger.warning("Serial port enumeration failed: %s", exc)
        return None

    for p in ports:
        if want_port and p.device.upper() == want_port:
            return {"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid}
    for p in ports:
        if p.vid == vid and p.pid == pid:
            return {"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid}
    return None


def _network_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def terminal_status() -> TerminalInfo:
    """Report whether the payment terminal is configured and present. Never raises."""
    if not settings.PAYMENT_TERMINAL_ENABLED:
        return TerminalInfo(False, "disabled", detail="PAYMENT_TERMINAL_ENABLED is false")

    transport = (settings.PAYMENT_TERMINAL_TRANSPORT or "serial").lower()

    if transport == "serial":
        found = _detect_serial_port()
        if found:
            return TerminalInfo(True, "serial", **found)
        return TerminalInfo(False, "serial", detail="No Dejavoo terminal on any serial port")

    if transport == "network":
        host = (settings.PAYMENT_TERMINAL_HOST or "").strip()
        if not host:
            return TerminalInfo(False, "network", detail="PAYMENT_TERMINAL_HOST not set")
        net_port = settings.PAYMENT_TERMINAL_NET_PORT
        ok = _network_reachable(host, net_port)
        return TerminalInfo(
            ok, "network", port=f"{host}:{net_port}",
            detail=None if ok else "SPIn host not reachable",
        )

    return TerminalInfo(False, transport, detail=f"Unknown transport '{transport}'")


def run_sale(amount: Decimal, *, reference: str | None = None) -> dict:
    """Drive the terminal for a card sale.

    NOT IMPLEMENTED yet -- pending Dejavoo SPIn SDK + Auth Key/Register ID. Raises
    so the caller falls back to manual card entry. Once SPIn is wired this returns
    a dict like ``{"approved": True, "card_last4": "1234", "card_type": "VISA",
    "auth_code": "...", "reference": "..."}``.
    """
    status = terminal_status()
    if not status.available:
        raise TerminalNotConfigured(status.detail or "Payment terminal unavailable")
    raise TerminalNotConfigured(
        "SPIn transaction support is not wired yet (awaiting Dejavoo SDK + Auth Key). "
        "Run the card manually and enter the method/last-4 as usual."
    )
