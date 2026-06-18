from __future__ import annotations

import json
import os
import time
from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CHANNEL = "scanner:barcode"
TARGET_KEY = "scanner:target"
ScannerTarget = Literal["video", "sales", "inventory"]


class ScannerInputRequest(BaseModel):
    barcode: str = Field(min_length=1)


class ScannerTargetRequest(BaseModel):
    target: ScannerTarget


class ScannerTargetResponse(BaseModel):
    target: ScannerTarget


async def _read_scanner_target(redis: aioredis.Redis) -> ScannerTarget:
    value = await redis.get(TARGET_KEY)
    if value in {"video", "sales", "inventory"}:
        return value
    return "video"


@router.get("/target", response_model=ScannerTargetResponse)
async def scanner_target():
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        target = await _read_scanner_target(redis)
        return {"target": target}
    finally:
        await redis.aclose()


@router.post("/target", response_model=ScannerTargetResponse)
async def scanner_target_update(payload: ScannerTargetRequest):
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis.set(TARGET_KEY, payload.target)
        return {"target": payload.target}
    finally:
        await redis.aclose()


@router.post("/input")
async def scanner_input(payload: ScannerInputRequest):
    barcode = payload.barcode.strip()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode is required")

    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        target = await _read_scanner_target(redis)
        await redis.publish(CHANNEL, json.dumps({"barcode": barcode, "ts": time.time(), "target": target}))
    finally:
        await redis.aclose()

    return {"status": "ok"}


async def _scanner_stream():
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(CHANNEL)
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
            if message is None:
                yield ": ping\n\n"
                continue

            data = message.get("data")
            if isinstance(data, str) and data.strip():
                yield f"data: {data}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
        finally:
            await pubsub.aclose()
            await redis.aclose()


@router.get("/stream")
async def scanner_stream():
    return StreamingResponse(
        _scanner_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
