from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import column, func, nullslast, or_, select, table
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pricing import PriceType, ProductPrice
from app.models.product import Product, ProductBrand, ProductCategory

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
    column("confirmed"),
    column("youtube_id"),
    column("uploaded_at"),
)

# Legacy Red Rhino / PyroSalesman kiosk barcode->video map (see
# scripts/load_legacy_kiosk_videos.py). Used as a fallback for scans whose
# barcode isn't a FIMS product.
legacy_kiosk_videos_table = table(
    "legacy_kiosk_videos",
    column("gtin"),
    column("gtin_norm"),
    column("video_filename"),
    column("name"),
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


def _get_product_video_filenames(db: Session, product_id: str) -> list[str]:
    """All non-empty video filenames for a product, best first.

    Ordered primary-then-newest, but callers should pick the first one that
    actually exists on the Video Pi rather than assuming the top row is playable
    — the "primary" row is frequently a loosely-matched YouTube download that was
    never synced to the Pi, while the real clip sits on the Pi as a non-primary row.
    """
    rows = (
        db.execute(
            select(product_videos_table.c.video_filename)
            .where(product_videos_table.c.product_id == product_id)
            .order_by(
                product_videos_table.c.is_primary.desc(),
                nullslast(product_videos_table.c.uploaded_at.desc()),
            )
        )
        .all()
    )
    filenames: list[str] = []
    for row in rows:
        name = (row.video_filename or "").strip()
        if name and name not in filenames:
            filenames.append(name)
    return filenames


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


def _fetch_remote_videos() -> set[str]:
    """Basenames of the video files currently present on the Video Pi.

    Used by /player/play to confirm a product's video file actually exists on the
    Pi before asking it to play that exact path. Returns an empty set if the Pi
    can't be reached or isn't configured, so play falls back to item-number
    matching instead of failing the whole request.
    """
    try:
        payload = get_from_video_pi("/videos")
    except (httpx.HTTPError, ValueError, TypeError):
        return set()
    return {Path(name).name for name in _normalize_video_list(payload)}


class PlayableProduct(BaseModel):
    id: str
    name: str
    item_number: str | None = None
    image_url: str | None = None
    brand_name: str | None = None
    in_store: bool = False


@router.get("/playable-products", response_model=list[PlayableProduct])
def list_playable_products(
    q: str | None = None,
    in_store: bool | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Products that actually have a video the Video Pi can play right now.

    The Remote should only offer products whose video file is physically on the
    Pi — not every in-store product, and not products whose only "video" is an
    unsynced YouTube download. We intersect each product's recorded video
    filenames against the Pi's live file list. If the Pi can't be reached we fall
    back to "has any video filename on record" so the list isn't mysteriously
    empty.
    """
    remote_lower = {name.lower() for name in _fetch_remote_videos()}

    stmt = (
        select(
            Product,
            ProductBrand.name.label("brand_name"),
            func.array_agg(product_videos_table.c.video_filename).label("filenames"),
        )
        .join(product_videos_table, product_videos_table.c.product_id == Product.id)
        .outerjoin(ProductBrand, ProductBrand.id == Product.brand_id)
        .where(
            Product.is_active.is_(True),
            product_videos_table.c.video_filename.isnot(None),
        )
    )
    if in_store is not None:
        stmt = stmt.where(Product.in_store.is_(in_store))
    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.item_number.ilike(f"%{q}%")))
    stmt = stmt.group_by(Product.id, ProductBrand.name).order_by(Product.created_at.desc())

    # Over-fetch, then filter to Pi-present files in Python and trim to `limit`.
    rows = db.execute(stmt.limit(max(limit * 6, 300))).all()

    results: list[dict] = []
    for product, brand_name, filenames in rows:
        names = [str(name).strip() for name in (filenames or []) if name and str(name).strip()]
        if remote_lower:
            playable = any(Path(name).name.lower() in remote_lower for name in names)
        else:
            playable = bool(names)
        if not playable:
            continue
        results.append(
            {
                "id": product.id,
                "name": product.name,
                "item_number": product.item_number,
                "image_url": f"/media/{product.image_path}" if product.image_path else None,
                "brand_name": brand_name,
                "in_store": product.in_store,
            }
        )
        if len(results) >= limit:
            break

    return results


@router.post("/player/play")
def play_video(body: PlayRequest, db: Session = Depends(get_db)):
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    remote_videos = _fetch_remote_videos()

    if body.product_id:
        product = _get_product_by_id(db, body.product_id)
        candidates = _get_product_video_filenames(db, body.product_id)

        # Prefer a video file that physically exists on the Video Pi, matched
        # case-insensitively, instead of blindly trusting the is_primary row
        # (which is often an unsynced YouTube download). This is what makes the
        # remote actually play the real clip, e.g. "Excalibur.mp4".
        remote_by_lower = {name.lower(): name for name in remote_videos}
        for candidate in candidates:
            base = Path(candidate).name
            actual = remote_by_lower.get(base.lower())
            if actual:
                return post_to_video_pi("/play", {"file_path": f"/media/pi/VIDEOS/videos/{actual}"})

        # Couldn't list the Pi's videos (it was unreachable), but we do have a
        # filename on record — try the best one directly rather than giving up.
        if not remote_videos and candidates:
            base = Path(candidates[0]).name
            return post_to_video_pi("/play", {"file_path": f"/media/pi/VIDEOS/videos/{base}"})

        # No known file is on the Pi — fall back to item-number matching, which is
        # how the legacy kiosk paired clips.
        item_number = (product.item_number or "").strip()
        if item_number:
            return post_to_video_pi("/play", {"item_number": item_number})
        return {"status": "no_match", "product_id": body.product_id, "reason": "video_not_available"}

    if body.file_path:
        video_url = build_video_url(body.file_path)
        return post_to_video_pi("/play", {"url": video_url, "file_path": body.file_path})

    raise HTTPException(status_code=400, detail="Missing file_path or product_id")


class PlayByBarcodeRequest(BaseModel):
    barcode: str = Field(min_length=1)


def _lookup_legacy_video(db: Session, barcode: str) -> dict | None:
    """Resolve a scanned barcode to a legacy kiosk video filename, or None.

    Matches the GTIN exactly, then leading-zero-normalized so a 12-digit UPC-A
    scan finds a 13-digit EAN-13 ("0"+UPC) stored value and vice-versa — the way
    the old kiosk's GTIN database paired barcodes to clips.
    """
    norm = barcode.lstrip("0") or barcode
    row = db.execute(
        select(
            legacy_kiosk_videos_table.c.video_filename,
            legacy_kiosk_videos_table.c.name,
        )
        .where(
            or_(
                legacy_kiosk_videos_table.c.gtin == barcode,
                legacy_kiosk_videos_table.c.gtin_norm == norm,
            )
        )
        .limit(1)
    ).first()
    if not row:
        return None
    video_filename = (row.video_filename or "").strip()
    if not video_filename:
        return None
    return {"video_filename": Path(video_filename).name, "name": (row.name or "").strip() or None}


def _show_no_video_card(db: Session, product_id: str | None, name: str | None, barcode: str) -> bool:
    if name:
        lines = ["NO VIDEO YET", name[:40].upper()]
        if product_id:
            count = db.execute(
                select(func.count())
                .select_from(product_videos_table)
                .where(product_videos_table.c.product_id == product_id)
                .where(product_videos_table.c.confirmed.is_(False))
                .where(product_videos_table.c.youtube_id.isnot(None))
            ).scalar_one()
            if count > 0:
                lines.append(f"{count} possible video{'s' if count != 1 else ''} awaiting review in FIMS")
    else:
        lines = ["VIDEO NOT FOUND", f"Barcode {barcode}"]

    try:
        post_to_video_pi("/no-video", {"lines": lines})
    except Exception:
        return False
    return True


def play_barcode_core(db: Session, barcode: str) -> dict:
    """Resolve a scanned barcode to a video and play it on the Video Pi.

    Resolution order:
      1. FIMS product with a video file actually present on the Video Pi.
      2. Legacy Red Rhino kiosk barcode->video map (for items not in FIMS, or
         FIMS items whose only video isn't on the Pi).
    This is what makes a scan of an un-catalogued product still play its demo,
    the way the standalone kiosk used to. Shared by the /player/play-by-barcode
    endpoint and the server-side scanner-input handler so a physical scan plays
    on the kiosk even when no browser Remote tab is open.
    """
    video_pi_url = get_video_pi_url()
    if not video_pi_url:
        return {"status": "not_configured"}

    barcode = (barcode or "").strip()
    if not barcode:
        return {"status": "not_found", "barcode": barcode}

    remote_videos = _fetch_remote_videos()
    remote_by_lower = {name.lower(): name for name in remote_videos}

    def _play_if_present(filename: str) -> dict | None:
        base = Path(filename).name
        actual = remote_by_lower.get(base.lower())
        if actual:
            return post_to_video_pi("/play", {"file_path": f"/media/pi/VIDEOS/videos/{actual}"})
        # Pi's file list was unreachable — try the bare name directly rather than
        # giving up (mirrors /player/play's fallback).
        if not remote_videos:
            return post_to_video_pi("/play", {"file_path": f"/media/pi/VIDEOS/videos/{base}"})
        return None

    # 1) FIMS product(s) mapped to this barcode.
    from app.api.v1.endpoints._barcode import resolve_product_ids

    product_ids, _ = resolve_product_ids(db, barcode)
    fims_name: str | None = None
    for product_id in product_ids:
        if fims_name is None:
            fims_name = _get_product_by_id(db, product_id).name
        for candidate in _get_product_video_filenames(db, product_id):
            result = _play_if_present(candidate)
            if result is not None:
                return {**result, "source": "fims", "product_id": product_id, "name": fims_name}

    # 2) Legacy kiosk library — the whole point of this endpoint.
    legacy = _lookup_legacy_video(db, barcode)
    if legacy:
        result = _play_if_present(legacy["video_filename"])
        if result is not None:
            return {**result, "source": "legacy", "name": legacy["name"] or fims_name}

    if product_ids:
        card_shown = _show_no_video_card(db, product_ids[0], fims_name, barcode)
        return {
            "status": "no_match",
            "source": "fims",
            "name": fims_name,
            "reason": "video_not_available",
            "card_shown": card_shown,
        }
    card_shown = _show_no_video_card(db, None, None, barcode)
    return {"status": "not_found", "barcode": barcode, "card_shown": card_shown}


@router.post("/player/play-by-barcode")
def play_by_barcode(body: PlayByBarcodeRequest, db: Session = Depends(get_db)):
    """Play the clip for a scanned barcode (FIMS first, then the old kiosk library)."""
    barcode = body.barcode.strip()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode is required")
    return play_barcode_core(db, barcode)


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
            # Only confirmed videos belong in the looping queue — unconfirmed rows
            # are loose/auto matches that are often the wrong clip (e.g. a Great
            # Grizzly video auto-attached to a World Class product).
            .where(product_videos_table.c.confirmed.is_(True))
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
                # Only confirmed videos belong in the looping queue — unconfirmed
                # rows are loose/auto matches that are often the wrong clip.
                product_videos_table.c.confirmed.is_(True),
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
