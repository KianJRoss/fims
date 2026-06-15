from __future__ import annotations

import json
import re
from collections.abc import Iterable
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SEARCH_URLS = [
    "https://issuu.com/search?q=fireworks+catalog+2026&type=publication",
    "https://issuu.com/search?q=world+class+fireworks&type=publication",
    "https://issuu.com/search?q=red+rhino+fireworks&type=publication",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
URL_RE = re.compile(r"https?://(?:www\.)?issuu\.com/[^\s\"'<>]+", re.IGNORECASE)
PUBLICATION_RE = re.compile(r"/(?:docs|publication|viewer|catalog|booklet)/", re.IGNORECASE)


def clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def add_result(results: list[tuple[str, str]], seen: set[str], title: str | None, url: str | None) -> None:
    clean_title = clean_text(title)
    clean_url = clean_text(url)
    if not clean_title or not clean_url:
        return
    normalized = urljoin("https://issuu.com/", clean_url)
    if "issuu.com" not in normalized:
        return
    if normalized in seen:
        return
    seen.add(normalized)
    results.append((clean_title, normalized))


def results_from_anchors(soup: BeautifulSoup) -> Iterable[tuple[str, str]]:
    for anchor in soup.find_all("a", href=True):
        href = urljoin("https://issuu.com/", anchor["href"])
        text = clean_text(anchor.get_text(" ", strip=True))
        if not text or "issuu.com" not in href:
            continue
        if not PUBLICATION_RE.search(href):
            continue
        yield text, href


def iter_json_like_blobs(script_text: str) -> Iterable[Any]:
    candidate = script_text.strip()
    if not candidate:
        return []

    if candidate.startswith("{") or candidate.startswith("["):
        try:
            return [json.loads(candidate)]
        except json.JSONDecodeError:
            pass

    for opening, closing in (("{", "}"), ("[", "]")):
        start = candidate.find(opening)
        end = candidate.rfind(closing)
        if start != -1 and end != -1 and end > start:
            snippet = candidate[start : end + 1]
            try:
                return [json.loads(snippet)]
            except json.JSONDecodeError:
                continue
    return []


def walk_json(value: Any) -> Iterable[tuple[str | None, str | None]]:
    if isinstance(value, dict):
        title = value.get("title") or value.get("name") or value.get("headline")
        url = (
            value.get("url")
            or value.get("href")
            or value.get("link")
            or value.get("canonicalUrl")
            or value.get("publicationUrl")
            or value.get("viewerUrl")
        )
        if isinstance(url, str) and url:
            yield str(title) if title else None, url

        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for item in value:
            yield from walk_json(item)
    elif isinstance(value, str):
        for match in URL_RE.findall(value):
            yield None, match


def extract_results_from_scripts(soup: BeautifulSoup) -> Iterable[tuple[str, str]]:
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text(" ", strip=True)
        if not script_text:
            continue
        for blob in iter_json_like_blobs(script_text):
            yield from walk_json(blob)
        for match in URL_RE.findall(script_text):
            yield None, match


def fetch_results(url: str) -> list[tuple[str, str]]:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    for title, href in results_from_anchors(soup):
        add_result(results, seen, title, href)

    for title, href in extract_results_from_scripts(soup):
        add_result(results, seen, title, href)

    return results


def main() -> int:
    for search_url in SEARCH_URLS:
        print(search_url)
        try:
            results = fetch_results(search_url)
        except Exception as exc:
            print(f"  error: {exc}")
            continue

        for title, url in results:
            print(f"  {title} - {url}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
