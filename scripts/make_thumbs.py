#!/usr/bin/env python3
"""Generate list-view thumbnails for media/product_images.

Creates media/product_images/thumbs/<stem>.webp (max 320px on the long side).
Skips thumbs that are already newer than their source, so re-runs are cheap —
safe to re-run after new product images are added or re-pulled.

Usage (from the repo root, host python with Pillow):
    python3 scripts/make_thumbs.py [media/product_images]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

MAX_SIZE = 320
QUALITY = 80
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    src_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "media/product_images")
    if not src_dir.is_dir():
        sys.exit(f"source dir not found: {src_dir}")
    thumb_dir = src_dir / "thumbs"
    thumb_dir.mkdir(exist_ok=True)

    made = skipped = failed = 0
    for src in sorted(src_dir.iterdir()):
        if not src.is_file() or src.suffix.lower() not in EXTS:
            continue
        dst = thumb_dir / (src.stem + ".webp")
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            continue
        try:
            with Image.open(src) as im:
                # flatten transparency onto the app's dark card color so PNGs
                # with alpha don't get a jarring white box
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    from PIL import Image as _I
                    bg = _I.new("RGB", im.size, (17, 24, 39))  # tailwind gray-900
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.thumbnail((MAX_SIZE, MAX_SIZE))
                im.save(dst, "WEBP", quality=QUALITY, method=4)
            made += 1
        except Exception as exc:  # corrupt/zero-byte sources exist in this set
            failed += 1
            print(f"FAIL {src.name}: {exc}", flush=True)

    print(f"done: {made} created, {skipped} up-to-date, {failed} failed", flush=True)


if __name__ == "__main__":
    main()
