from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter()


class PlayRequest(BaseModel):
    file_path: str = Field(..., min_length=1)


def get_video_pi_url() -> str | None:
    value = os.getenv("VIDEO_PI_URL", "").strip()
    return value.rstrip("/") if value else None


def build_video_url(file_path: str) -> str:
    filename = Path(file_path).name
    return f"http://store.local/external-videos/{quote(filename)}"


async def post_to_video_pi(path: str, body: dict | None = None) -> dict:
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "error", "message": "Video Pi not configured"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{video_pi_url}{path}", json=body or {})
    response.raise_for_status()
    return response.json()


async def get_from_video_pi(path: str) -> dict:
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{video_pi_url}{path}")
    response.raise_for_status()
    return response.json()


@router.post("/player/play")
async def play_video(body: PlayRequest):
    video_url = build_video_url(body.file_path)
    return await post_to_video_pi("/play", {"url": video_url, "file_path": body.file_path})


@router.post("/player/stop")
async def stop_video():
    return await post_to_video_pi("/stop")


@router.get("/player/status")
async def video_status():
    return await get_from_video_pi("/status")
