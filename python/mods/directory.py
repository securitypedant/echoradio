"""Station directory: a curated BBC list (bpsib's gist) plus the community Radio Browser index.

Results are plain dicts: name, url, description, country, countrycode, state, tags, codec,
bitrate, homepage, source ("bbc" | "radio-browser") and an optional timezone hint.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from mods.config import Config

USER_AGENT = "EchoRadio/2.0 (+https://github.com/securitypedant/echoradio)"
GIST_API = "https://api.github.com/gists/67089b959e4fa898af69fea59ad74bc3"
RADIO_BROWSER_HOSTS = ("https://de1.api.radio-browser.info", "https://fi1.api.radio-browser.info",
                       "https://at1.api.radio-browser.info")
BBC_CACHE_SECONDS = 24 * 3600
_lock = threading.Lock()
_bbc_cache: dict = {"fetched_at": 0.0, "stations": []}
_country_zones: dict[str, list[str]] | None = None


def _get(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ------------------------------------------------------------ timezones
def _load_country_zones() -> dict[str, list[str]]:
    global _country_zones
    if _country_zones is not None:
        return _country_zones
    table: dict[str, list[str]] = {}
    # zone.tab keeps one zone per country (e.g. Europe/Amsterdam); zone1970.tab merges countries.
    for name in ("zone.tab", "zone1970.tab"):
        path = os.path.join("/usr/share/zoneinfo", name)
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("#") or not line.strip():
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 3:
                        continue
                    for cc in parts[0].split(","):
                        table.setdefault(cc.upper(), [])
                        if parts[2] not in table[cc.upper()]:
                            table[cc.upper()].append(parts[2])
            break
        except OSError:
            continue
    _country_zones = table
    return table


def timezone_hint(countrycode: str | None) -> str | None:
    """A timezone when the country has exactly one, else None (the user picks)."""
    if not countrycode:
        return None
    zones = _load_country_zones().get(countrycode.upper(), [])
    if countrycode.upper() == "GB":
        return "Europe/London"
    return zones[0] if len(zones) == 1 else None


# ------------------------------------------------------------------ BBC
def _parse_m3u(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    title = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            title = line.split(",", 1)[1].strip() if "," in line else None
        elif line.startswith("#"):
            continue
        elif line.lower().startswith(("http://", "https://")):
            out.append((title or line, line))
            title = None
    return out


def _cache_path() -> str:
    return os.path.join(Config.DATA_ROOT, "directory_cache.json")


def bbc_stations(force: bool = False) -> list[dict]:
    with _lock:
        now = time.time()
        if not force and _bbc_cache["stations"] and now - _bbc_cache["fetched_at"] < BBC_CACHE_SECONDS:
            return _bbc_cache["stations"]
        if not _bbc_cache["stations"]:
            try:
                with open(_cache_path(), encoding="utf-8") as fh:
                    disk = json.load(fh)
                if now - float(disk.get("fetched_at", 0)) < BBC_CACHE_SECONDS and disk.get("stations"):
                    _bbc_cache.update(disk)
                    return _bbc_cache["stations"]
            except (OSError, ValueError):
                pass
        try:
            gist = json.loads(_get(GIST_API))
            stations: list[dict] = []
            for fname, finfo in (gist.get("files") or {}).items():
                if not fname.lower().endswith((".m3u", ".m3u8")):
                    continue
                content = finfo.get("content")
                if content is None or finfo.get("truncated"):
                    content = _get(finfo["raw_url"]).decode("utf-8", "replace")
                for title, url in _parse_m3u(content):
                    name = re.sub(r"^BBC\s*-\s*", "BBC ", title).strip()
                    uk_only = "(UK Only)" in title or "uk=1" in url
                    stations.append({
                        "name": name, "url": url, "country": "United Kingdom", "countrycode": "GB",
                        "state": "", "tags": "bbc, uk" + (", uk-only" if uk_only else ""),
                        "codec": "HLS/AAC", "bitrate": 96, "homepage": "https://www.bbc.co.uk/sounds",
                        "description": "BBC via lstn.lv" + (" (UK only)" if uk_only else ""),
                        "source": "bbc", "timezone": "Europe/London",
                    })
            if stations:
                _bbc_cache.update({"fetched_at": now, "stations": stations})
                try:
                    with open(_cache_path(), "w", encoding="utf-8") as fh:
                        json.dump(_bbc_cache, fh)
                except OSError:
                    pass
        except Exception:  # noqa: BLE001 - keep whatever we had
            pass
        return _bbc_cache["stations"]


# --------------------------------------------------------- Radio Browser
def radio_browser(query: str, limit: int = 30) -> tuple[list[dict], str | None]:
    params = urllib.parse.urlencode({"name": query, "limit": limit, "hidebroken": "true",
                                     "order": "votes", "reverse": "true"})
    last_error = None
    for host in RADIO_BROWSER_HOSTS:
        try:
            data = json.loads(_get(f"{host}/json/stations/search?{params}"))
            out = []
            for st in data:
                url = (st.get("url_resolved") or st.get("url") or "").strip()
                if not url.lower().startswith(("http://", "https://")):
                    continue
                cc = st.get("countrycode") or ""
                out.append({
                    "name": (st.get("name") or "").strip(), "url": url, "country": st.get("country") or "",
                    "countrycode": cc, "state": st.get("state") or "", "tags": st.get("tags") or "",
                    "codec": st.get("codec") or "", "bitrate": st.get("bitrate") or 0,
                    "homepage": st.get("homepage") or "", "votes": st.get("votes") or 0,
                    "favicon": (st.get("favicon") or "").strip(),
                    "description": ", ".join(x for x in (st.get("state"), st.get("country")) if x),
                    "source": "radio-browser", "timezone": timezone_hint(cc),
                })
            return out, None
        except Exception as exc:  # noqa: BLE001
            last_error = f"{host}: {exc}"
    return [], last_error


def search(query: str) -> dict:
    q = (query or "").strip()
    ql = q.lower()
    bbc = [s for s in bbc_stations() if not ql or ql in s["name"].lower() or ql in s["tags"]]
    results = list(bbc)
    errors = {}
    if len(q) >= 2:
        rb, err = radio_browser(q)
        if err:
            errors["radio-browser"] = err
        seen = {s["url"] for s in results}
        for s in rb:
            if s["url"] not in seen:
                results.append(s)
                seen.add(s["url"])
    if not bbc_stations():
        errors["bbc"] = "BBC list unavailable"
    return {"query": q, "results": results[:80], "errors": errors}
