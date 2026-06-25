from __future__ import annotations

import argparse
import io
import os
import multiprocessing as mp
import sys
import types
import time
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

from .._shared import derive_out_path, load_rgba_image


def _get_session(model_name: str):
    from rembg import new_session

    return new_session(model_name)


def _rembg_worker(image_bytes: bytes, model_name: str, out_q: mp.Queue) -> None:
    try:
        from rembg import remove

        with Image.open(io.BytesIO(image_bytes)) as img:
            pil = img.convert("RGB")
        result = remove(pil, session=_get_session(model_name))
        if isinstance(result, Image.Image):
            rgba = result.convert("RGBA")
        elif isinstance(result, bytes):
            rgba = Image.open(io.BytesIO(result)).convert("RGBA")
        elif isinstance(result, np.ndarray):
            rgba = Image.fromarray(result).convert("RGBA")
        else:
            raise TypeError(f"Unsupported rembg result type: {type(result)!r}")
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        out_q.put(("ok", buf.getvalue()))
    except Exception as exc:
        out_q.put(("err", repr(exc)))


def _remove_with_model(image: Image.Image, model_name: str, timeout_s: int = 20) -> Image.Image:
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    proc = ctx.Process(target=_rembg_worker, args=(buf.getvalue(), model_name, q))
    proc.daemon = True
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(10)
        raise TimeoutError(f"rembg timed out for model {model_name}")
    if q.empty():
        raise RuntimeError(f"rembg produced no output for model {model_name}")
    status, payload = q.get()
    if status != "ok":
        raise RuntimeError(str(payload))
    return Image.open(io.BytesIO(payload)).convert("RGBA")


def remove_background(image_path: str | Path, out_path: str | Path | None = None, model: str | None = None) -> str:
    source = Path(image_path)
    target = Path(out_path) if out_path is not None else derive_out_path(source, "_bg.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    pil = load_rgba_image(source)
    primary = model or os.getenv("BG_MODEL", "birefnet-general")
    fallbacks = [primary, "isnet-general-use"]
    last_error: Exception | None = None
    for model_name in dict.fromkeys(fallbacks):
        try:
            start = time.monotonic()
            result = _remove_with_model(pil, model_name)
            elapsed = time.monotonic() - start
            result.save(target, format="PNG")
            if elapsed > 20 and model_name != "isnet-general-use":
                try:
                    fallback_result = _remove_with_model(pil, "isnet-general-use")
                    fallback_result.save(target, format="PNG")
                except Exception:
                    pass
            return str(target)
        except Exception as exc:
            last_error = exc
            continue
    fallback = pil.convert("RGBA")
    fallback.save(target, format="PNG")
    return str(target)


def alpha_mask(image_path: str | Path) -> np.ndarray:
    from rembg import remove

    pil = load_rgba_image(image_path)
    primary = os.getenv("BG_MODEL", "birefnet-general")
    try:
        result = remove(pil, session=_get_session(primary))
    except Exception:
        try:
            result = remove(pil, session=_get_session("isnet-general-use"))
        except Exception:
            result = pil.convert("RGBA")
    if isinstance(result, Image.Image):
        rgba = result.convert("RGBA")
    elif isinstance(result, bytes):
        from io import BytesIO

        rgba = Image.open(BytesIO(result)).convert("RGBA")
    elif isinstance(result, np.ndarray):
        rgba = Image.fromarray(result).convert("RGBA")
    else:
        raise TypeError(f"Unsupported rembg result type: {type(result)!r}")
    return np.asarray(rgba.getchannel("A"))


def self_test() -> int:
    banana = Path(__file__).resolve().parents[3] / "media" / "product_images" / "1004074.jpg"
    out_path = remove_background(banana)
    print(f"BG output: {out_path}")
    assert Path(out_path).exists(), "Expected background output PNG"
    with Image.open(out_path) as img:
        assert img.mode in ("RGBA", "LA"), f"Expected alpha channel, got {img.mode}"
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
