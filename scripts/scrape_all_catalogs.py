"""
Scrape all Issuu catalogs from issuu_catalogs.json using the text layer.
Auto-detects page count for each catalog.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://issuu.com/",
}
SKIP_BRANDS = {"Cobb Realty"}  # non-fireworks


def detect_page_count(cdn_id: str, hint: int = 200) -> int:
    """Binary search for the last valid page."""
    # First check if even page 1 works
    url = f"https://svg.issuu.com/{cdn_id}/page_1.html"
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return 0

    lo, hi = 1, hint
    # Expand upper bound if needed
    while True:
        url = f"https://svg.issuu.com/{cdn_id}/page_{hi}.html"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            hi *= 2
        else:
            break

    # Binary search
    while lo < hi - 1:
        mid = (lo + hi) // 2
        url = f"https://svg.issuu.com/{cdn_id}/page_{mid}.html"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            lo = mid
        else:
            hi = mid
        time.sleep(0.1)

    return lo


def slug_from_catalog(cat: dict) -> str:
    brand = cat["brand"].lower()
    year = str(cat["year"])
    replacements = {
        "world class / jakes": "jakes",
        "world class": "jakes",
        "red rhino": "red_rhino",
        "cutting edge": "cutting_edge",
        "far east importing": "far_east",
        "unknown": "unknown",
    }
    for k, v in replacements.items():
        if k in brand:
            return v
    return brand.replace(" ", "_").replace("/", "_")


def main():
    catalogs_json = SCRIPTS_DIR / "issuu_catalogs.json"
    catalogs = json.loads(catalogs_json.read_text(encoding="utf-8"))

    for cat in catalogs:
        if cat["brand"] in SKIP_BRANDS:
            print(f"SKIP {cat['title']} (non-fireworks)")
            continue

        cdn_id = cat["cdn_id"]
        year = str(cat["year"])
        slug = slug_from_catalog(cat)
        out_path = SCRIPTS_DIR / "catalogs" / slug / year / "text_layer.json"

        if out_path.exists():
            print(f"DONE {cat['title']} - already scraped, skipping")
            continue

        print(f"\n{'='*60}")
        print(f"Detecting pages: {cat['title']}")
        page_count = detect_page_count(cdn_id)
        if page_count == 0:
            print(f"  SKIP — CDN not responding for {cdn_id}")
            continue
        print(f"  Pages: {page_count}")

        (SCRIPTS_DIR / "catalogs" / slug / year).mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "scrape_issuu_text.py"),
            "--cdn-id", cdn_id,
            "--slug", slug,
            "--year", year,
            "--pages", str(page_count),
            "--start-page", "5",
            "--delay", "0.2",
        ]
        print(f"  Running scraper...")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            print(f"  ERROR scraping {cat['title']}")
        time.sleep(1)

    print("\n\nAll done.")


if __name__ == "__main__":
    main()
