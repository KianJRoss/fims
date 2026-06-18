from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.media import ProductVideo
from app.models.product import Product
from app.worker.tasks.video_download import download_video
from app.worker.tasks.video_search import find_product_videos

router = APIRouter()
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/app/media")


class ConfirmBody(BaseModel):
    confirmed: bool
    is_primary: bool | None = None


def video_to_dict(video: ProductVideo) -> dict:
    return {
        "id": video.id,
        "product_id": video.product_id,
        "file_path": video.file_path,
        "source": video.source,
        "url": video.url,
        "youtube_id": video.youtube_id,
        "title": video.title,
        "thumbnail_url": video.thumbnail_url,
        "search_query": video.search_query,
        "confirmed": video.confirmed,
        "download_status": video.download_status,
        "original_filename": video.original_filename,
        "duration_seconds": video.duration_seconds,
        "is_primary": video.is_primary,
        "uploaded_at": video.uploaded_at,
        "downloaded": bool(video.file_path and video.confirmed),
    }


@router.get("/product/{product_id}")
def list_product_videos(product_id: str, db: Session = Depends(get_db)):
    videos = (
        db.query(ProductVideo)
        .filter(ProductVideo.product_id == product_id)
        .order_by(ProductVideo.confirmed.desc(), ProductVideo.is_primary.desc(), ProductVideo.uploaded_at.desc())
        .all()
    )
    return [video_to_dict(video) for video in videos]


@router.post("/product/{product_id}/search")
def search_product_videos(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    find_product_videos.delay(str(product_id), product.name, product.item_number)
    return {"queued": True, "product_id": product_id}


@router.post("/product/{product_id}/no-video")
def mark_product_no_video(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.no_video_confirmed = True
    db.commit()
    return {"ok": True, "product_id": product_id, "no_video_confirmed": True}


@router.patch("/{video_id}/confirm")
def confirm_video(video_id: int, body: ConfirmBody, db: Session = Depends(get_db)):
    video = db.query(ProductVideo).filter(ProductVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if body.is_primary is True:
        db.execute(
            update(ProductVideo)
            .where(ProductVideo.product_id == video.product_id, ProductVideo.id != video.id, ProductVideo.is_primary.is_(True))
            .values(is_primary=False)
        )

    video.confirmed = body.confirmed
    if body.is_primary is not None:
        video.is_primary = body.is_primary

    if body.confirmed and not video.file_path:
        download_video.delay(video.id)

    db.commit()
    db.refresh(video)
    return video_to_dict(video)


@router.delete("/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(ProductVideo).filter(ProductVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video.file_path:
        media_root_abs = os.path.abspath(MEDIA_ROOT)
        full_path = os.path.abspath(os.path.normpath(os.path.join(media_root_abs, video.file_path)))
        if os.path.commonpath([media_root_abs, full_path]) == media_root_abs and os.path.exists(full_path):
            os.remove(full_path)

    db.delete(video)
    db.commit()
    return Response(status_code=204)


@router.get("/{video_id}/status")
def get_video_status(video_id: int, db: Session = Depends(get_db)):
    video = db.query(ProductVideo).filter(ProductVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    return {
        "id": video.id,
        "confirmed": video.confirmed,
        "file_path": video.file_path,
        "downloaded": bool(video.file_path and video.confirmed),
        "duration_seconds": video.duration_seconds,
        "download_status": video.download_status,
    }
