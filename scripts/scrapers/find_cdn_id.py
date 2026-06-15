from __future__ import annotations

import argparse
import re
import sys

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
CDN_ID_PATTERNS = [
    re.compile(r'"config"\s*:\s*\{\s*"id"\s*:\s*"([0-9a-f]{12}-[0-9a-f]{32})"', re.IGNORECASE),
    re.compile(r'"id"\s*:\s*"([0-9a-f]{12}-[0-9a-f]{32})"', re.IGNORECASE),
    re.compile(r"\b([0-9a-f]{12}-[0-9a-f]{32})\b", re.IGNORECASE),
]


def find_cdn_id(html: str) -> str | None:
    for pattern in CDN_ID_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Find an Issuu CDN ID from a publication URL.")
    parser.add_argument("publication_url", help="Issuu publication URL")
    args = parser.parse_args()

    response = requests.get(args.publication_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    cdn_id = find_cdn_id(response.text)
    if not cdn_id:
        print("CDN ID not found", file=sys.stderr)
        return 1

    print(cdn_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
