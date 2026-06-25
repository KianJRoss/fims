from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

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

from .engines.bg import remove_background
from .engines.pdf import rasterize
from .pipeline import analyze_image, materialize_image


def _parse_steps(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ("ocr", "codes", "vlm")
    return tuple(step.strip() for step in raw.split(",") if step.strip())


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.vision.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("path")
    analyze.add_argument("--steps", default="ocr,codes,vlm")
    analyze.add_argument("--bg", action="store_true")
    analyze.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "analyze":
        path = Path(args.path)
        steps = _parse_steps(args.steps)
        if path.suffix.lower() == ".pdf":
            page_image = rasterize(path, 0)
            analysis = analyze_image(page_image, steps=steps, source=f"{path}#page=1")
            if args.bg:
                try:
                    bg_source = materialize_image(path, page_image, f"{path}#page=1", force_save=True)
                    analysis.meta["background_removed"] = remove_background(bg_source)
                except Exception as exc:
                    analysis.meta.setdefault("errors", {})["bg"] = str(exc)
        else:
            analysis = analyze_image(path, steps=steps)
            if args.bg:
                try:
                    analysis.meta["background_removed"] = remove_background(path)
                except Exception as exc:
                    analysis.meta.setdefault("errors", {})["bg"] = str(exc)
        if args.json:
            print(json.dumps(analysis.to_dict(), ensure_ascii=False))
        else:
            print(analysis.to_json(indent=2))
        return 0
    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
