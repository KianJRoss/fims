from __future__ import annotations

import argparse
import tempfile
import sys
import types
from pathlib import Path
from typing import Any

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


def page_count(pdf_path: str | Path) -> int:
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        return doc.page_count


def rasterize(pdf_path: str | Path, page: int, dpi: int = 200) -> Image.Image:
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        pix = doc.load_page(page).get_pixmap(dpi=dpi, alpha=False)
        mode = "RGB" if pix.alpha == 0 else "RGBA"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def extract_text(pdf_path: str | Path, page: int) -> str:
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        return doc.load_page(page).get_text("text")


def split_page_subjects(*_args: Any, **_kwargs: Any):
    # TODO Phase 2: split PDF pages into per-product subject regions.
    raise NotImplementedError("TODO Phase 2")


def self_test() -> int:
    import fitz

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "vision_test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Vision PDF test")
        doc.save(str(pdf_path))
        doc.close()
        count = page_count(pdf_path)
        text = extract_text(pdf_path, 0)
        image = rasterize(pdf_path, 0)
        print(f"PDF page count: {count}")
        print(f"PDF extracted text: {text.strip()}")
        print(f"PDF raster size: {image.size}")
        assert count == 1
        assert "Vision PDF test" in text
        assert isinstance(image, Image.Image)
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
