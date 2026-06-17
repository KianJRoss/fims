from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fims:fims@localhost:5432/fims",
).replace("postgresql+psycopg://", "postgresql://")

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent
EXPECTED_PDF = ROOT_DIR / "scripts" / "catalogs" / "noname" / "2026" / "NoName2026.pdf"
FALLBACK_PDF = ROOT_DIR / "NoName2026.pdf"
PREVIEW_JSON = ROOT_DIR / "scripts" / "catalogs" / "noname" / "2026" / "noname_parsed_preview.json"
MEDIA_PRODUCT_DIR = ROOT_DIR / "media" / "product_images"

ITEM_CODE_RE = re.compile(r"^(?=[A-Z0-9/\-]{3,20}$)(?=.*[A-Z])(?=.*\d)[A-Z0-9/\-]+$")
PACKING_RE = re.compile(r"^'\S+$|^\d+(?:/\d+)+$")
WEIGHT_RE = re.compile(r"^\d+\.\d+$")
SHOT_RE = re.compile(r"(\d+)\s*[Ss]hots?")
FOOTER_RE = re.compile(r"^(?:\d+|www\.|powered by tcpdf|gotfireworks\.com)", re.IGNORECASE)


def resolve_pdf_path(cli_path: str | None = None) -> Path:
    candidates = []
    if cli_path:
        candidates.append(Path(cli_path))
    candidates.extend([EXPECTED_PDF, FALLBACK_PDF])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find NoName2026.pdf. Looked at: {', '.join(str(path) for path in candidates)}"
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def is_item_code(line: str) -> bool:
    return bool(ITEM_CODE_RE.match(line.strip()))


def is_packing(line: str) -> bool:
    return bool(PACKING_RE.match(line.strip()))


def is_weight(line: str) -> bool:
    return bool(WEIGHT_RE.match(line.strip()))


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
    if is_item_code(stripped) or is_weight(stripped):
        return False
    return True


def is_footer_line(line: str) -> bool:
    stripped = line.strip()
    return bool(FOOTER_RE.search(stripped))


