from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo(os.environ.get("STORE_TZ", "America/New_York"))


def store_now() -> datetime:
    return datetime.now(STORE_TZ).replace(tzinfo=None)


def store_today() -> date:
    return datetime.now(STORE_TZ).date()


def store_day_utc_bounds(d: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(d, time.min, tzinfo=STORE_TZ)
    end_local = datetime.combine(d + timedelta(days=1), time.min, tzinfo=STORE_TZ)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
