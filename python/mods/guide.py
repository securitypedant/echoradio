"""Programme guide: what was on the station at a given moment.

Providers (see docs/schedule-feeds.md for the research behind them):

* ``bbc``      – BBC Sounds broadcasts feed; service id like ``bbc_radio_two``.
* ``kexp``     – KEXP shows API (plus song titles from its plays feed).
* ``bauer``    – Bauer UK "listenapi" (Absolute, Magic, KISS, Greatest Hits …); station code like ``abr``.
* ``radiodns`` – RadioDNS/SPI EPG XML (Global: Classic FM, LBC, Heart, Capital; News UK: Virgin, Times;
                 Deutschlandfunk; ARD stations …); service = PI.xml URL template with ``{date}``.
* ``orf``      – ORF Austria (``oe1``, ``oe3``, ``fm4``).
* ``abc``      – ABC Australia program items (service id like ``RN``, ``triplej``, ``local_sydney``).
* ``rte``      – RTÉ Ireland (``radio1``, ``2fm``, ``lyricfm``, ``rnag``).
* ``manual``   – a weekly schedule entered in the stream form.

Schedule settings live in <stream>/schedule.json:
``{"provider": "...", "service": "...", "manual": [{"days": [0..6], "start": "06:30", "end": "09:30",
"title": "...", "subtitle": "..."}]}``.

Every provider exposes the same shape: a list of ``{start, end, title, subtitle, synopsis, image}``
with epoch-second times, fetched per day and cached in memory.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from mods import streams

USER_AGENT = "EchoRadio/2.1 (+https://github.com/securitypedant/echoradio)"
PROVIDERS = ("none", "bbc", "kexp", "bauer", "radiodns", "orf", "abc", "rte", "manual")
PROVIDER_LABELS = {
    "none": "None",
    "bbc": "BBC Sounds (automatic)",
    "kexp": "KEXP (automatic, with song titles)",
    "bauer": "Bauer UK: Absolute, Magic, KISS, Greatest Hits … (automatic)",
    "radiodns": "RadioDNS EPG: Classic FM, LBC, Heart, Capital, Virgin, Times, Deutschlandfunk, ARD … (automatic)",
    "orf": "ORF Austria: Ö1, Ö3, FM4 (automatic)",
    "abc": "ABC Australia: RN, triple j, local stations (automatic)",
    "rte": "RTÉ Ireland: Radio 1, 2FM, lyric fm, RnaG (automatic)",
    "manual": "Weekly schedule I enter",
}
SERVICE_HELP = {
    "bbc": ("BBC service id", "e.g. bbc_radio_two (detected from the URL)"),
    "bauer": ("Bauer station code", "e.g. abr (Absolute), mag (Magic), ki1 (KISS), gh0 (Greatest Hits)"),
    "radiodns": ("EPG URL", "PI.xml URL with {date}, e.g. http://epg.musicradio.com/radiodns/spi/3.1/dab/ce1/c181/c2a1/0/{date}_PI.xml"),
    "orf": ("ORF station", "oe1, oe3 or fm4"),
    "abc": ("ABC service id", "e.g. RN, triplej, local_sydney, classic"),
    "rte": ("RTÉ station", "radio1, 2fm, lyricfm or rnag"),
}
SERVICE_RE = {
    "bbc": re.compile(r"^bbc_[a-z0-9_]{2,40}$"),
    "bauer": re.compile(r"^[a-z0-9]{2,8}$"),
    "radiodns": re.compile(r"^https?://[^\s]+\{date\}[^\s]*$"),
    "orf": re.compile(r"^(oe1|oe3|fm4)$"),
    "abc": re.compile(r"^[A-Za-z0-9_]{2,40}$"),
    "rte": re.compile(r"^(radio1|2fm|lyricfm|rnag)$"),
}
DAY_TTL = 6 * 3600
_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()
BBC_SERVICE_RE = re.compile(r"(bbc_[a-z0-9_]+)")

BBC_URL = "https://rms.api.bbc.co.uk/v2/broadcasts/schedules/{service}/{date}"
KEXP_SHOWS_URL = "https://api.kexp.org/v2/shows/?start_time_after={after}&start_time_before={before}&limit=100"
KEXP_PLAYS_URL = "https://api.kexp.org/v2/plays/?airdate_after={after}&airdate_before={before}&limit=200"
BAUER_URL = "https://listenapi.planetradio.co.uk/api9.2/schedule/{code}/{start}/{end}"
BAUER_STATIONS_URL = "https://listenapi.planetradio.co.uk/api9.2/stations/UK"
ORF_URL = "https://audioapi.orf.at/{station}/api/json/4.0/broadcasts/{date}"
ABC_URL = "https://program.abcradio.net.au/api/v1/programitems/search.json?service={service}&from={start}&to={end}&limit=100&offset={offset}"
RTE_URL = "https://www.rte.ie/radio/{station}/schedule/{date}/"
# RadioDNS SI.xml files we know how to map stream URLs against (host -> SI url).
RADIODNS_SI = (
    "http://epg.musicradio.com/radiodns/spi/3.1/SI.xml",
    "https://wireless.radiodns.metadata.radio/radiodns/spi/3.1/SI.xml",
    "https://rdns.deutschlandradio.de/radiodns/spi/3.1/SI.xml",
    "https://dewdr.radiodns.ard.de/radiodns/spi/3.1/SI.xml",
    "https://debr.radiodns.ard.de/radiodns/spi/3.1/SI.xml",
    "https://derbb.radiodns.ard.de/radiodns/spi/3.1/SI.xml",
)
ABC_STREAM_HINTS = {"rnnsw": "RN", "rn": "RN", "triplejnsw": "triplej", "triplej": "triplej", "localsydney": "local_sydney",
                    "classic": "classic", "news": "news", "doublej": "doublej", "jazz": "jazz", "country": "country",
                    "unearthed": "unearthed", "kids": "kids", "localmelbourne": "local_melbourne",
                    "localbrisbane": "local_brisbane", "localperth": "local_perth", "localadelaide": "local_adelaide"}


# ----------------------------------------------------------------- helpers
def _get(url: str, timeout: float = 12.0, accept: str = "application/json, */*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _cached(key: tuple, ttl: float, fn: Callable[[], object], keep_stale: bool = True):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        value = fn()
    except Exception:  # noqa: BLE001 - keep stale data if any
        if hit and keep_stale:
            return hit[1]
        raise
    with _lock:
        _cache[key] = (now, value)
    return value


def _iso_ts(text: str) -> float:
    """Parse ISO-8601 timestamps in the variants these feeds use."""
    t = text.strip().replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", t):              # +0000 -> +00:00
        t = t[:-2] + ":" + t[-2:]
    return datetime.fromisoformat(t).timestamp()


def _iso_duration(text: str) -> float:
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", text.strip())
    if not m:
        return 0.0
    d, h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _item(start: float, end: float, title: str, subtitle: str = "", synopsis: str = "", image: str = "") -> dict:
    return {"start": float(start), "end": float(end), "title": (title or "").strip()[:160],
            "subtitle": (subtitle or "").strip()[:160], "synopsis": (synopsis or "").strip()[:300], "image": image or ""}


def _fill_ends(items: list[dict], default_len: float = 3 * 3600) -> list[dict]:
    """For feeds that give start times only: end = next start."""
    items.sort(key=lambda p: p["start"])
    for i, p in enumerate(items):
        if not p.get("end"):
            p["end"] = items[i + 1]["start"] if i + 1 < len(items) else p["start"] + default_len
    return items


# --------------------------------------------------------------- settings
def path_for(stub: str) -> str:
    return os.path.join(streams.stream_dir(stub), "schedule.json")


def load_settings(stub: str) -> dict:
    try:
        with open(path_for(stub), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    provider = data.get("provider") or "none"
    if provider not in PROVIDERS:
        provider = "none"
    service = data.get("service") or data.get("bbc_service") or ""
    return {"provider": provider, "service": service,
            "manual": [e for e in (data.get("manual") or []) if isinstance(e, dict)]}


def save_settings(stub: str, settings: dict) -> None:
    os.makedirs(streams.stream_dir(stub), exist_ok=True)
    tmp = path_for(stub) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    os.replace(tmp, path_for(stub))


def valid_service(provider: str, service: str) -> bool:
    rx = SERVICE_RE.get(provider)
    return bool(rx.match(service)) if rx else True


# ------------------------------------------------------------- detection
def guess_bbc_service(url: str) -> str:
    m = BBC_SERVICE_RE.search(url or "")
    return m.group(1) if m else ""


def guess_provider(url: str) -> str:
    """Suggest a guide provider from the stream URL."""
    u = (url or "").lower()
    if BBC_SERVICE_RE.search(u):
        return "bbc"
    if "kexp" in u:
        return "kexp"
    if "hellorayo" in u or "planetradio" in u or "bauermedia" in u:
        return "bauer"
    if "ors-shoutcast.at" in u or "orf.at" in u:
        return "orf"
    if "abc-cdn.net.au" in u or "abc.streamguys1.com" in u or "mediahubaustralia" in u or "abcradio" in u:
        return "abc"
    if "rte.ie" in u or "/rte_" in u or "rte_1" in u or "rte_2fm" in u:
        return "rte"
    if radiodns_lookup(url):
        return "radiodns"
    return "none"


def guess_service(provider: str, url: str) -> str:
    """Best-effort station identifier for a provider from the stream URL ('' if unknown)."""
    u = (url or "")
    ul = u.lower()
    if provider == "bbc":
        return guess_bbc_service(u)
    if provider == "orf":
        m = re.search(r"/(oe1|oe3|fm4)", ul)
        return m.group(1) if m else ""
    if provider == "rte":
        if "2fm" in ul:
            return "2fm"
        if "lyric" in ul:
            return "lyricfm"
        if "rnag" in ul or "raidio" in ul:
            return "rnag"
        if "radio1" in ul or "rte_1" in ul:
            return "radio1"
        return ""
    if provider == "abc":
        m = re.search(r"(?:hls/|live/)([a-z0-9]+)(?:\.m3u8|/)", ul)
        if m:
            return ABC_STREAM_HINTS.get(m.group(1), "")
        return ""
    if provider == "bauer":
        return bauer_code_for_url(u)
    if provider == "radiodns":
        return radiodns_lookup(u)
    return ""


# -------------------------------------------------------------------- BBC
def _bbc_day(service: str, day: date) -> list[dict]:
    def fetch():
        data = json.loads(_get(BBC_URL.format(service=service, date=day.isoformat())))
        items = []
        for b in data.get("data") or []:
            try:
                start, end = _iso_ts(b["start"]), _iso_ts(b["end"])
            except (KeyError, ValueError):
                continue
            titles = b.get("titles") or {}
            syn = b.get("synopses") or {}
            items.append(_item(start, end, titles.get("primary"), titles.get("secondary"),
                               syn.get("short") or syn.get("medium"), (b.get("image_url") or "").replace("{recipe}", "320x320")))
        return items
    return _cached(("bbc", service, day.isoformat()), DAY_TTL, fetch)


# ------------------------------------------------------------------- KEXP
def _iso_z(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kexp_get(url: str) -> list[dict]:
    out: list[dict] = []
    for _ in range(5):
        data = json.loads(_get(url))
        out.extend(data.get("results") or [])
        url = data.get("next")
        if not url:
            break
    return out


def _kexp_window(t_from: float, t_to: float) -> list[dict]:
    key = ("kexp-shows", int(t_from // 1800), int(t_to // 1800))

    def fetch():
        raw = _kexp_get(KEXP_SHOWS_URL.format(after=_iso_z(t_from - 12 * 3600), before=_iso_z(t_to + 12 * 3600)))
        shows = []
        for sh in raw:
            try:
                start = datetime.fromisoformat(sh["start_time"]).timestamp()
            except (KeyError, ValueError):
                continue
            shows.append(_item(start, 0, sh.get("program_name"), ", ".join(sh.get("host_names") or []),
                               sh.get("tagline"), sh.get("image_uri")))
        return _fill_ends(shows)
    return _cached(key, 10 * 60, fetch)


def kexp_song_at(instant: float) -> str | None:
    hour = int(instant // 3600) * 3600

    def fetch():
        raw = _kexp_get(KEXP_PLAYS_URL.format(after=_iso_z(hour - 600), before=_iso_z(hour + 3600)))
        plays = []
        for pl in raw:
            try:
                ts = datetime.fromisoformat(pl["airdate"]).timestamp()
            except (KeyError, ValueError):
                continue
            if pl.get("play_type") == "trackplay" and (pl.get("artist") or pl.get("song")):
                plays.append((ts, " – ".join(x for x in (pl.get("artist"), pl.get("song")) if x)))
            elif pl.get("play_type") == "airbreak":
                plays.append((ts, ""))
        plays.sort()
        return plays
    ttl = 10 * 60 if time.time() - hour < 4 * 3600 else 24 * 3600
    try:
        plays = _cached(("kexp-plays", hour), ttl, fetch)
    except Exception:  # noqa: BLE001
        return None
    label = None
    for ts, text in plays:
        if ts <= instant:
            label = text
        else:
            break
    return label or None


# ------------------------------------------------------------------ Bauer
def _bauer_day(code: str, day: date) -> list[dict]:
    def fetch():
        url = BAUER_URL.format(code=code, start=f"{day.isoformat()}T00:00:00", end=f"{(day + timedelta(days=1)).isoformat()}T00:00:00")
        data = json.loads(_get(url))
        items = []
        for _d, eps in (data.items() if isinstance(data, dict) else []):
            for e in eps or []:
                try:
                    start = _iso_ts(e["start"])
                    end = start + float(e.get("duration") or 0)
                except (KeyError, ValueError, TypeError):
                    continue
                items.append(_item(start, end, e.get("title"), "", e.get("shortdesc"), e.get("image_url")))
        return items
    return _cached(("bauer", code, day.isoformat()), DAY_TTL, fetch)


def _bauer_stations() -> list[dict]:
    return _cached(("bauer-stations",), 24 * 3600, lambda: json.loads(_get(BAUER_STATIONS_URL)))


def bauer_code_for_url(url: str) -> str:
    """Match a stream URL against Bauer's station list (stream hosts/paths) to find the station code."""
    if not url:
        return ""
    try:
        stations = _bauer_stations()
    except Exception:  # noqa: BLE001
        return ""
    path = urllib.parse.urlparse(url).path.lower().rsplit("/", 1)[-1].split(".")[0]
    if not path:
        return ""
    for st in stations:
        code = st.get("stationCode") or ""
        for s in st.get("stationStreams") or []:
            su = (s.get("streamUrl") or "").lower()
            if su and path and path in su:
                return code
    return ""


