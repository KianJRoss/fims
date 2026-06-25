from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

if __package__ in (None, ""):
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    _SCRIPTS_DIR = _REPO_ROOT / "scripts"
    if "scripts" not in sys.modules:
        _pkg = types.ModuleType("scripts")
        _pkg.__path__ = [str(_SCRIPTS_DIR)]
        sys.modules["scripts"] = _pkg
    if "scripts.vision" not in sys.modules:
        _pkg = types.ModuleType("scripts.vision")
        _pkg.__path__ = [str(_SCRIPTS_DIR / "vision")]
        sys.modules["scripts.vision"] = _pkg
    if "scripts.vision.engines" not in sys.modules:
        _pkg = types.ModuleType("scripts.vision.engines")
        _pkg.__path__ = [str(_SCRIPTS_DIR / "vision" / "engines")]
        sys.modules["scripts.vision.engines"] = _pkg
    __package__ = "scripts.vision.engines"

from .._shared import load_pil_image
from ..result import Code


def _normalize_bbox(bbox: Any) -> list[float] | None:
    if bbox is None:
        return None
    try:
        arr = np.asarray(bbox, dtype=float)
        if arr.size == 4:
            x1, y1, x2, y2 = arr.reshape(-1).tolist()
            return [float(x1), float(y1), float(x2), float(y2)]
        if arr.ndim == 2 and arr.shape[1] == 2:
            xs = arr[:, 0]
            ys = arr[:, 1]
            return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    except Exception:
        return None
    return None


def _dedupe(codes: list[Code]) -> list[Code]:
    seen: set[tuple[str, str, tuple[float, float, float, float] | None]] = set()
    out: list[Code] = []
    for code in codes:
        bbox_key = None if code.bbox is None else tuple(round(v, 2) for v in code.bbox)
        key = (code.kind.upper(), code.data, bbox_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(code)
    return out


def _from_zxingcpp(image: Any) -> list[Code]:
    try:
        import zxingcpp
    except Exception:
        return []
    try:
        results = zxingcpp.read_barcodes(image)
    except Exception:
        return []
    codes: list[Code] = []
    for item in results or []:
        kind = getattr(getattr(item, "format", None), "name", None) or str(getattr(item, "format", "UNKNOWN"))
        data = getattr(item, "text", None) or getattr(item, "bytes", None)
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        if data is None:
            continue
        position = getattr(item, "position", None) or getattr(item, "polygon", None) or getattr(item, "points", None)
        bbox = _normalize_bbox(position)
        codes.append(Code(kind=kind, data=str(data), bbox=bbox))
    return codes


def _from_pyzbar(image: Any) -> list[Code]:
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except Exception:
        return []
    try:
        decoded = pyzbar_decode(image)
    except Exception:
        return []
    codes: list[Code] = []
    for item in decoded or []:
        kind = getattr(item, "type", "UNKNOWN")
        data = getattr(item, "data", b"")
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        bbox = None
        rect = getattr(item, "rect", None)
        if rect is not None:
            try:
                bbox = [float(rect.left), float(rect.top), float(rect.left + rect.width), float(rect.top + rect.height)]
            except Exception:
                bbox = None
        codes.append(Code(kind=str(kind), data=str(data), bbox=bbox))
    return codes


def _from_opencv_qr(image: Any) -> list[Code]:
    try:
        import cv2
    except Exception:
        return []
    try:
        pil = load_pil_image(image)
        arr = np.asarray(pil.convert("RGB"))
        detector = cv2.QRCodeDetector()
        codes: list[Code] = []
        try:
            multi = detector.detectAndDecodeMulti(arr)
            if isinstance(multi, tuple) and len(multi) == 4:
                ok, decoded_info, points, _ = multi
            elif isinstance(multi, tuple) and len(multi) == 3:
                ok, decoded_info, points = multi
            else:
                ok, decoded_info, points = False, [], None
        except Exception:
            ok, decoded_info, points = False, [], None
        if ok and decoded_info is not None and points is not None:
            for text, pts in zip(decoded_info, points):
                clean = str(text or "").strip()
                if not clean:
                    continue
                bbox = _normalize_bbox(pts)
                codes.append(Code(kind="QR_CODE", data=clean, bbox=bbox))
        if not codes:
            try:
                single = detector.detectAndDecode(arr)
                if isinstance(single, tuple) and len(single) == 3:
                    text, pts, _ = single
                elif isinstance(single, tuple) and len(single) == 2:
                    text, pts = single
                else:
                    text, pts = "", None
                clean = str(text or "").strip()
                if clean:
                    bbox = _normalize_bbox(pts)
                    codes.append(Code(kind="QR_CODE", data=clean, bbox=bbox))
            except Exception:
                pass
        return codes
    except Exception:
        return []


def read_codes(image: Any) -> list[Code]:
    pil = load_pil_image(image)
    codes = []
    codes.extend(_from_zxingcpp(pil))
    codes.extend(_from_pyzbar(pil))
    codes.extend(_from_opencv_qr(pil))
    return _dedupe(codes)


def self_test() -> int:
    banana = Path(__file__).resolve().parents[3] / "media" / "product_images" / "1004074.jpg"
    codes = read_codes(banana)
    print(f"Code detections: {len(codes)}")
    print([code.to_dict() for code in codes[:10]])
    assert isinstance(codes, list)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("Use --self-test")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
