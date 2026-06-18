from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import column, nullslast, or_, select, table
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pricing import PriceType, ProductPrice
from app.models.product import Product, ProductCategory

router = APIRouter()


class IdleFilterRequest(BaseModel):
    brand_id: list[int] = Field(default_factory=list)
    category: str | None = None
    in_store: bool | None = None
    q: str | None = None

product_videos_table = table(
    "product_videos",
    column("product_id"),
    column("video_filename"),
    column("is_primary"),
    column("uploaded_at"),
)


class PlayRequest(BaseModel):
    product_id: str | None = None
    file_path: str | None = Field(default=None, min_length=1)


def get_video_pi_url() -> str | None:
    value = os.getenv("VIDEO_PI_URL", "").strip()
    return value.rstrip("/") if value else None


def build_video_url(file_path: str) -> str:
    filename = Path(file_path).name
    return f"http://store.local/external-videos/{quote(filename)}"


def post_to_video_pi(path: str, body: dict | None = None) -> dict:
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{video_pi_url}{path}", json=body or {})
    response.raise_for_status()
    return response.json()


def get_from_video_pi(path: str) -> dict:
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    with httpx.Client(timeout=15.0) as client:
        response = client.get(f"{video_pi_url}{path}")
    response.raise_for_status()
    return response.json()


def _normalize_video_list(payload: object) -> list[str]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, str) and item.strip()]

    if isinstance(payload, dict):
        for key in ("videos", "files", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, str) and item.strip()]

    return []


def _get_product_by_id(db: Session, product_id: str) -> Product:
    product = db.execute(select(Product).where(Product.id == product_id)).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def _get_best_product_video_filename(db: Session, product_id: str) -> tuple[bool, str | None]:
    rows = (
        db.execute(
            select(
                product_videos_table.c.video_filename,
                product_videos_table.c.is_primary,
                product_videos_table.c.uploaded_at,
            )
            .where(product_videos_table.c.product_id == product_id)
            .order_by(
                product_videos_table.c.is_primary.desc(),
                nullslast(product_videos_table.c.uploaded_at.desc()),
            )
        )
        .all()
    )
    if not rows:
        return False, None

    for row in rows:
        video_filename = (row.video_filename or "").strip()
        if video_filename:
            return True, video_filename

    return True, None


def _build_idle_playlist(item_numbers: list[str], video_filenames: list[str]) -> list[str]:
    playlist: list[str] = []
    seen_paths: set[str] = set()

    for item_number in item_numbers:
        item_number_lower = item_number.lower()
        for filename in video_filenames:
            if item_number_lower in filename.lower():
                path = f"/media/pi/VIDEOS/videos/{filename}"
                if path not in seen_paths:
                    seen_paths.add(path)
                    playlist.append(path)

    return playlist


def _build_idle_playlist_from_filenames(video_filenames_to_match: list[str], video_filenames: list[str]) -> list[str]:
    playlist: list[str] = []
    seen_paths: set[str] = set()

    for wanted_filename in video_filenames_to_match:
        wanted_lower = wanted_filename.lower()
        for filename in video_filenames:
            filename_lower = filename.lower()
            if wanted_lower == filename_lower or wanted_lower in filename_lower or filename_lower in wanted_lower:
                path = f"/media/pi/VIDEOS/videos/{filename}"
                if path not in seen_paths:
                    seen_paths.add(path)
                    playlist.append(path)

    return playlist


@router.post("/player/play")
def play_video(body: PlayRequest, db: Session = Depends(get_db)):
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    if body.product_id:
        product = _get_product_by_id(db, body.product_id)
        has_product_videos, video_filename = _get_best_product_video_filename(db, body.product_id)
        if video_filename:
            return post_to_video_pi("/play", {"file_path": f"/media/pi/VIDEOS/videos/{Path(video_filename).name}"})
        if has_product_videos:
            return {"status": "no_match", "product_id": body.product_id}

        item_number = (product.item_number or "").strip()
        if not item_number:
            return {"status": "no_match", "item_number": product.item_number}
        return post_to_video_pi("/play", {"item_number": item_number})

    if body.file_path:
        video_url = build_video_url(body.file_path)
        return post_to_video_pi("/play", {"url": video_url, "file_path": body.file_path})

    raise HTTPException(status_code=400, detail="Missing file_path or product_id")


