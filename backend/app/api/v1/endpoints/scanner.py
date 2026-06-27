from __future__ import annotations

import json
import os
import time
from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.db.session import SessionLocal

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CHANNEL = "scanner:barcode"

# Scanner routing is liveness-based: each page that wants the scanner (Sales,
# Products/inventory) sends a heartbeat "claim" while it is open AND visible.
# A claim is a short-lived Redis key that the page refreshes on an interval; if
# the page is backgrounded, the device sleeps, or the tab closes, the heartbeat
# stops and the key expires. The effective target is the most-recently-renewed
# live claim, defaulting to "video" (the Remote / kiosk player) when nothing is
# actively claiming it. So a phone left on the Sales page that goes to sleep
# automatically hands the scanner back to the Remote instead of holding it.
CLAIM_PREFIX = "scanner:claim:"
# TTL must comfortably exceed the client heartbeat interval so a single missed
# beat (e.g. a slow request) doesn't drop the claim, but be short enough that a
# slept/closed client releases the scanner within a few seconds.
CLAIM_TTL_SECONDS = 15

ScannerTarget = Literal["video", "sales", "inventory"]
ClaimableTarget = Literal["sales", "inventory"]


class ScannerInputRequest(BaseModel):
    barcode: str = Field(min_length=1)


class ScannerTargetResponse(BaseModel):
    target: ScannerTarget


class ScannerClaimRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    target: ClaimableTarget


class ScannerReleaseRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)


async def _resolve_effective_target(redis: aioredis.Redis) -> ScannerTarget:
    """The current scanner target = the most-recently-renewed live claim.

    Falls back to "video" when no page is actively claiming the scanner.
    """
    best_target: ScannerTarget = "video"
    best_ts = -1.0
    async for key in redis.scan_iter(match=f"{CLAIM_PREFIX}*", count=50):
        value = await redis.get(key)
        if not value:
            continue
        raw_target, _, raw_ts = value.partition("|")
        if raw_target not in ("sales", "inventory"):
            continue
        try:
            ts = float(raw_ts)
        except ValueError:
            ts = 0.0
        if ts > best_ts:
            best_ts = ts
            best_target = raw_target  # type: ignore[assignment]
    return best_target


@router.get("/target", response_model=ScannerTargetResponse)
async def scanner_target():
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        target = await _resolve_effective_target(redis)
        return {"target": target}
    finally:
        await redis.aclose()


@router.post("/claim", response_model=ScannerTargetResponse)
async def scanner_claim(payload: ScannerClaimRequest):
    """Heartbeat: assert that this client is active on a scanner-using page.

    The stored timestamp marks when this client *acquired* the scanner, not the
    last heartbeat: a repeat heartbeat for the same target preserves the original
    acquire time. That keeps "most-recent claim wins" stable when two scanner
    pages are open at once (otherwise both renewing every few seconds would make
    the target oscillate) — the page that most recently opened/focused wins until
    it goes away.
    """
    key = f"{CLAIM_PREFIX}{payload.client_id}"
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        acquired_ts = time.time()
        existing = await redis.get(key)
        if existing:
            raw_target, _, raw_ts = existing.partition("|")
            if raw_target == payload.target:
                try:
                    acquired_ts = float(raw_ts)
                except ValueError:
                    pass
        await redis.set(key, f"{payload.target}|{acquired_ts}", ex=CLAIM_TTL_SECONDS)
        target = await _resolve_effective_target(redis)
        return {"target": target}
    finally:
        await redis.aclose()


@router.post("/release", response_model=ScannerTargetResponse)
async def scanner_release(payload: ScannerReleaseRequest):
    """Drop this client's claim immediately (page hidden / left / closed)."""
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis.delete(f"{CLAIM_PREFIX}{payload.client_id}")
        target = await _resolve_effective_target(redis)
        return {"target": target}
    finally:
        await redis.aclose()


def _play_barcode_sync(barcode: str) -> dict:
    # Imported lazily to avoid a circular import at module load.
    from app.api.v1.endpoints.video_library import play_barcode_core

    db = SessionLocal()
    try:
        return play_barcode_core(db, barcode)
    finally:
        db.close()


@router.post("/input")
async def scanner_input(payload: ScannerInputRequest):
    barcode = payload.barcode.strip()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode is required")

    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    target: ScannerTarget = "video"
    try:
        target = await _resolve_effective_target(redis)
        await redis.publish(CHANNEL, json.dumps({"barcode": barcode, "ts": time.time(), "target": target}))
    finally:
        await redis.aclose()

    # The video target's output is the Video Pi (mpv), not a browser, so the play
    # must be driven server-side — otherwise a scan only plays if someone happens
    # to have the Remote tab open and focused. Sales/inventory targets stay
    # browser-driven (the cashier is actively on those pages) via the SSE stream.
    play_result: dict | None = None
    if target == "video":
        try:
            play_result = await run_in_threadpool(_play_barcode_sync, barcode)
        except Exception:
            play_result = None

    response: dict = {"status": "ok", "target": target}
    if play_result is not None:
        response["play"] = play_result
    return response


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
