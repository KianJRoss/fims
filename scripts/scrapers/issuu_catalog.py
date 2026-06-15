from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://issuu.com/",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class IssuuCatalogScraper:
    def __init__(self, cdn_id: str, output_dir: Path, start_page: int, end_page: int, delay: float = 0.5):
        self.cdn_id = cdn_id
        self.output_dir = output_dir
        self.start_page = start_page
        self.end_page = end_page
        self.delay = delay
        self.session = requests.Session()

    @property
    def total_pages(self) -> int:
        return max(0, self.end_page - self.start_page + 1)

    def fetch_page_text(self, page_number: int) -> str:
        url = f"https://svg.issuu.com/{self.cdn_id}/page_{page_number}.html"
        response = self.session.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return normalize_text(soup.get_text(" | ", strip=True))

    def run(self) -> Path:
        pages: list[dict[str, object]] = []
        total = self.total_pages

        for index, page_number in enumerate(range(self.start_page, self.end_page + 1), start=1):
            try:
                text = self.fetch_page_text(page_number)
            except Exception as exc:
                text = ""
                print(f"Fetched page {page_number}/{total} [error: {exc}]")
            else:
                print(f"Fetched page {page_number}/{total}")

            pages.append({"page": page_number, "text": text})
            if index < total:
                time.sleep(self.delay)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "text_layer.json"
        out_path.write_text(
            json.dumps({"pages": pages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Issuu text layer pages.")
    parser.add_argument("cdn_id", help="Issuu CDN ID")
    parser.add_argument("output_dir", help="Output directory for text_layer.json")
    parser.add_argument("start_page", type=int, help="First page to fetch")
    parser.add_argument("end_page", type=int, help="Last page to fetch")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to sleep between requests")
    args = parser.parse_args()

    scraper = IssuuCatalogScraper(
        cdn_id=args.cdn_id,
        output_dir=Path(args.output_dir),
        start_page=args.start_page,
        end_page=args.end_page,
        delay=args.delay,
    )
    out_path = scraper.run()
    print(f"Saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
