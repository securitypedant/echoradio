"""Time-shift arithmetic for EchoRadio.

Pure standard library so it can be unit tested on the host and imported by the
web app. All instants are timezone-aware UTC datetimes.

The core idea: a listener in ``target_tz`` whose wall clock currently reads W
should hear what the station in ``source_tz`` broadcast when *its* wall clock
read W. Interpreting the same wall-clock time in both zones, and converting to
UTC, gives the exact source instant. Because this is evaluated on every request
it is correct for half-hour zones and across daylight-saving changes on either
side.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

# A segment is written over 10 s and indexed shortly after; never serve closer
# to the live edge than this.
DEFAULT_MIN_DELAY = timedelta(seconds=120)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _wall_to_instant(wall: datetime, tz: ZoneInfo) -> datetime:
    """Interpret a naive wall-clock time in ``tz`` and return the UTC instant."""
    return wall.replace(tzinfo=tz).astimezone(UTC)


def source_instant(now: datetime | None, source_tz: str, target_tz: str,
                   min_delay: timedelta = DEFAULT_MIN_DELAY) -> datetime:
    """UTC instant of the source content that should be playing right now.

    If the naive mapping lands in the future (the source zone is *behind* the
    listener) or closer than ``min_delay`` to now, one day is subtracted so the
    listener hears yesterday's broadcast of the same wall-clock time. The one
    exception is when both zones share an offset right now: there is no time
    shift to make, so the station plays as close to live as recording allows
    (``min_delay`` behind) rather than a day late.
    """
    now = (now or utcnow()).astimezone(UTC)
    src = ZoneInfo(source_tz)
    tgt = ZoneInfo(target_tz)
    wall = now.astimezone(tgt).replace(tzinfo=None)
    instant = _wall_to_instant(wall, src)
    if instant == now:
        return now - min_delay
    # Guard against pathological zone data with a bounded loop.
    for _ in range(3):
        if now - instant >= min_delay:
            break
        wall -= timedelta(days=1)
        instant = _wall_to_instant(wall, src)
    return instant


def delay(now: datetime | None, source_tz: str, target_tz: str,
          min_delay: timedelta = DEFAULT_MIN_DELAY) -> timedelta:
    """How far behind real time the listener hears the station."""
    now = (now or utcnow()).astimezone(UTC)
    return now - source_instant(now, source_tz, target_tz, min_delay)


def aired_at(now: datetime | None, source_tz: str, target_tz: str,
             min_delay: timedelta = DEFAULT_MIN_DELAY) -> datetime:
    """Source-local wall-clock time of what is playing now."""
    return source_instant(now, source_tz, target_tz, min_delay).astimezone(ZoneInfo(source_tz))


def describe_delay(td: timedelta) -> str:
    """Human-readable delay such as ``8h 30m`` or ``45m``."""
    total = int(round(td.total_seconds() / 60))
    hours, minutes = divmod(total, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def zone_offset_label(tz: str, at: datetime | None = None) -> str:
    """``UTC+1`` style label for a zone at a given instant."""
    at = (at or utcnow()).astimezone(ZoneInfo(tz))
    off = at.utcoffset() or timedelta(0)
    sign = "+" if off >= timedelta(0) else "-"
    off = abs(off)
    hours, rem = divmod(int(off.total_seconds()), 3600)
    minutes = rem // 60
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