# --------------------------------------------------------------- RadioDNS
def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _radiodns_day(template: str, day: date) -> list[dict]:
    def fetch():
        url = template.replace("{date}", day.strftime("%Y%m%d"))
        root = ET.fromstring(_get(url, accept="application/xml, text/xml, */*"))
        items = []
        for prog in root.iter():
            if _strip_ns(prog.tag) != "programme":
                continue
            names = {_strip_ns(c.tag): (c.text or "").strip() for c in prog if _strip_ns(c.tag) in ("shortName", "mediumName", "longName")}
            title = names.get("longName") or names.get("mediumName") or names.get("shortName") or ""
            subtitle = ""
            start = end = None
            synopsis = ""
            image = ""
            presenters = []
            for el in prog.iter():
                t = _strip_ns(el.tag)
                if t == "time" and el.get("time") and start is None:
                    try:
                        start = _iso_ts(el.get("time"))
                        end = start + _iso_duration(el.get("duration") or "PT0S")
                    except ValueError:
                        pass
                elif t in ("shortDescription", "longDescription") and (el.text or "").strip() and not synopsis:
                    synopsis = el.text.strip()
                elif t == "multimedia" and el.get("url") and not image:
                    image = el.get("url")
                elif t == "person" and el.get("name"):
                    presenters.append(el.get("name"))
            if start is None or not end or end <= start:
                continue
            if presenters:
                subtitle = ", ".join(presenters)
            elif re.match(r"^(Moderation:|Mit |Mit:|Presented by|With )", synopsis or ""):
                # ARD-style short descriptions carry the presenter ("Moderation: …", "Mit …").
                subtitle, synopsis = synopsis[:160], ""
            items.append(_item(start, end, title, subtitle, synopsis, image))
        return items
    return _cached(("radiodns", template, day.isoformat()), DAY_TTL, fetch)


