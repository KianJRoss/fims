#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

import requests
from evdev import InputDevice, ecodes, list_devices

API_URL = "http://127.0.0.1/api/v1/scanner/input"

KEY_MAP = {
    getattr(ecodes, f"KEY_{digit}"): digit for digit in range(10)
}
KEY_MAP.update(
    {
        getattr(ecodes, f"KEY_{chr(ord('A') + index)}"): chr(ord('A') + index)
        for index in range(26)
    }
)
KEY_MAP[ecodes.KEY_SPACE] = " "

ENTER_CODES = {ecodes.KEY_ENTER}
if hasattr(ecodes, "KEY_KPENTER"):
    ENTER_CODES.add(ecodes.KEY_KPENTER)


def _device_capabilities(device: InputDevice) -> dict:
    try:
        return device.capabilities(verbose=True)
    except OSError:
        return {}


def _load_input_devices() -> list[InputDevice]:
    devices: list[InputDevice] = []
    for path in list_devices():
        try:
            devices.append(InputDevice(path))
        except OSError:
            continue
    return devices


def is_keyboard_like(device: InputDevice) -> bool:
    keys = device.capabilities().get(ecodes.EV_KEY, [])
    if not keys:
        return False

    interesting_codes = {
        ecodes.KEY_ENTER,
        ecodes.KEY_SPACE,
        ecodes.KEY_0,
        ecodes.KEY_1,
        ecodes.KEY_2,
        ecodes.KEY_3,
        ecodes.KEY_4,
        ecodes.KEY_5,
        ecodes.KEY_6,
        ecodes.KEY_7,
        ecodes.KEY_8,
        ecodes.KEY_9,
    }
    interesting_codes.update(getattr(ecodes, f"KEY_{chr(ord('A') + index)}") for index in range(26))
    return any(code in interesting_codes for code in keys)


def select_device(forced_device: str | None = None) -> InputDevice | None:
    if forced_device:
        return InputDevice(forced_device)

    devices = _load_input_devices()
    selected: InputDevice | None = None
    try:
        for device in devices:
            name = (device.name or "").lower()
            if any(term in name for term in ("barcode", "scanner", "hid")):
                selected = device
                break

        if selected is None:
            keyboard_like = [device for device in devices if is_keyboard_like(device)]
            if len(keyboard_like) >= 2:
                selected = keyboard_like[1]
            elif keyboard_like:
                selected = keyboard_like[0]

        if selected is None:
            return None

        for device in devices:
            if device is not selected:
                device.close()
        return selected
    except Exception:
        for device in devices:
            try:
                device.close()
            except Exception:
                pass
        raise


def print_devices() -> None:
    for path in list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue
        try:
            print(f"{device.path}\t{name_or_unknown(device.name)}\t{_device_capabilities(device)}")
        finally:
            device.close()


def name_or_unknown(value: str | None) -> str:
    return value if value else "Unknown"


def post_barcode(barcode: str) -> None:
    response = requests.post(API_URL, json={"barcode": barcode}, timeout=5)
    response.raise_for_status()


def read_scanner(device: InputDevice) -> None:
    buffer: list[str] = []
    for event in device.read_loop():
        if event.type != ecodes.EV_KEY or event.value != 1:
            continue

        if event.code in ENTER_CODES:
            barcode = "".join(buffer).strip()
            buffer.clear()
            if barcode:
                post_barcode(barcode)
            continue

        char = KEY_MAP.get(event.code)
        if char is not None:
            buffer.append(char)


def run_loop(forced_device: str | None = None) -> None:
    while True:
        device: InputDevice | None = None
        try:
            device = select_device(forced_device)
            if device is None:
                raise RuntimeError("No barcode scanner device found")
            read_scanner(device)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[scanner_reader] {exc}")
            time.sleep(2)
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read a USB HID barcode scanner and forward scans to FIMS.")
    parser.add_argument("--list-devices", action="store_true", help="Print input devices and exit")
    parser.add_argument("--device", help="Force a specific /dev/input/eventX device")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_devices:
        print_devices()
        return

    run_loop(args.device)


if __name__ == "__main__":
    main()
