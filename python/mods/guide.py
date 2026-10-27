"""Programme guide: what was on the station at a given moment.

Providers:
* ``bbc``    – BBC Sounds broadcast schedules (https://rms.api.bbc.co.uk/v2/broadcasts/schedules/<service>/<date>),
               cached per day on disk for six hours.
* ``manual`` – a weekly schedule entered in the stream form: entries with weekdays, start, end, title.

Schedule settings live in <stream>/schedule.json: {"provider": "bbc"|"manual"|"none", "bbc_service": "bbc_radio_two",
"manual": [{"days": [0..6], "start": "06:30", "end": "09:30", "title": "...", "subtitle": "..."}]}.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mods import streams

USER_AGENT = "EchoRadio/2.1 (+https://github.com/securitypedant/echoradio)"
BBC_URL = "https://rms.api.bbc.co.uk/v2/broadcasts/schedules/{service}/{date}"
BBC_TTL = 6 * 3600
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_lock = threading.Lock()
BBC_SERVICE_RE = re.compile(r"(bbc_[a-z0-9_]+)")


# --------------------------------------------------------------- settings
def path_for(stub: str) -> str:
    return os.path.join(streams.stream_dir(stub), "schedule.json")


def load_settings(stub: str) -> dict:
    try:
        with open(path_for(stub), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    return {"provider": data.get("provider") or "none", "bbc_service": data.get("bbc_service") or "",
            "manual": [e for e in (data.get("manual") or []) if isinstance(e, dict)]}


def save_settings(stub: str, settings: dict) -> None:
    os.makedirs(streams.stream_dir(stub), exist_ok=True)
    tmp = path_for(stub) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    os.replace(tmp, path_for(stub))


def guess_bbc_service(url: str) -> str:
    m = BBC_SERVICE_RE.search(url or "")
    return m.group(1) if m else ""


# -------------------------------------------------------------------- BBC
def _bbc_day(service: str, date: str) -> list[dict]:
    key = (service, date)
    now = time.time()
    with _lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < BBC_TTL:
            return cached[1]
    req = urllib.request.Request(BBC_URL.format(service=service, date=date), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        items = []
        for b in data.get("data") or []:
            try:
                start = datetime.fromisoformat(b["start"].replace("Z", "+00:00")).timestamp()
                end = datetime.fromisoformat(b["end"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            titles = b.get("titles") or {}
            syn = b.get("synopses") or {}
            items.append({"start": start, "end": end, "title": titles.get("primary") or "",
                          "subtitle": titles.get("secondary") or "", "synopsis": syn.get("short") or syn.get("medium") or "",
                          "image": (b.get("image_url") or "").replace("{recipe}", "320x320")})
        with _lock:
            _cache[key] = (now, items)
        return items
    except Exception:  # noqa: BLE001 - keep stale data if any
        with _lock:
            cached = _cache.get(key)
        return cached[1] if cached else []


def _bbc(service: str, t_from: float, t_to: float, tz: ZoneInfo) -> list[dict]:
    out: list[dict] = []
    day = datetime.fromtimestamp(t_from, tz).date() - timedelta(days=1)
    last = datetime.fromtimestamp(t_to, tz).date()
    seen = set()
    while day <= last:
        for item in _bbc_day(service, day.isoformat()):
            if item["start"] in seen:
                continue
            seen.add(item["start"])
            if item["end"] > t_from and item["start"] < t_to:
                out.append(dict(item))
        day += timedelta(days=1)
    out.sort(key=lambda p: p["start"])
    return out


# ----------------------------------------------------------------- manual
def _manual(entries: list[dict], t_from: float, t_to: float, tz: ZoneInfo) -> list[dict]:
    out: list[dict] = []
    day = datetime.fromtimestamp(t_from, tz).date() - timedelta(days=1)
    last = datetime.fromtimestamp(t_to, tz).date()
    while day <= last:
        for e in entries:
            try:
                days = [int(d) for d in (e.get("days") or [])]
                sh, sm = (int(x) for x in str(e.get("start", "")).split(":"))
                eh, em = (int(x) for x in str(e.get("end", "")).split(":"))
            except (TypeError, ValueError):
                continue
            if day.weekday() not in days:
                continue
            start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
            end = datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
            if end <= start:
                end += timedelta(days=1)
            s, en = start.timestamp(), end.timestamp()
            if en > t_from and s < t_to:
                out.append({"start": s, "end": en, "title": str(e.get("title") or "")[:120],
                            "subtitle": str(e.get("subtitle") or "")[:120], "synopsis": "", "image": ""})
        day += timedelta(days=1)
    out.sort(key=lambda p: p["start"])
    return out


# --------------------------------------------------------------- public
def programmes(meta: dict, t_from: float, t_to: float) -> list[dict]:
    settings = load_settings(meta["stub"])
    tz = ZoneInfo(meta["source_timezone"])
    if settings["provider"] == "bbc" and settings["bbc_service"]:
        return _bbc(settings["bbc_service"], t_from, t_to, tz)
    if settings["provider"] == "manual" and settings["manual"]:
        return _manual(settings["manual"], t_from, t_to, tz)
    return []


def programme_at(meta: dict, instant: float) -> dict | None:
    for p in programmes(meta, instant - 1, instant + 1):
        if p["start"] <= instant < p["end"]:
            return p
    return None