def _radiodns_services() -> list[dict]:
    """[{host, epg_template, bearers:[...stream urls...]}] from the known SI.xml files (cached a day)."""
    def fetch():
        out = []
        for si_url in RADIODNS_SI:
            try:
                root = ET.fromstring(_get(si_url, accept="application/xml, text/xml, */*"))
            except Exception:  # noqa: BLE001
                continue
            base = si_url.rsplit("/radiodns/", 1)[0]
            for svc in root.iter():
                if _strip_ns(svc.tag) != "service":
                    continue
                dab = None
                urls = []
                name = ""
                for el in svc.iter():
                    t = _strip_ns(el.tag)
                    if t == "bearer":
                        bid = (el.get("id") or "").strip()
                        if bid.startswith("dab:") and dab is None:
                            dab = bid
                        elif bid.startswith(("http://", "https://")):
                            urls.append(bid.lower())
                    elif t == "mediumName" and not name:
                        name = (el.text or "").strip()
                if dab and urls:
                    gcc_eid_sid_scids = dab[4:].split(".")
                    if len(gcc_eid_sid_scids) >= 4:
                        tmpl = f"{base}/radiodns/spi/3.1/dab/{'/'.join(gcc_eid_sid_scids[:4])}/{{date}}_PI.xml"
                        out.append({"name": name, "epg_template": tmpl, "urls": urls})
        return out
    return _cached(("radiodns-si",), 24 * 3600, fetch)


