#!/usr/bin/env python3
"""Detect a Dejavoo (Castles) payment terminal on a serial port. READ-ONLY.

Lists serial ports and flags the Dejavoo by its USB VID/PID (0x0CA6 / 0xA050).
It does NOT open or write to the terminal, so it is always safe to run -- it
cannot start, cancel, or lock a card transaction.

This is the POS-station test tool: run it on the machine the terminal is plugged
into (the live transaction integration is a separate, later step that needs the
Dejavoo SPIn SDK + Auth Key).

    python scripts/payments/dejavoo_probe.py            # one-shot report
    python scripts/payments/dejavoo_probe.py --monitor  # watch plug/unplug live
    python scripts/payments/dejavoo_probe.py --json      # machine-readable

Requires pyserial (`pip install pyserial`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

DEJAVOO_VID = 0x0CA6
DEJAVOO_PID = 0xA050


def _is_dejavoo(p) -> bool:
    return (p.vid, p.pid) == (DEJAVOO_VID, DEJAVOO_PID)


def scan():
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    hits = [p for p in ports if _is_dejavoo(p)]
    return ports, hits


def report(as_json: bool) -> int:
    ports, hits = scan()
    if as_json:
        print(json.dumps({
            "detected": bool(hits),
            "terminal_port": hits[0].device if hits else None,
            "ports": [
                {"device": p.device, "vid": p.vid, "pid": p.pid,
                 "description": p.description, "dejavoo": _is_dejavoo(p)}
                for p in ports
            ],
        }, indent=2))
        return 0 if hits else 1

    print(f"{len(ports)} serial port(s) present:")
    for p in ports:
        vid = f"{p.vid:#06x}" if p.vid else "-"
        pid = f"{p.pid:#06x}" if p.pid else "-"
        tag = "   <-- DEJAVOO terminal" if _is_dejavoo(p) else ""
        print(f"  {p.device:8} vid={vid} pid={pid}  {p.description}{tag}")
    if hits:
        print(f"\nDejavoo terminal detected on {hits[0].device} "
              f"(EFT-POS terminal, VID {DEJAVOO_VID:#06x}/PID {DEJAVOO_PID:#06x}).")
        return 0
    print("\nNo Dejavoo terminal detected. (Checkout would use manual card entry.)")
    return 1


def monitor() -> int:
    print("Monitoring for Dejavoo plug/unplug (Ctrl-C to stop)...")
    last = object()
    try:
        while True:
            _, hits = scan()
            state = hits[0].device if hits else None
            if state != last:
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp}  {'CONNECTED ' + state if state else 'DISCONNECTED'}")
                last = state
            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--monitor", action="store_true", help="watch for plug/unplug")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    try:
        import serial.tools.list_ports  # noqa: F401
    except Exception:
        print("pyserial is required: pip install pyserial", file=sys.stderr)
        return 2
    return monitor() if args.monitor else report(args.json)


if __name__ == "__main__":
    sys.exit(main())
