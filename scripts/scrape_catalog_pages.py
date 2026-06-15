from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic


TOTAL_PAGES = 177
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DOWNLOAD_DELAY_SECONDS = 0.3
API_DELAY_SECONDS = 0.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SYSTEM_PROMPT = (
    "You are a data extraction assistant. Extract all fireworks product "
    "information from catalog pages. Return only valid JSON, no prose."
)
USER_MESSAGE = (
    "Extract all fireworks products shown on this catalog page. For each product, "
    "extract as much as you can find:\n"
    "- name (product name)\n"
    "- item_number (usually a 7-digit number like 1004400)\n"
    "- shot_count (integer, shots count)\n"
    "- duration_seconds (integer)\n"
    "- effects (list of strings: e.g. ['gold glitter', 'red stars', 'blue peony'])\n"
    "- colors (list of strings)\n"
    "- description (any text description shown)\n"
    "- price (any price shown, as string)\n"
    "- category (type of firework: fountain, aerial, artillery shell, finale, etc.)\n"
    "- image_url (leave null — we will fill this in later)\n\n"
    'Return a JSON object like:\n{"page": <page number>, "products": [<product objects>]}\n\n'
    'If the page is a cover, table of contents, intro page, or contains no products, '
    'return {"page": <N>, "products": []}'
)

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "catalog_pages"
OUTPUT_PATH = BASE_DIR / "jakes_catalog_vision.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and extract fireworks catalog pages."
    )
    parser.add_argument(
        "--pages-only",
        action="store_true",
        help="Only download pages and skip extraction.",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract from already downloaded pages.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start page number.",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=TOTAL_PAGES,
        help="End page number.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Anthropic model name to use.",
    )
    return parser.parse_args()


def clamp_page(page_number: int) -> int:
    return max(1, min(TOTAL_PAGES, page_number))


def selected_pages(start: int, end: int) -> list[int]:
    start_page = clamp_page(start)
    end_page = clamp_page(end)
    if end_page < start_page:
        return []
    return list(range(start_page, end_page + 1))


def download_pages(pages: list[int]) -> None:
    if not pages:
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT}

    for page_number in pages:
        image_path = CACHE_DIR / f"page_{page_number}.jpg"
        if image_path.exists():
            continue

        url = (
            "https://image.isu.pub/"
            "260506140512-f077399ecfd86afa6eee7e4087f1bd81/"
            f"jpg/page_{page_number}.jpg"
        )

        try:
            response = session.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            image_path.write_bytes(response.content)
            print(f"Downloaded page {page_number}/{TOTAL_PAGES}")
        except Exception as exc:
            print(f"Error downloading page {page_number}: {exc}")
        finally:
            time.sleep(DOWNLOAD_DELAY_SECONDS)


def read_image_base64(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


def extract_text_from_response(response: Any) -> str:
    text_parts: list[str] = []
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            text_parts.append(block.text)
    return "".join(text_parts).strip()


def parse_json_payload(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def extract_pages(pages: list[int], model: str) -> None:
    if not pages:
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error extracting pages: ANTHROPIC_API_KEY is not set")
        return

    try:
        client = Anthropic(api_key=api_key)
    except Exception as exc:
        print(f"Error initializing Anthropic client: {exc}")
        return

    for page_number in pages:
        json_path = CACHE_DIR / f"page_{page_number}.json"
        if json_path.exists():
            continue

        image_path = CACHE_DIR / f"page_{page_number}.jpg"
        if not image_path.exists():
            continue

        try:
            image_data = read_image_base64(image_path)
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_data,
                                },
                            },
                            {"type": "text", "text": USER_MESSAGE},
                        ],
                    }
                ],
            )
            response_text = extract_text_from_response(response)
            parsed = parse_json_payload(response_text)
            json_path.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"Error extracting page {page_number}: {exc}")
        finally:
            time.sleep(API_DELAY_SECONDS)


def load_page_json(page_number: int) -> dict[str, Any] | None:
    json_path = CACHE_DIR / f"page_{page_number}.json"
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_output() -> int:
    products: list[dict[str, Any]] = []
    seen_item_numbers: set[str] = set()

    for page_number in range(1, TOTAL_PAGES + 1):
        payload = load_page_json(page_number)
        if not payload:
            continue

        page_products = payload.get("products", [])
        if not isinstance(page_products, list):
            continue

        for product in page_products:
            if not isinstance(product, dict):
                continue
            item_number = product.get("item_number")
            if item_number is not None and str(item_number).strip():
                key = str(item_number).strip()
                if key in seen_item_numbers:
                    continue
                seen_item_numbers.add(key)
            products.append(product)

    OUTPUT_PATH.write_text(
        json.dumps(products, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(products)


def main() -> None:
    args = parse_args()
    pages = selected_pages(args.start, args.end)

    if not args.extract_only:
        download_pages(pages)

    if args.pages_only:
        return

    extract_pages(pages, args.model)
    total_products = write_output()

    print(f"Pages downloaded: {len(pages)}")
    print(f"Pages extracted: {len(pages)}")
    print(f"Total products found: {total_products}")
    print("Output: scripts/jakes_catalog_vision.json")


if __name__ == "__main__":
    main()