def radiodns_lookup(url: str) -> str:
    """EPG template for a stream URL if a known RadioDNS SI.xml lists it as a bearer."""
    if not url:
        return ""
    u = url.lower().split("?")[0]
    try:
        services = _radiodns_services()
    except Exception:  # noqa: BLE001
        return ""
    for svc in services:
        for b in svc["urls"]:
            if b.split("?")[0] == u or (b.rsplit("/", 1)[-1] and b.rsplit("/", 1)[-1] == u.rsplit("/", 1)[-1] and urllib.parse.urlparse(b).hostname == urllib.parse.urlparse(u).hostname):
                return svc["epg_template"]
    return ""


# -------------------------------------------------------------------- ORF
def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _orf_day(station: str, day: date) -> list[dict]:
    def fetch():
        data = json.loads(_get(ORF_URL.format(station=station, date=day.strftime("%Y%m%d"))))
        # The per-day endpoint returns a flat list of broadcasts; the rolling endpoint nests them per day.
        if isinstance(data, list) and data and isinstance(data[0], dict) and "broadcasts" in data[0]:
            raw = [b for d in data for b in (d.get("broadcasts") or [])]
        elif isinstance(data, list):
            raw = data
        else:
            raw = (data.get("broadcasts") if isinstance(data, dict) else None) or []
        items = []
        for b in raw:
            try:
                start = _iso_ts(b.get("startISO") or b["scheduledStartISO"])
                end = _iso_ts(b.get("endISO") or b["scheduledEndISO"])
            except (KeyError, ValueError, TypeError):
                continue
            prog = _strip_html(b.get("programTitle") or "")
            title = _strip_html(b.get("title") or "")
            if prog and title and prog != title:
                name, episode = prog, title
            else:
                name, episode = (prog or title), _strip_html(b.get("subtitle") or "")
            synopsis = _strip_html(b.get("description") or b.get("subtitle") or "")
            mod = _strip_html(b.get("moderator") or "")
            if mod:
                episode = f"{episode} · {mod}" if episode else mod
            items.append(_item(start, end, name, episode, synopsis, ""))
        return items
    return _cached(("orf", station, day.isoformat()), DAY_TTL, fetch)


