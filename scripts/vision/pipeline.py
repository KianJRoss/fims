from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

if __package__ in (None, ""):
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _SCRIPTS_DIR = _REPO_ROOT / "scripts"
    if "scripts" not in sys.modules:
        _pkg = types.ModuleType("scripts")
        _pkg.__path__ = [str(_SCRIPTS_DIR)]
        sys.modules["scripts"] = _pkg
    if "scripts.vision" not in sys.modules:
        _pkg = types.ModuleType("scripts.vision")
        _pkg.__path__ = [str(_SCRIPTS_DIR / "vision")]
        sys.modules["scripts.vision"] = _pkg
    __package__ = "scripts.vision"

from ._shared import ensure_vision_out_dir, load_pil_image
from .engines.bg import remove_background
from .engines.codes import read_codes
from .engines.ocr import read_text
from .engines.pdf import rasterize
from .engines.vlm import describe, read_label
from .result import Analysis


def materialize_image(source: Any, pil: Image.Image, source_label: str, *, suffix: str = ".png", force_save: bool = False) -> Path:
    path = Path(source) if isinstance(source, (str, Path)) else None
    if path is not None and not force_save:
        return path
    out_dir = ensure_vision_out_dir()
    safe_name = source_label.replace("\\", "_").replace("/", "_").replace(":", "_").replace("#", "_")
    temp_path = out_dir / f"{safe_name}{suffix}"
    pil.save(temp_path, format="PNG")
    return temp_path


def analyze_image(path: Any, steps: Iterable[str] = ("ocr", "codes", "vlm"), source: str | None = None) -> Analysis:
    pil = load_pil_image(path)
    arr = np.asarray(pil)
    source_label = source or (str(path) if isinstance(path, (str, Path)) else "memory-image")
    analysis = Analysis(
        source=source_label,
        width=pil.width,
        height=pil.height,
        meta={"errors": {}, "steps": list(steps)},
    )

    for step in steps:
        try:
            if step == "ocr":
                analysis.texts = read_text(arr)
            elif step == "codes":
                analysis.codes = read_codes(pil)
            elif step == "vlm":
                vlm_path = materialize_image(path, pil, source_label)
                analysis.vlm = {
                    "label": read_label(vlm_path),
                    "describe": describe(vlm_path),
                }
            elif step == "bg":
                bg_source = path if isinstance(path, (str, Path)) else materialize_image(path, pil, source_label)
                bg_path = remove_background(bg_source)
                analysis.meta["background_removed"] = bg_path
            else:
                analysis.meta.setdefault("warnings", []).append(f"Unknown step: {step}")
        except Exception as exc:
            analysis.meta.setdefault("errors", {})[step] = str(exc)
    return analysis


def analyze_pdf_page(pdf: str | Path, page: int, steps: Iterable[str] = ("ocr", "codes", "vlm")) -> Analysis:
    image = rasterize(pdf, page)
    source = f"{pdf}#page={page + 1}"
    return analyze_image(image, steps=steps, source=source)