def safe_image_stem(item_code: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", item_code).strip("._-") or "unknown"


def cell_index_from_splits(x_split: float, y_split_1: float, y_split_2: float, x: float, y: float) -> int:
    col = 0 if x < x_split else 1
    if y < y_split_1:
        row = 0
    elif y < y_split_2:
        row = 1
    else:
        row = 2
    if row < 0:
        row = 0
    if row > 2:
        row = 2
    return row * 2 + col


def collect_text_blocks(page: Any) -> list[tuple[float, float, float, float, str]]:
    blocks: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        if len(block) >= 7 and block[6] not in (0, "0", None):
            continue
        x0, y0, x1, y1, text = block[:5]
        clean_text = str(text or "").strip()
        if not clean_text:
            continue
        blocks.append((float(x0), float(y0), float(x1), float(y1), clean_text))
    return blocks


def collect_image_infos(page: Any) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    seen: set[tuple[int, tuple[float, float, float, float]]] = set()

    for block in page.get_text("blocks"):
        if len(block) < 7:
            continue
        block_type = block[6]
        if block_type not in (1, "1"):
            continue
        x0, y0, x1, y1 = block[:4]
        bbox_tuple = (float(x0), float(y0), float(x1), float(y1))
        key = (0, bbox_tuple)
        if key in seen:
            continue
        seen.add(key)
        infos.append({"xref": 0, "bbox": bbox_tuple, "source": "text_block_image"})

    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        if not bbox:
            continue
        xref = int(info.get("xref") or 0)
        bbox_tuple = tuple(float(value) for value in bbox)
        key = (xref, bbox_tuple)
        if key in seen:
            continue
        seen.add(key)
        infos.append({"xref": xref, "bbox": bbox_tuple, "source": "image_info"})

    try:
        for image in page.get_images(full=True):
            if not image:
                continue
            xref = int(image[0] or 0)
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            for rect in rects:
                bbox_tuple = tuple(float(value) for value in rect)
                key = (xref, bbox_tuple)
                if key in seen:
                    continue
                seen.add(key)
                infos.append({"xref": xref, "bbox": bbox_tuple, "source": "get_images"})
    except Exception:
        pass

    if len(infos) > 1:
        areas = []
        for info in infos:
            bbox = info.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = bbox
            areas.append((x1 - x0) * (y1 - y0))
        if areas:
            areas_sorted = sorted(areas)
            median_area = areas_sorted[len(areas_sorted) // 2]
            low = median_area * 0.5
            high = median_area * 1.8
            filtered = []
            for info in infos:
                bbox = info.get("bbox")
                if not bbox:
                    continue
                x0, y0, x1, y1 = bbox
                area = (x1 - x0) * (y1 - y0)
                if low <= area <= high:
                    filtered.append(info)
            if len(filtered) >= 1:
                infos = filtered

    return infos


def layout_splits(
    text_blocks: list[tuple[float, float, float, float, str]],
    image_infos: list[dict[str, Any]],
    page: Any,
) -> tuple[float, float, float]:
    xs: list[float] = []
    for info in image_infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        x0, _y0, x1, _y1 = bbox
        xs.append((float(x0) + float(x1)) / 2.0)
    if xs:
        x_split = (min(xs) + max(xs)) / 2.0
    else:
        xs = [((x0 + x1) / 2.0) for x0, _y0, x1, _y1, _text in text_blocks]
        if xs:
            x_split = (min(xs) + max(xs)) / 2.0
        else:
            x_split = page.rect.width / 2.0

    ys: list[float] = []
    for info in image_infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        _x0, y0, _x1, y1 = bbox
        ys.append((float(y0) + float(y1)) / 2.0)
    ys_unique = sorted({round(value, 3) for value in ys})
    if len(ys_unique) >= 3:
        y_split_1 = (ys_unique[0] + ys_unique[1]) / 2.0
        y_split_2 = (ys_unique[1] + ys_unique[2]) / 2.0
    elif len(ys) >= 3:
        ys_sorted = sorted(ys)
        y_split_1 = (ys_sorted[0] + ys_sorted[len(ys_sorted) // 3]) / 2.0
        y_split_2 = (ys_sorted[(len(ys_sorted) * 2) // 3] + ys_sorted[-1]) / 2.0
    else:
        y_split_1 = page.rect.height / 3.0
        y_split_2 = (page.rect.height / 3.0) * 2.0

    return x_split, y_split_1, y_split_2


def group_text_blocks(
    page: Any,
    splits: tuple[float, float, float],
) -> dict[int, list[tuple[float, float, str]]]:
    grouped: dict[int, list[tuple[float, float, str]]] = {}
    x_split, y_split_1, y_split_2 = splits
    for x0, y0, x1, y1, text in collect_text_blocks(page):
        idx = cell_index_from_splits(x_split, y_split_1, y_split_2, x0, y0)
        grouped.setdefault(idx, []).append((float(y0), float(x0), text))
    return grouped


def group_images(
    page: Any,
    splits: tuple[float, float, float],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    x_split, y_split_1, y_split_2 = splits
    for info in collect_image_infos(page):
        bbox = info.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        idx = cell_index_from_splits(x_split, y_split_1, y_split_2, float(x0), float(y0))
        grouped.setdefault(idx, []).append(info)
    return grouped


def _extract_image_png(doc: Any, page: Any, image_info: dict[str, Any], out_path: Path) -> None:
    import fitz

    xref = int(image_info.get("xref") or 0)
    bbox = image_info.get("bbox")
    if xref > 0:
        pixmap = fitz.Pixmap(doc, xref)
        try:
            if pixmap.n > 4:
                pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
            pixmap.save(str(out_path))
        finally:
            pixmap = None
        return

    if not bbox:
        raise RuntimeError("Cannot render image without a bbox")
    clip = fitz.Rect(bbox)
    pixmap = page.get_pixmap(clip=clip, alpha=False)
    pixmap.save(str(out_path))


def parse_cluster(lines: list[str]) -> dict[str, Any] | None:
    if not lines:
        return None

    item_idx = next((idx for idx, line in enumerate(lines) if is_item_code(line)), None)
    if item_idx is None:
        return None

    name = " ".join(lines[:item_idx]).strip() or None
    item_code = lines[item_idx].strip()

    if item_idx + 1 >= len(lines):
        return None

    brand = lines[item_idx + 1].strip() or None
    cursor = item_idx + 2
    packing = None
    weight = None

    if cursor < len(lines) and is_packing(lines[cursor]):
        packing = lines[cursor].strip()
        cursor += 1

    if cursor < len(lines) and is_weight(lines[cursor]):
        weight = float(lines[cursor])
        cursor += 1
    else:
        return None

    tail_lines = lines[cursor:]
    description_parts: list[str] = []
    category_candidates: list[str] = []
    shot_count = None

    for line in tail_lines:
        if is_footer_line(line):
            continue
        shot_match = SHOT_RE.search(line)
        if shot_count is None and shot_match:
            shot_count = int(shot_match.group(1))
            continue
        if is_category_header(line):
            category_candidates.append(line.strip())
            continue
        description_parts.append(line.strip())

    description = " ".join(part for part in description_parts if part).strip() or None
    category = category_candidates[-1] if category_candidates else None

    return {
        "name": name,
        "item_code": item_code,
        "brand": brand,
        "packing": packing,
        "weight": weight,
        "description": description,
        "shot_count": shot_count,
        "category": category,
    }


def confidence_for_row(row: dict[str, Any]) -> float:
    confidence = 1.0
    if not row.get("name"):
        confidence -= 0.15
    if not row.get("brand"):
        confidence -= 0.15
    if not row.get("packing"):
        confidence -= 0.05
    if row.get("weight") is None:
        confidence -= 0.25
    if not row.get("description"):
        confidence -= 0.15
    if row.get("shot_count") is None:
        confidence -= 0.05
    if not row.get("category"):
        confidence -= 0.1
    return max(0.0, round(confidence, 2))


def build_rows(pdf_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    import fitz

    rows: list[dict[str, Any]] = []
    skipped_pages: list[dict[str, Any]] = []
    saved_images = 0
    debug = os.getenv("NONAME_DEBUG") == "1"

    doc = fitz.open(str(pdf_path))
    try:
        for page_index in range(2, doc.page_count):
            page = doc[page_index]
            if debug and page_index == 14:
                raw_blocks = page.get_text("blocks")
                type_counts = Counter()
                for block in raw_blocks:
                    if len(block) >= 7:
                        type_counts[block[6]] += 1
                print(f"DEBUG page 14 raw blocks: {len(raw_blocks)}")
                print(f"DEBUG page 14 block types: {dict(type_counts)}")
                for idx, block in enumerate(raw_blocks[:18]):
                    bbox = tuple(float(value) for value in block[:4])
                    text = str(block[4] or "").replace("\n", " ")
                    print(f"DEBUG block {idx}: type={block[6] if len(block) >= 7 else 'n/a'} bbox={bbox} text={text[:120]!r}")
                raw_images = page.get_image_info(xrefs=True)
                print(f"DEBUG page 14 image_info count: {len(raw_images)}")
                for idx, info in enumerate(raw_images[:10]):
                    bbox = tuple(float(value) for value in info.get("bbox") or ())
                    width = float(info.get("width") or 0)
                    height = float(info.get("height") or 0)
                    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) if len(bbox) == 4 else 0
                    print(
                        f"DEBUG image {idx}: xref={info.get('xref')} bbox={bbox} "
                        f"px={width}x{height} area={area:.1f}"
                    )
                try:
                    print(f"DEBUG page 2 get_images count: {len(page.get_images(full=True))}")
                except Exception as exc:
                    print(f"DEBUG page 2 get_images error: {exc}")
            text_blocks = collect_text_blocks(page)
            image_infos = collect_image_infos(page)
            splits = layout_splits(text_blocks, image_infos, page)
            text_groups = group_text_blocks(page, splits)
            image_groups = group_images(page, splits)
            if debug and page_index == 14:
                print(f"DEBUG page 14 filtered image count: {len(image_infos)}")
                for idx, info in enumerate(image_infos):
                    bbox = info.get("bbox")
                    if bbox:
                        cell = cell_index_from_splits(splits[0], splits[1], splits[2], float(bbox[0]), float(bbox[1]))
                    else:
                        cell = None
                    print(f"DEBUG filtered image {idx}: cell={cell} info={info}")
                print(f"DEBUG page 14 grouped text cells: {sorted(text_groups)}")
                print(f"DEBUG page 14 grouped image cells: {sorted(image_groups)}")

            text_cells = sorted(text_groups)
            image_cells = sorted(image_groups)

            if not text_cells or not image_cells or text_cells != image_cells:
                skipped_pages.append(
                    {
                        "page": page_index,
                        "reason": (
                            f"text cells {text_cells or []} did not match image cells {image_cells or []}"
                        ),
                    }
                )
                continue

            if any(len(text_groups[cell]) == 0 for cell in text_cells) or any(
                len(image_groups[cell]) != 1 for cell in image_cells
            ):
                skipped_pages.append(
                    {
                        "page": page_index,
                        "reason": "one or more grid cells had an unexpected number of text blocks or images",
                    }
                )
                continue

            page_rows: list[dict[str, Any]] = []
            for cell in text_cells:
                cell_lines: list[str] = []
                for _y0, _x0, text in sorted(text_groups[cell], key=lambda item: (item[0], item[1])):
                    cell_lines.extend(normalize_lines(text))

                parsed = parse_cluster(cell_lines)
                if not parsed or not parsed.get("item_code"):
                    if debug and page_index == 14:
                        print(f"DEBUG page 14 cell {cell} lines: {cell_lines}")
                    skipped_pages.append(
                        {
                            "page": page_index,
                            "reason": f"unable to parse product cluster in cell {cell}",
                        }
                    )
                    page_rows = []
                    break

                image_info = image_groups[cell][0]
                image_name = f"{safe_image_stem(parsed['item_code'])}.png"
                image_path = MEDIA_PRODUCT_DIR / image_name
                ensure_dir(MEDIA_PRODUCT_DIR)
                _extract_image_png(doc, page, image_info, image_path)
                saved_images += 1

                raw_data = {
                    "name": parsed["name"],
                    "item_code": parsed["item_code"],
                    "brand": parsed["brand"],
                    "packing": parsed["packing"],
                    "weight": parsed["weight"],
                    "description": parsed["description"],
                    "shot_count": parsed["shot_count"],
                    "category": parsed["category"],
                    "page": page_index,
                    "image_path": f"product_images/{image_name}",
                    "confidence": confidence_for_row(parsed),
                }
                page_rows.append(raw_data)

            rows.extend(page_rows)
    finally:
        doc.close()

    return rows, skipped_pages, saved_images


def write_preview(rows: list[dict[str, Any]], preview_path: Path) -> None:
    ensure_dir(preview_path.parent)
    preview_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def stage_rows(pdf_path: Path, rows: list[dict[str, Any]]) -> int:
    now = datetime.now(timezone.utc)
    conn = psycopg.connect(DB_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO import_jobs (document_type, file_name, file_path, status, created_at)
                VALUES ('CATALOG', %s, %s, 'review', %s)
                RETURNING id
                """,
                ("NoName2026.pdf", str(pdf_path), now),
            )
            job_id = int(cur.fetchone()[0])

            for idx, raw_data in enumerate(rows):
                cur.execute(
                    """
                    INSERT INTO import_rows
                        (job_id, row_index, raw_data, review_status, match_confidence)
                    VALUES (%s, %s, %s, 'pending', %s)
                    """,
                    (job_id, idx, Jsonb(raw_data), raw_data["confidence"]),
                )
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse the No Name 2026 PDF catalog.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the catalog, extract images, and write a preview JSON without touching the database.",
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="Optional override for the source PDF path.",
    )
    return parser.parse_args()


def main() -> int:
    args = load_args()
    pdf_path = resolve_pdf_path(args.pdf)

    rows, skipped_pages, saved_images = build_rows(pdf_path)

    if args.dry_run:
        write_preview(rows, PREVIEW_JSON)
        print(f"Dry-run preview written to {PREVIEW_JSON}")
        print(f"Source PDF: {pdf_path}")
        print(f"Products parsed: {len(rows)}")
        print(f"Images saved: {saved_images}")
        if skipped_pages:
            print("Skipped pages:")
            for entry in skipped_pages:
                print(f"  page {entry['page']}: {entry['reason']}")
        else:
            print("Skipped pages: none")
        return 0

    job_id = stage_rows(pdf_path, rows)
    print(f"Created ImportJob {job_id} for {len(rows)} staged rows from {pdf_path}")
    if skipped_pages:
        print("Skipped pages:")
        for entry in skipped_pages:
            print(f"  page {entry['page']}: {entry['reason']}")
    else:
        print("Skipped pages: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