# -------------------------------------------------------------------- ABC
def _abc_day(service: str, day: date) -> list[dict]:
    def fetch():
        items = []
        offset = 0
        start_s = f"{day.isoformat()}T00:00:00"
        end_s = f"{(day + timedelta(days=1)).isoformat()}T00:00:00"
        for _ in range(5):
            data = json.loads(_get(ABC_URL.format(service=urllib.parse.quote(service), start=start_s, end=end_s, offset=offset)))
            for it in data.get("items") or []:
                ev = it.get("primary_publication_event") or {}
                try:
                    start, end = _iso_ts(ev["start"]), _iso_ts(ev["end"])
                except (KeyError, ValueError, TypeError):
                    continue
                presenters = ", ".join((p.get("display_name") or "") for p in (it.get("presenters") or []) if p.get("display_name"))
                items.append(_item(start, end, it.get("title"), presenters,
                                   it.get("short_synopsis") or it.get("mini_synopsis") or it.get("medium_synopsis"), ""))
            count = int(data.get("count") or 0)
            total = int(data.get("total") or 0)
            offset += count
            if count == 0 or offset >= total:
                break
        return items
    return _cached(("abc", service, day.isoformat()), DAY_TTL, fetch)


# -------------------------------------------------------------------- RTÉ
def _rte_day(station: str, day: date) -> list[dict]:
    tz = ZoneInfo("Europe/Dublin")

    def fetch():
        data = json.loads(_get(RTE_URL.format(station=station, date=day.strftime("%Y%m%d"))))
        groups = data if isinstance(data, list) else []
        items = []
        for g in groups:
            for sh in (g.get("data") if isinstance(g, dict) else None) or []:
                if not sh or not sh.get("showName"):
                    continue
                try:
                    hh, mm = (int(x) for x in str(sh.get("showTime", "")).split(":")[:2])
                    end_dt = datetime.strptime(sh["showEndDate"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
                except (ValueError, KeyError, TypeError):
                    continue
                start_dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)
                items.append(_item(start_dt.timestamp(), end_dt.timestamp(), sh.get("showName"), "", "", sh.get("image") or ""))
        return items
    return _cached(("rte", station, day.isoformat()), DAY_TTL, fetch)


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
                out.append(_item(s, en, str(e.get("title") or ""), str(e.get("subtitle") or "")))
        day += timedelta(days=1)
    out.sort(key=lambda p: p["start"])
    return out


# --------------------------------------------------------------- public
DAY_FETCHERS: dict[str, Callable[[str, date], list[dict]]] = {
    "bbc": _bbc_day, "bauer": _bauer_day, "radiodns": _radiodns_day, "orf": _orf_day, "abc": _abc_day, "rte": _rte_day,
}


def _by_days(fetcher, service: str, t_from: float, t_to: float, tz: ZoneInfo) -> list[dict]:
    out: list[dict] = []
    seen: set[float] = set()
    day = datetime.fromtimestamp(t_from, tz).date() - timedelta(days=1)
    last = datetime.fromtimestamp(t_to, tz).date()
    while day <= last:
        try:
            items = fetcher(service, day)
        except Exception:  # noqa: BLE001 - a missing day must not break the guide
            items = []
        for p in items:
            if p["start"] in seen:
                continue
            seen.add(p["start"])
            if p["end"] > t_from and p["start"] < t_to:
                out.append(dict(p))
        day += timedelta(days=1)
    out.sort(key=lambda p: p["start"])
    return out


def programmes(meta: dict, t_from: float, t_to: float) -> list[dict]:
    settings = load_settings(meta["stub"])
    tz = ZoneInfo(meta["source_timezone"])
    provider, service = settings["provider"], settings["service"]
    if provider == "kexp":
        return [dict(p) for p in _kexp_window(t_from, t_to) if p["end"] > t_from and p["start"] < t_to]
    if provider == "manual" and settings["manual"]:
        return _manual(settings["manual"], t_from, t_to, tz)
    fetcher = DAY_FETCHERS.get(provider)
    if fetcher and service and valid_service(provider, service):
        return _by_days(fetcher, service, t_from, t_to, tz)
    return []


def programme_at(meta: dict, instant: float) -> dict | None:
    for p in programmes(meta, instant - 1, instant + 1):
        if p["start"] <= instant < p["end"]:
            return p
    return None


def external_song_at(meta: dict, instant: float) -> str | None:
    """Song title from a provider's play log, for stations whose stream carries no titles."""
    settings = load_settings(meta["stub"])
    if settings["provider"] == "kexp":
        return kexp_song_at(instant)
    return None
