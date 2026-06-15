#!/usr/bin/env python3
"""Quick diagnostic: find barcode scanner, show device info, and print live scans."""

import sys
import time

try:
    from evdev import InputDevice, ecodes, list_devices
except ImportError:
    print("evdev not installed. Run: sudo pip3 install evdev --break-system-packages")
    sys.exit(1)

KEY_MAP = {
    ecodes.KEY_0: "0", ecodes.KEY_1: "1", ecodes.KEY_2: "2", ecodes.KEY_3: "3",
    ecodes.KEY_4: "4", ecodes.KEY_5: "5", ecodes.KEY_6: "6", ecodes.KEY_7: "7",
    ecodes.KEY_8: "8", ecodes.KEY_9: "9",
    ecodes.KEY_A: "A", ecodes.KEY_B: "B", ecodes.KEY_C: "C", ecodes.KEY_D: "D",
    ecodes.KEY_E: "E", ecodes.KEY_F: "F", ecodes.KEY_G: "G", ecodes.KEY_H: "H",
    ecodes.KEY_I: "I", ecodes.KEY_J: "J", ecodes.KEY_K: "K", ecodes.KEY_L: "L",
    ecodes.KEY_M: "M", ecodes.KEY_N: "N", ecodes.KEY_O: "O", ecodes.KEY_P: "P",
    ecodes.KEY_Q: "Q", ecodes.KEY_R: "R", ecodes.KEY_S: "S", ecodes.KEY_T: "T",
    ecodes.KEY_U: "U", ecodes.KEY_V: "V", ecodes.KEY_W: "W", ecodes.KEY_X: "X",
    ecodes.KEY_Y: "Y", ecodes.KEY_Z: "Z",
    ecodes.KEY_MINUS: "-", ecodes.KEY_DOT: ".", ecodes.KEY_SLASH: "/",
    ecodes.KEY_SPACE: " ",
}

def find_scanners():
    scanners = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            name = dev.name.upper()
            if any(k in name for k in ("SCANNER", "BARCODE", "HID")):
                scanners.append(dev)
            else:
                dev.close()
        except Exception:
            pass
    return scanners

def main():
    print("\n=== FIMS Barcode Scanner Diagnostic ===\n")

    print("All input devices:")
    for path in list_devices():
        try:
            dev = InputDevice(path)
            print(f"  {path}  {dev.name}")
            dev.close()
        except Exception:
            pass

    print()
    scanners = find_scanners()

    if not scanners:
        print("No scanner found (looking for 'SCANNER', 'BARCODE', or 'HID' in device name).")
        print("Try: ls /dev/input/event*  to see all devices.")
        sys.exit(1)

    for dev in scanners:
        print(f"Found scanner: {dev.name}")
        print(f"  Path   : {dev.path}")
        print(f"  Phys   : {dev.phys or '(not reported)'}")
        print()

    dev = scanners[0]
    print(f"Listening on {dev.path} — scan a barcode to test (Ctrl+C to quit):\n")

    buf = ""
    try:
        for event in dev.read_loop():
            if event.type != ecodes.EV_KEY or event.value != 1:
                continue
            if event.code == ecodes.KEY_ENTER:
                if buf:
                    print(f"  SCAN -> {buf}")
                    buf = ""
            else:
                buf += KEY_MAP.get(event.code, "?")
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        dev.close()

if __name__ == "__main__":
    main()
