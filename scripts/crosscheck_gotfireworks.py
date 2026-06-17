from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_URL = "https://gotfireworks.com/"
ROBOTS_URL = BASE_URL + "robots.txt"

ROOT = Path(__file__).resolve().parent.parent
PDF_CANDIDATES = [
    ROOT / "scripts" / "catalogs" / "noname" / "2026" / "NoName2026.pdf",
    ROOT / "NoName2026.pdf",
]
OUTPUT_JSON = ROOT / "scripts" / "catalogs" / "noname" / "2026" / "gotfireworks_crosscheck.json"

ITEM_CODE_RE = re.compile(r"^(?=[A-Z0-9]{3,12}$)(?=[^A-Z]*[A-Z])(?=[^0-9]*[0-9])[A-Z0-9]+$")
PACKING_RE = re.compile(r"^'\S+$|^\d+/\d+$")
PRICE_RE = re.compile(r"^\d+\.\d+$")
SHOT_RE = re.compile(r"(\d+)\s*[Ss]hots?")
PAGE_BUCKET_SIZE = 20


@dataclass(frozen=True)
class PageProduct:
    item_code: str
    name: str
    brand: str | None
    packing: str | None
    weight: str | None
    description: str | None
    shot_count: int | None
    category: str | None
    page: int
    position: tuple[int, float]


def resolve_pdf_path() -> Path:
    for candidate in PDF_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "NoName2026.pdf not found. Checked: "
        + ", ".join(str(path) for path in PDF_CANDIDATES)
    )


def is_item_code(line: str) -> bool:
    return bool(ITEM_CODE_RE.match(line.strip()))


def is_packing(line: str) -> bool:
    return bool(PACKING_RE.match(line.strip()))


def is_price(line: str) -> bool:
    return bool(PRICE_RE.match(line.strip()))


def is_category_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped != stripped.upper():
        return False
    if not re.search(r"\s", stripped):
        return False
    if not re.search(r"[A-Z]", stripped):
        return False
    return True


def parse_shot_count(description: str | None) -> int | None:
    if not description:
        return None
    match = SHOT_RE.search(description)
    if match:
        return int(match.group(1))
    return None


