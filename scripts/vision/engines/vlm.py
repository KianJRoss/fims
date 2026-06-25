from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import types
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


# Heavy VLM inference runs on KianPuter (RTX 4070 Ti SUPER, 16GB) over Tailscale --
# ~1s/image vs 15-50s on the laptop. Override with OLLAMA_HOST to run locally.
PC_OLLAMA = "http://100.99.89.118:11434"


def _ollama_host() -> str:
    return os.getenv("OLLAMA_HOST", PC_OLLAMA).rstrip("/")


def _vision_model() -> str:
    return os.getenv("VISION_MODEL", "qwen2.5vl:7b")


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _extract_jsonish(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        snippet = match.group(0)
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            return {"response": text}
    return {"response": text}


def ask_json(image_path: str | Path, prompt: str) -> dict[str, Any]:
    image_bytes = Path(image_path).read_bytes()
    payload = {
        "model": _vision_model(),
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
    }
    data = _http_json("POST", f"{_ollama_host()}/api/generate", payload=payload, timeout=180)
    if isinstance(data, dict):
        response = data.get("response")
        if isinstance(response, dict):
            return response
        if isinstance(response, str):
            parsed = _extract_jsonish(response)
            if parsed:
                return parsed
        if "message" in data and isinstance(data["message"], dict):
            content = data["message"].get("content")
            if isinstance(content, str):
                parsed = _extract_jsonish(content)
                if parsed:
                    return parsed
        if "response" in data:
            return {"response": data["response"]}
    raise ValueError("Unexpected Ollama response")


def read_label(image_path: str | Path) -> str:
    prompt = (
        "Return JSON only with a short `label` field naming the main product shown in the image. "
        "Keep it brief."
    )
    data = ask_json(image_path, prompt)
    for key in ("label", "name", "text", "description", "value"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(data, ensure_ascii=False)


def describe(image_path: str | Path) -> dict[str, Any]:
    prompt = (
        "Return JSON only describing the image. Include concise keys like label, brand, size, colors, "
        "and notable text if present."
    )
    return ask_json(image_path, prompt)


def _model_ready() -> bool:
    try:
        data = _http_json("GET", f"{_ollama_host()}/api/tags", timeout=20)
    except (HTTPError, URLError, TimeoutError, ConnectionError, OSError, ValueError):
        return False
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return False
    target = _vision_model()
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name == target:
            return True
    return False


def self_test() -> int:
    banana = Path(__file__).resolve().parents[3] / "media" / "product_images" / "1004074.jpg"
    if not _model_ready():
        print("model not ready, skipping")
        return 0
    label = read_label(banana)
    print(f"VLM label: {label}")
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
