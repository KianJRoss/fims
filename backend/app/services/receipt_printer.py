from __future__ import annotations

import logging
import socket
import textwrap
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Literal, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)

CopyType = Literal["customer", "merchant"]

STORE_NAME = "Main Street Fireworks"
PAPER_WIDTH = 42
SOCKET_TIMEOUT_SECONDS = 2.0


def receipt_print_payload(sale) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    """Copy ORM sale data into detached objects safe for background printing."""
    sale_copy = SimpleNamespace(
        id=sale.id,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        grand_total=sale.grand_total,
        payment_method=sale.payment_method,
        card_last4=sale.card_last4,
        created_at=sale.created_at,
        completed_at=sale.completed_at,
    )
    item_copies: list[SimpleNamespace] = []
    for item in sale.items:
        product = getattr(item, "product", None)
        item_copies.append(
            SimpleNamespace(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                line_total=item.line_total,
                product=SimpleNamespace(name=getattr(product, "name", None)),
            )
        )
    return sale_copy, item_copies


def print_receipt(sale, items: Sequence, copy_type: CopyType = "customer") -> None:
    """Print a customer or merchant receipt copy to a network ESC/POS printer."""
    if not settings.RECEIPT_PRINTER_HOST:
        logger.info("Receipt printer host is not configured; skipping %s receipt print", copy_type)
        return

    if copy_type == "merchant" and sale.payment_method != "CARD":
        logger.info("Skipping merchant receipt copy for non-card sale %s", sale.id)
        return

    try:
        payload = build_receipt_bytes(sale, items, copy_type)
        with socket.create_connection(
            (settings.RECEIPT_PRINTER_HOST, settings.RECEIPT_PRINTER_PORT),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as printer:
            printer.settimeout(SOCKET_TIMEOUT_SECONDS)
            printer.sendall(payload)
    except Exception as exc:
        logger.warning(
            "Receipt printer unavailable for sale %s (%s copy): %s",
            getattr(sale, "id", "unknown"),
            copy_type,
            exc,
        )


def build_receipt_bytes(sale, items: Sequence, copy_type: CopyType = "customer") -> bytes:
    lines: list[bytes] = [
        b"\x1b@",  # initialize
        b"\x1ba\x01",  # center align
        b"\x1bE\x01",  # bold on
        _line(STORE_NAME),
        b"\x1bE\x00",  # bold off
        _line("MERCHANT COPY" if copy_type == "merchant" else "CUSTOMER COPY"),
        _line(_receipt_datetime(sale)),
        _line(f"Sale: {sale.id}"),
        _line(""),
        b"\x1ba\x00",  # left align
        _line("-" * PAPER_WIDTH),
        _line(_columns("Qty Item", "Unit", "Total")),
        _line("-" * PAPER_WIDTH),
    ]

    for item in items:
        product = getattr(item, "product", None)
        item_name = getattr(product, "name", None) or getattr(item, "product_id", "Item")
        qty = int(getattr(item, "quantity", 0) or 0)
        unit_price = _money(getattr(item, "unit_price", 0))
        line_total = _money(getattr(item, "line_total", 0))
        discount = _decimal(getattr(item, "discount_amount", 0))

        prefix = f"{qty}x "
        name_width = PAPER_WIDTH - len(prefix)
        name_lines = textwrap.wrap(item_name, width=name_width) or [item_name[:name_width]]
        lines.append(_line(prefix + name_lines[0]))
        for continuation in name_lines[1:]:
            lines.append(_line(" " * len(prefix) + continuation))
        lines.append(_line(_columns("", unit_price, line_total)))
        if discount > Decimal("0"):
            lines.append(_line(_columns("  Discount", "", f"-{_money(discount)}")))

    lines.extend(
        [
            _line("-" * PAPER_WIDTH),
            _line(_columns("Subtotal", "", _money(getattr(sale, "subtotal", 0)))),
        ]
    )

    discount_total = _decimal(getattr(sale, "discount_total", 0))
    if discount_total > Decimal("0"):
        lines.append(_line(_columns("Discounts", "", f"-{_money(discount_total)}")))

    tax_total = _decimal(getattr(sale, "tax_total", 0))
    if tax_total > Decimal("0"):
        lines.append(_line(_columns("Tax", "", _money(tax_total))))

    lines.extend(
        [
            b"\x1bE\x01",
            _line(_columns("TOTAL", "", _money(getattr(sale, "grand_total", 0)))),
            b"\x1bE\x00",
            _line(""),
            _line(_payment_line(sale)),
        ]
    )

    if copy_type == "merchant" and getattr(sale, "payment_method", None) == "CARD":
        lines.extend(
            [
                _line(""),
                _line("I agree to pay above total"),
                _line(""),
                _line("Signature:"),
                _line("_" * PAPER_WIDTH),
            ]
        )

    lines.extend(
        [
            _line(""),
            _line(""),
            b"\x1dV\x00",  # full cut
        ]
    )
    return b"".join(lines)


def _receipt_datetime(sale) -> str:
    value = getattr(sale, "completed_at", None) or getattr(sale, "created_at", None) or datetime.utcnow()
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %I:%M %p")
    return str(value)


def _payment_line(sale) -> str:
    method = getattr(sale, "payment_method", None) or "UNKNOWN"
    if method == "CARD" and getattr(sale, "card_last4", None):
        return f"Payment: CARD ****{sale.card_last4}"
    return f"Payment: {method}"


def _columns(left: str, middle: str, right: str) -> str:
    if middle:
        left_width = PAPER_WIDTH - 19
        return f"{left[:left_width]:<{left_width}}{middle:>9}{right:>10}"
    return f"{left[: PAPER_WIDTH - 12]:<{PAPER_WIDTH - 12}}{right:>12}"


def _money(value) -> str:
    return f"${_decimal(value):.2f}"


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _line(value: str) -> bytes:
    return f"{value}\n".encode("cp437", errors="replace")