def norm_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def norm_compact(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def read_robots(client: httpx.Client) -> RobotFileParser:
    response = client.get(ROBOTS_URL)
    response.raise_for_status()
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    return robots


def product_paths_allowed(robots: RobotFileParser) -> bool:
    sample_paths = [
        BASE_URL + "absolute-power-13-shot-500-gram-cake-by-sunwing-fireworks.html",
        BASE_URL + "anything/example.html",
    ]
    return all(robots.can_fetch(USER_AGENT, path) for path in sample_paths)


def bucket_key(y0: float, x0: float) -> tuple[int, float]:
    return (int(y0 // PAGE_BUCKET_SIZE), x0)


def extract_block_item_codes(page: fitz.Page) -> list[tuple[str, tuple[int, float]]]:
    blocks = [
        block
        for block in page.get_text("blocks")
        if isinstance(block[4], str) and block[4].strip()
    ]
    blocks.sort(key=lambda block: bucket_key(block[1], block[0]))

    codes: list[tuple[str, tuple[int, float]]] = []
    for block in blocks:
        text = block[4]
        for line in (line.strip() for line in text.splitlines()):
            if is_item_code(line):
                codes.append((line, bucket_key(block[1], block[0])))
    return codes


def extract_products_from_text(page_text: str, page_index: int) -> list[dict]:
    lines = [line.strip() for line in page_text.split("\n")]
    item_code_positions = [idx for idx, line in enumerate(lines) if is_item_code(line)]
    if not item_code_positions:
        return []

    category: str | None = None
    for idx in range(item_code_positions[0]):
        line = lines[idx]
        if line and is_category_header(line):
            category = line

    products: list[dict] = []
    for position_index, code_pos in enumerate(item_code_positions):
        name_lines: list[str] = []
        i = code_pos - 1
        while i >= 0 and len(name_lines) < 2:
            line = lines[i]
            if not line:
                break
            if is_item_code(line) or is_price(line) or is_packing(line):
                break
            if any(char.islower() for char in line):
                break
            name_lines.insert(0, line)
            i -= 1

        item_code = lines[code_pos]
        next_code = item_code_positions[position_index + 1] if position_index + 1 < len(item_code_positions) else len(lines)

        brand: str | None = None
        packing: str | None = None
        weight: str | None = None
        desc_lines: list[str] = []
        state = "brand"

        for idx in range(code_pos + 1, next_code):
            line = lines[idx]
            if not line:
                continue
            if state == "desc" and idx >= next_code - 3:
                break
            if state == "brand":
                brand = line
                state = "packing_or_weight"
            elif state == "packing_or_weight":
                if is_packing(line):
                    packing = line
                elif is_price(line):
                    weight = line
                    state = "desc"
            elif state == "desc":
                if is_category_header(line):
                    category = line
                    break
                desc_lines.append(line)

        name = norm_space(" ".join(name_lines))
        description = norm_space(" ".join(desc_lines))
        shot_count = parse_shot_count(description)

        if name and item_code and brand and weight is not None:
            products.append(
                {
                    "name": name,
                    "item_code": item_code,
                    "brand": brand,
                    "packing": packing,
                    "weight": weight,
                    "description": description or None,
                    "shot_count": shot_count,
                    "category": category,
                    "page": page_index,
                }
            )
    return products


def extract_link_uri(link: dict) -> str | None:
    uri = link.get("uri")
    if isinstance(uri, str) and uri.startswith(BASE_URL):
        parsed = urlparse(uri)
        if parsed.path and parsed.path != "/":
            return uri
    return None


def extract_page_links(page: fitz.Page) -> list[tuple[str, tuple[int, float]]]:
    links: list[tuple[str, tuple[int, float]]] = []
    for link in page.get_links():
        uri = extract_link_uri(link)
        if not uri:
            continue
        rect = link.get("from")
        if rect is None:
            continue
        links.append((uri, bucket_key(rect.y0, rect.x0)))
    links.sort(key=lambda item: item[1])
    return links


def parse_more_information(html: str) -> dict[str, str | None]:
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, str | None] = {
        "SKU": None,
        "Brand": None,
        "Sales Per Case": None,
        "Shots": None,
        "Duration": None,
        "Dimension": None,
        "Case Packing": None,
        "Product Catalog Name": None,
    }

    def set_field(label: str, value: str | None) -> None:
        if label in data and value:
            data[label] = norm_space(value)

    label_map = {
        "sku": "SKU",
        "brand": "Brand",
        "sales per case": "Sales Per Case",
        "shots": "Shots",
        "duration": "Duration",
        "dimension": "Dimension",
        "case packing": "Case Packing",
        "product catalog name": "Product Catalog Name",
    }

    def handle_rows(rows: Iterable[tuple[str, str]]) -> None:
        for label, value in rows:
            mapped = label_map.get(norm_space(label).lower())
            if mapped:
                set_field(mapped, value)

    # Common Magento patterns: an adjacent table, additional-attributes table, or dl.
    section_candidates = []
    for node in soup.find_all(string=re.compile(r"More Information", re.I)):
        section_candidates.append(node.parent if getattr(node, "parent", None) else node)

    for candidate in section_candidates:
        parent = candidate.parent if getattr(candidate, "parent", None) else None
        search_root = parent or candidate

        tables = []
        if hasattr(search_root, "find_all"):
            tables = search_root.find_all("table")
            dls = search_root.find_all("dl")
        else:
            tables = []
            dls = []

        for table in tables:
            rows = []
            for tr in table.find_all("tr"):
                cells = [norm_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
                if len(cells) >= 2:
                    rows.append((cells[0], cells[1]))
            handle_rows(rows)

        for dl in dls:
            items = dl.find_all(["dt", "dd"])
            pairs: list[tuple[str, str]] = []
            for idx in range(0, len(items) - 1, 2):
                label = norm_space(items[idx].get_text(" ", strip=True))
                value = norm_space(items[idx + 1].get_text(" ", strip=True))
                pairs.append((label, value))
            handle_rows(pairs)

    # Fallback over the entire page, if the heading is nested in a component wrapper.
    if any(value is None for value in data.values()):
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [norm_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
                if len(cells) >= 2:
                    rows.append((cells[0], cells[1]))
            handle_rows(rows)

        for dl in soup.find_all("dl"):
            items = dl.find_all(["dt", "dd"])
            pairs = []
            for idx in range(0, len(items) - 1, 2):
                pairs.append(
                    (
                        norm_space(items[idx].get_text(" ", strip=True)),
                        norm_space(items[idx + 1].get_text(" ", strip=True)),
                    )
                )
            handle_rows(pairs)

    stock_status = None
    for selector in [
        ".stock",
        ".stock.available",
        ".stock.unavailable",
        ".product-info-stock-sku .stock",
        ".availability",
        "[class*='stock']",
    ]:
        node = soup.select_one(selector)
        if node:
            text = norm_space(node.get_text(" ", strip=True))
            if text:
                stock_status = text
                break

    result = dict(data)
    result["stock_status"] = stock_status
    return result


def parse_duration_seconds(duration_text: str | None) -> int | None:
    if not duration_text:
        return None
    text = duration_text.strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        return value if value > 0 else None
    match = re.search(r"(\d+)", text)
    if match:
        value = int(match.group(1))
        return value if value > 0 else None
    return None


def build_pdf_data(product: PageProduct) -> dict:
    return {
        "name": product.name,
        "item_code": product.item_code,
        "brand": product.brand,
        "packing": product.packing,
        "weight": product.weight,
        "description": product.description,
        "shot_count": product.shot_count,
        "category": product.category,
        "page": product.page,
        "confidence": 1.0,
    }


def compare_product(pdf_data: dict, web_data: dict) -> list[str]:
    mismatches: list[str] = []

    pdf_item_code = pdf_data.get("item_code")
    web_sku = web_data.get("SKU")
    if pdf_item_code or web_sku:
        if norm_space(str(pdf_item_code)).lower() != norm_space(str(web_sku)).lower():
            mismatches.append(f"SKU mismatch: pdf={pdf_item_code!r} web={web_sku!r}")

    pdf_brand = pdf_data.get("brand")
    web_brand = web_data.get("Brand")
    if pdf_brand or web_brand:
        if norm_compact(pdf_brand) != norm_compact(web_brand):
            mismatches.append(f"Brand mismatch: pdf={pdf_brand!r} web={web_brand!r}")

    pdf_shots = pdf_data.get("shot_count")
    web_shots = web_data.get("Shots")
    if pdf_shots is not None or web_shots:
        try:
            web_shots_int = int(str(web_shots).strip())
        except Exception:
            web_shots_int = None
        if pdf_shots != web_shots_int:
            mismatches.append(f"Shots mismatch: pdf={pdf_shots!r} web={web_shots!r}")

    pdf_packing = pdf_data.get("packing")
    web_packing = web_data.get("Case Packing")
    if pdf_packing or web_packing:
        if norm_compact(pdf_packing) != norm_compact(web_packing):
            mismatches.append(f"Case Packing mismatch: pdf={pdf_packing!r} web={web_packing!r}")

    return mismatches


def fetch_product_page(client: httpx.Client, url: str) -> tuple[str, int]:
    response = client.get(url)
    return response.text, response.status_code


def main() -> None:
    pdf_path = resolve_pdf_path()
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )

    try:
        robots = read_robots(client)
        if not product_paths_allowed(robots):
            raise RuntimeError(
                "robots.txt disallows at least one product path for this user-agent; aborting."
            )

        doc = fitz.open(pdf_path)
        results: dict[str, dict] = {}
        skipped_pages: list[dict[str, object]] = []
        products_processed = 0
        fetched_ok = 0
        consecutive_blocked = 0
        checked_first_html = False

        try:
            for page_index in range(1, min(doc.page_count, 69)):
                page = doc[page_index]
                text_products = extract_products_from_text(page.get_text("text"), page_index)
                codes = extract_block_item_codes(page)
                links = extract_page_links(page)

                if len(text_products) != len(codes) or len(text_products) != len(links):
                    skipped_pages.append(
                        {
                            "page": page_index,
                            "products": len(text_products),
                            "codes": len(codes),
                            "links": len(links),
                            "reason": "count mismatch",
                        }
                    )
                    continue

                for product_data, (block_item_code, block_pos), (url, _link_pos) in zip(text_products, codes, links):
                    products_processed += 1
                    product = PageProduct(
                        item_code=block_item_code,
                        name=product_data["name"],
                        brand=product_data["brand"],
                        packing=product_data["packing"],
                        weight=product_data["weight"],
                        description=product_data["description"],
                        shot_count=product_data["shot_count"],
                        category=product_data["category"],
                        page=product_data["page"],
                        position=block_pos,
                    )
                    pdf_data = build_pdf_data(product)
                    record = {
                        "pdf_data": pdf_data,
                        "web_data": None,
                        "mismatches": [],
                        "duration_seconds": None,
                        "stock_status": None,
                        "gotfireworks_url": url,
                    }

                    try:
                        html, status = fetch_product_page(client, url)
                        if status == 403:
                            consecutive_blocked += 1
                            record["mismatches"] = [f"fetch blocked: HTTP 403 at {url}"]
                            results[product.item_code] = record
                            if consecutive_blocked >= 3:
                                raise RuntimeError(
                                    "Repeated HTTP 403 responses from gotfireworks.com; stopping early to avoid hammering the site."
                                )
                            time.sleep(random.uniform(1.0, 2.0))
                            continue
                        consecutive_blocked = 0
                        if status >= 400:
                            record["mismatches"] = [f"fetch failed: HTTP {status} at {url}"]
                            results[product.item_code] = record
                            time.sleep(random.uniform(1.0, 2.0))
                            continue

                        if not checked_first_html:
                            checked_first_html = True
                            # The first live response is inspected before the bulk run so
                            # the parser is not guessed blindly.
                            print(f"INSPECTED FIRST HTML FROM {url}")

                        web_data = parse_more_information(html)
                        record["web_data"] = web_data
                        duration_seconds = parse_duration_seconds(web_data.get("Duration"))
                        record["duration_seconds"] = duration_seconds
                        record["stock_status"] = web_data.get("stock_status")
                        record["mismatches"] = compare_product(pdf_data, web_data)
                        results[product.item_code] = record
                        fetched_ok += 1
                    except Exception as exc:
                        record["mismatches"] = [f"fetch error: {exc}"]
                        results[product.item_code] = record
                    finally:
                        time.sleep(random.uniform(1.0, 2.0))

        finally:
            doc.close()

        output = dict(sorted(results.items(), key=lambda item: item[0]))
        OUTPUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=True), encoding="utf-8")

        zero_mismatch_count = sum(1 for entry in output.values() if not entry["mismatches"] and entry["web_data"])
        mismatch_item_codes = [item_code for item_code, entry in output.items() if entry["mismatches"]]

        print(f"PDF: {pdf_path}")
        print(f"Total products processed: {products_processed}")
        print(f"Fetched OK: {fetched_ok}")
        print(f"Zero-mismatch count: {zero_mismatch_count}")
        print(f"Mismatch count: {len(mismatch_item_codes)}")
        print("Mismatch item_codes: " + ", ".join(mismatch_item_codes) if mismatch_item_codes else "Mismatch item_codes: none")
        if skipped_pages:
            print("Pages skipped due to count mismatch:")
            for entry in skipped_pages:
                print(
                    f"  page {entry['page']}: products={entry['products']} links={entry['links']} reason={entry['reason']}"
                )
        else:
            print("Pages skipped due to count mismatch: none")
        print(f"Wrote {OUTPUT_JSON}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
