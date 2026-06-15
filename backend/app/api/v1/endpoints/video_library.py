from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pricing import PriceType, ProductPrice
from app.models.product import Product

router = APIRouter()


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


def _get_product_by_id(db: Session, product_id: str) -> Product:
    product = db.execute(select(Product).where(Product.id == product_id)).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


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


@router.post("/player/play")
def play_video(body: PlayRequest, db: Session = Depends(get_db)):
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    if body.product_id:
        product = _get_product_by_id(db, body.product_id)
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


@router.post("/player/idle/sync")
def sync_idle_playlist(db: Session = Depends(get_db)):
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    rows = (
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
    playlist = _build_idle_playlist([item_number for item_number in rows if item_number], video_filenames)

    post_to_video_pi("/idle/playlist", {"paths": playlist})
    return {"synced": len(playlist), "total_products": len(rows)}


@router.get("/player/status")
def video_status():
    return get_from_video_pi("/status")
