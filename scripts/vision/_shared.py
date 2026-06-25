from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def vision_out_dir() -> Path:
    return repo_root() / "media" / "vision_out"


def ensure_vision_out_dir() -> Path:
    out_dir = vision_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _as_path(source: Any) -> Path | None:
    if isinstance(source, Path):
        return source
    if isinstance(source, str):
        return Path(source)
    return None


def load_pil_image(source: Any) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.copy()
    if isinstance(source, np.ndarray):
        arr = source
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            return Image.fromarray(arr, mode="L").convert("RGB")
        if arr.ndim == 3 and arr.shape[2] == 4:
            return Image.fromarray(arr, mode="RGBA").convert("RGB")
        return Image.fromarray(arr).convert("RGB")
    path = _as_path(source)
    if path is not None:
        return Image.open(path).convert("RGB")
    raise TypeError(f"Unsupported image source type: {type(source)!r}")


def load_rgba_image(source: Any) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.copy().convert("RGBA")
    if isinstance(source, np.ndarray):
        arr = source
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            return Image.fromarray(arr, mode="L").convert("RGBA")
        if arr.ndim == 3 and arr.shape[2] == 4:
            return Image.fromarray(arr, mode="RGBA")
        return Image.fromarray(arr).convert("RGBA")
    path = _as_path(source)
    if path is not None:
        return Image.open(path).convert("RGBA")
    raise TypeError(f"Unsupported image source type: {type(source)!r}")


def image_to_array(image: Any) -> np.ndarray:
    pil = load_pil_image(image)
    return np.asarray(pil)


def rgba_bytes(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def derive_out_path(source_path: Any, suffix: str) -> Path:
    path = _as_path(source_path)
    stem = path.stem if path is not None else "image"
    return ensure_vision_out_dir() / f"{stem}{suffix}"

