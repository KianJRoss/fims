from __future__ import annotations

import json
import logging
import subprocess

import httpx

from app.core.email_crypto import decrypt_secret
from app.models.monitoring import AiMonitorConfig

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _extract_anthropic_text(payload: dict) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise RuntimeError("Anthropic response missing content blocks")

    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())

    text = "\n".join(chunks).strip()
    if not text:
        raise RuntimeError("Anthropic response did not include text content")
    return text


def analyze(config: AiMonitorConfig, prompt: str) -> str:
    backend_type = (config.backend_type or "").strip().lower()

    if backend_type == "api_key":
        encrypted_api_key = config.encrypted_api_key
        if not encrypted_api_key:
            raise RuntimeError("AI monitoring API key is not configured")

        api_key = decrypt_secret(encrypted_api_key)
        response = httpx.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20.0,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Anthropic request failed with status {response.status_code}: {response.text.strip()}"
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Anthropic response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Anthropic response body was malformed")
        return _extract_anthropic_text(payload)

    if backend_type == "cli":
        result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=60)
        stdout = (result.stdout or "").strip()
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                f"claude CLI failed with exit code {result.returncode}"
                + (f": {stderr}" if stderr else "")
            )
        if not stdout:
            raise RuntimeError("claude CLI returned no output")
        return stdout

    raise RuntimeError(f"Unsupported AI monitoring backend: {config.backend_type}")


def test_backend(config: AiMonitorConfig) -> tuple[bool, str]:
    try:
        output = analyze(config, "Reply with exactly: OK")
        return True, output
    except Exception as exc:  # noqa: BLE001 - user-facing connectivity test
        return False, str(exc)