@router.post("/player/stop")
def stop_video():
    return post_to_video_pi("/stop")


@router.post("/player/idle/filter")
def set_idle_filter(body: IdleFilterRequest, db: Session = Depends(get_db)):
    """Build the looping idle playlist from a product filter (brand/category/in_store/search)
    instead of the fixed in-store-or-high-price algorithm in /idle/sync."""
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    stmt = select(Product.id).where(Product.is_active.is_(True))
    if body.in_store is not None:
        stmt = stmt.where(Product.in_store.is_(body.in_store))
    if body.category:
        stmt = stmt.where(Product.category.has(ProductCategory.name == body.category))
    if body.brand_id:
        stmt = stmt.where(Product.brand_id.in_(body.brand_id))
    if body.q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{body.q}%"), Product.item_number.ilike(f"%{body.q}%")))

    matched_product_ids = db.execute(stmt).scalars().all()
    if not matched_product_ids:
        post_to_video_pi("/idle/playlist", {"paths": []})
        return {"status": "ok", "matched_products": 0, "video_count": 0}

    video_filenames = (
        db.execute(
            select(product_videos_table.c.video_filename)
            .where(product_videos_table.c.product_id.in_(matched_product_ids))
            .where(product_videos_table.c.video_filename.isnot(None))
        )
        .scalars()
        .all()
    )
    unique_filenames = sorted({name.strip() for name in video_filenames if name and name.strip()})
    paths = [f"/media/pi/VIDEOS/videos/{Path(name).name}" for name in unique_filenames]

    post_to_video_pi("/idle/playlist", {"paths": paths})
    # The idle loop only re-reads the playlist between full cycles, so without this a filter
    # change wouldn't actually take effect until whatever was already playing finished its
    # entire (possibly much larger/unfiltered) pass. /stop kills the current mpv process, which
    # makes the idle loop's background thread immediately rebuild and respawn from the playlist
    # we just set, instead of waiting.
    post_to_video_pi("/stop")
    return {"status": "ok", "matched_products": len(matched_product_ids), "video_count": len(paths)}


@router.post("/player/idle/sync")
def sync_idle_playlist(db: Session = Depends(get_db)):
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    paired_rows = (
        db.execute(
            select(Product.item_number, product_videos_table.c.video_filename)
            .select_from(Product)
            .join(product_videos_table, product_videos_table.c.product_id == Product.id)
            .where(
                Product.in_store.is_(True),
                Product.item_number.isnot(None),
            )
            .order_by(Product.name.asc(), Product.id.asc())
        )
        .all()
    )

    fallback_rows = (
        db.execute(
            select(Product.item_number)
            .join(ProductPrice, ProductPrice.product_id == Product.id)
            .join(PriceType, PriceType.id == ProductPrice.price_type_id)
            .where(
                or_(PriceType.name == "RETAIL", PriceType.code == "RETAIL"),
                ProductPrice.amount >= 25.00,
                Product.item_number.isnot(None),
            )
            .order_by(ProductPrice.amount.desc(), Product.id.asc())
            .limit(200)
        )
        .scalars()
        .all()
    )

    video_response = get_from_video_pi("/videos")
    video_filenames = video_response.get("videos", [])
    selected_video_filenames = [video_filename for _, video_filename in paired_rows if video_filename]
    playlist = _build_idle_playlist_from_filenames(selected_video_filenames, video_filenames)
    if not playlist:
        playlist = _build_idle_playlist([item_number for item_number in fallback_rows if item_number], video_filenames)

    post_to_video_pi("/idle/playlist", {"paths": playlist})
    return {
        "synced": len(playlist),
        "total_products": len(selected_video_filenames) if selected_video_filenames else len(fallback_rows),
    }


@router.get("/player/status")
def video_status():
    return get_from_video_pi("/status")


@router.get("/player/videos")
def list_videos():
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"videos": [], "count": 0, "error": "VIDEO_PI_URL is not set"}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{video_pi_url}/videos")
            response.raise_for_status()
            payload = response.json()
        videos = _normalize_video_list(payload)
        return {"videos": videos, "count": len(videos)}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"videos": [], "count": 0, "error": str(exc)}
