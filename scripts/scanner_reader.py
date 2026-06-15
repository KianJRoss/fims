#!/usr/bin/env python3
"""Read all USB HID barcode scanners and forward scans to FIMS via HTTP."""
from __future__ import annotations

import argparse
import sys
import threading
import time

import requests
from evdev import InputDevice, ecodes, list_devices

API_URL = "http://127.0.0.1/api/v1/scanner/input"

KEY_MAP: dict[int, str] = {getattr(ecodes, f"KEY_{d}"): str(d) for d in range(10)}
KEY_MAP.update(
    {getattr(ecodes, f"KEY_{chr(65 + i)}"): chr(65 + i) for i in range(26)}
)

ENTER_CODES: set[int] = {ecodes.KEY_ENTER}
if hasattr(ecodes, "KEY_KPENTER"):
    ENTER_CODES.add(ecodes.KEY_KPENTER)

SCANNER_KEYWORDS = ("barcode", "scanner", "hid")


def _is_scanner(device: InputDevice) -> bool:
    name = (device.name or "").lower()
    return any(k in name for k in SCANNER_KEYWORDS)


def _is_keyboard_like(device: InputDevice) -> bool:
    keys = device.capabilities().get(ecodes.EV_KEY, [])
    digit_codes = {getattr(ecodes, f"KEY_{d}") for d in range(10)}
    return bool(set(keys) & digit_codes) and ecodes.KEY_ENTER in keys


def find_scanners() -> list[InputDevice]:
    """Return all devices that look like barcode scanners."""
    found: list[InputDevice] = []
    all_devs: list[InputDevice] = []
    try:
        for path in list_devices():
            try:
                all_devs.append(InputDevice(path))
            except OSError:
                continue

        named = [d for d in all_devs if _is_scanner(d)]
        if named:
            found = named
        else:
            kb_like = [d for d in all_devs if _is_keyboard_like(d)]
            if len(kb_like) >= 2:
                found = kb_like[1:]

        # Close devices we won't use
        for d in all_devs:
            if d not in found:
                try:
                    d.close()
                except OSError:
                    pass
    except Exception:
        for d in all_devs:
            try:
                d.close()
            except OSError:
                pass
        raise

    return found


def post_barcode(barcode: str) -> None:
    response = requests.post(API_URL, json={"barcode": barcode}, timeout=5)
    response.raise_for_status()


def read_device(device: InputDevice, label: str) -> None:
    """Block and read events from one device, posting barcodes to the API."""
    buffer: list[str] = []
    try:
        device.grab()
    except OSError:
        pass  # grab is best-effort; read still works without it

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY or event.value != 1:
                continue
            if event.code in ENTER_CODES:
                barcode = "".join(buffer).strip()
                buffer.clear()
                if barcode:
                    print(f"[{label}] barcode: {barcode}", flush=True)
                    try:
                        post_barcode(barcode)
                    except Exception as exc:
                        print(f"[{label}] POST error: {exc}", flush=True)
            else:
                char = KEY_MAP.get(event.code)
                if char is not None:
                    buffer.append(char)
    except OSError as exc:
        print(f"[{label}] device lost: {exc}", flush=True)
    finally:
        try:
            device.ungrab()
        except OSError:
            pass
        try:
            device.close()
        except OSError:
            pass


def run_loop(forced_device: str | None = None) -> None:
    while True:
        try:
            if forced_device:
                devices = [InputDevice(forced_device)]
            else:
                devices = find_scanners()

            if not devices:
                print("[scanner_reader] no scanner found, retrying in 5s", flush=True)
                time.sleep(5)
                continue

            for d in devices:
                print(f"[scanner_reader] monitoring {d.name!r} at {d.path}", flush=True)

            if len(devices) == 1:
                read_device(devices[0], devices[0].path)
            else:
                threads = []
                for d in devices:
                    t = threading.Thread(target=read_device, args=(d, d.path), daemon=True)
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join()

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[scanner_reader] error: {exc}", flush=True)

        time.sleep(2)


def print_devices() -> None:
    for path in list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue
        try:
            caps = device.capabilities(verbose=True)
            print(f"{device.path}\t{device.name or 'Unknown'}\t{caps}")
        finally:
            device.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read USB HID barcode scanners and forward to FIMS.")
    parser.add_argument("--list-devices", action="store_true", help="Print input devices and exit")
    parser.add_argument("--device", help="Force a specific /dev/input/eventX device")
    args = parser.parse_args()

    if args.list_devices:
        print_devices()
        sys.exit(0)

    run_loop(args.device)


if __name__ == "__main__":
    main()
