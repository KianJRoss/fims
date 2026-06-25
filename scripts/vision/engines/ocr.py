from __future__ import annotations

import argparse
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

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

from .._shared import image_to_array, load_pil_image
from ..result import TextRegion

_rapid_ocr = None
_pytesseract = None
_pytesseract_output = None
_tesseract_available = None


def _get_rapid_ocr():
    global _rapid_ocr
    if _rapid_ocr is not None:
        return _rapid_ocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_ocr = RapidOCR()
    except Exception:
        _rapid_ocr = False
    return _rapid_ocr


def _get_pytesseract():
    global _pytesseract, _pytesseract_output, _tesseract_available
    if _pytesseract is not None:
        return _pytesseract, _pytesseract_output, _tesseract_available
    try:
        import pytesseract
        from pytesseract import Output

        _pytesseract = pytesseract
        _pytesseract_output = Output
        _tesseract_available = bool(shutil.which("tesseract"))
    except Exception:
        _pytesseract = False
        _pytesseract_output = None
        _tesseract_available = False
    return _pytesseract, _pytesseract_output, _tesseract_available


def _normalize_bbox(bbox: Any) -> list[float] | None:
    if bbox is None:
        return None
    try:
        arr = np.asarray(bbox, dtype=float)
        if arr.size == 4:
            x1, y1, x2, y2 = arr.tolist()
            return [float(x1), float(y1), float(x2), float(y2)]
        if arr.ndim == 2 and arr.shape[0] >= 4:
            xs = arr[:, 0]
            ys = arr[:, 1]
            return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    except Exception:
        return None
    return None


def _candidate_images(pil: Image.Image) -> list[Image.Image]:
    base = pil.convert("RGB")
    upscaled = base.resize((base.width * 2, base.height * 2), Image.Resampling.LANCZOS)
    grayscale = base.convert("L").convert("RGB")
    contrast = ImageEnhance.Contrast(grayscale).enhance(1.8)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    return [base, upscaled, grayscale, sharpened]


def _parse_rapidocr_result(result: Any) -> list[TextRegion]:
    if not result:
        return []
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], (list, tuple)):
        result = result[0]
    regions: list[TextRegion] = []
    for item in result or []:
        text = None
        bbox = None
        confidence = None
        if isinstance(item, dict):
            text = item.get("text") or item.get("transcription") or item.get("label")
            bbox = item.get("bbox") or item.get("box") or item.get("points")
            confidence = item.get("confidence") or item.get("score")
        elif isinstance(item, (list, tuple)):
            if len(item) >= 2:
                bbox = item[0]
                text = item[1]
            if len(item) >= 3:
                confidence = item[2]
        if text is None:
            continue
        norm_bbox = _normalize_bbox(bbox)
        if norm_bbox is None:
            norm_bbox = [0.0, 0.0, 0.0, 0.0]
        regions.append(TextRegion(text=str(text), bbox=norm_bbox, confidence=float(confidence) if confidence is not None else None))
    return regions


def _parse_pytesseract_data(data: dict[str, list[Any]]) -> list[TextRegion]:
    regions: list[TextRegion] = []
    texts = data.get("text", [])
    if not texts:
        return regions
    for i, text in enumerate(texts):
        clean = str(text).strip()
        if not clean:
            continue
        try:
            conf_raw = data.get("conf", [None])[i]
            confidence = float(conf_raw) / 100.0 if conf_raw not in (None, "", "-1") else None
        except Exception:
            confidence = None
        try:
            x = float(data.get("left", [0])[i])
            y = float(data.get("top", [0])[i])
            w = float(data.get("width", [0])[i])
            h = float(data.get("height", [0])[i])
        except Exception:
            x = y = w = h = 0.0
        regions.append(TextRegion(text=clean, bbox=[x, y, x + w, y + h], confidence=confidence))
    return regions


def read_text(image: Any) -> list[TextRegion]:
    pil = load_pil_image(image)
    regions: list[TextRegion] = []
    seen: set[tuple[str, tuple[float, float, float, float]]] = set()

    rapid_ocr = _get_rapid_ocr()
    if rapid_ocr not in (None, False):
        for candidate in _candidate_images(pil):
            try:
                result, _ = rapid_ocr(image_to_array(candidate))
                for region in _parse_rapidocr_result(result):
                    key = (region.text, tuple(round(v, 2) for v in region.bbox))
                    if key in seen:
                        continue
                    seen.add(key)
                    regions.append(region)
            except Exception:
                continue

    pytesseract, output, tesseract_available = _get_pytesseract()
    if pytesseract not in (None, False) and tesseract_available:
        for candidate in _candidate_images(pil):
            try:
                data = pytesseract.image_to_data(candidate, output_type=output.DICT, config="--psm 11")
                for region in _parse_pytesseract_data(data):
                    key = (region.text, tuple(round(v, 2) for v in region.bbox))
                    if key in seen:
                        continue
                    seen.add(key)
                    regions.append(region)
            except Exception:
                continue

    return regions


def self_test() -> int:
    banana = Path(__file__).resolve().parents[3] / "media" / "product_images" / "1004074.jpg"
    regions = read_text(banana)
    texts = [region.text for region in regions]
    print(f"OCR regions: {len(regions)}")
    print("OCR texts:", texts[:10])
    assert any("BANANA" in text.upper() for text in texts), "Expected BANANA in OCR output"
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
