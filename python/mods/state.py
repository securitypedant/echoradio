"""Per-stream runtime state: segment indexes, status, delay figures, housekeeping."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import delay as delay_mod
import hls
from mods import icecast, songlog, streams, supervisor
from mods.config import Config
from mods.logger import logger

_indexes: dict[str, hls.SegmentIndex] = {}
_indexes_lock = threading.Lock()
RECORDING_FRESH_SECONDS = 40.0

# HLS listeners: playlist pollers seen recently, keyed per stream by a client id.
_listeners: dict[str, dict[str, float]] = {}
_listeners_lock = threading.Lock()
LISTENER_TTL_SECONDS = 45.0


def note_listener(stub: str, key: str) -> None:
    now = time.time()
    with _listeners_lock:
        seen = _listeners.setdefault(stub, {})
        seen[key] = now
        for k in [k for k, ts in seen.items() if now - ts > LISTENER_TTL_SECONDS]:
            del seen[k]


def hls_listeners(stub: str) -> int:
    now = time.time()
    with _listeners_lock:
        seen = _listeners.get(stub, {})
        return sum(1 for ts in seen.values() if now - ts <= LISTENER_TTL_SECONDS)


def index_for(meta: dict) -> hls.SegmentIndex:
    stub = meta["stub"]
    with _indexes_lock:
        idx = _indexes.get(stub)
        if idx is None:
            idx = hls.SegmentIndex(streams.stream_dir(stub), meta["timeline_origin"])
            _indexes[stub] = idx
        return idx


def forget_index(stub: str) -> None:
    with _indexes_lock:
        _indexes.pop(stub, None)


def min_delay() -> timedelta:
    return timedelta(seconds=Config.MIN_DELAY_SECONDS)


def source_instant(meta: dict, now: datetime | None = None) -> datetime:
    return delay_mod.source_instant(now, meta["source_timezone"], meta["target_timezone"], min_delay())


# The "live stream" backup plays the station this far behind real time (seconds).
LIVE_LAG_SECONDS = 60.0


def live_shift(meta: dict, now: datetime | None = None) -> float | None:
    """Timeline-to-recording offset for the live backup kind (None for other kinds)."""
    if meta.get("backup_track") != "live":
        return None
    now = now or delay_mod.utcnow()
    return (now - source_instant(meta, now)).total_seconds() - LIVE_LAG_SECONDS


def delay_info(meta: dict, now: datetime | None = None) -> dict:
    now = now or delay_mod.utcnow()
    instant = source_instant(meta, now)
    td = now - instant
    src_tz = ZoneInfo(meta["source_timezone"])
    tgt_tz = ZoneInfo(meta["target_timezone"])
    return {
        "delay_seconds": int(td.total_seconds()),
        "delay_text": delay_mod.describe_delay(td),
        "source_instant": instant.timestamp(),
        "aired_at": instant.astimezone(src_tz).strftime("%H:%M"),
        "aired_at_iso": instant.astimezone(src_tz).isoformat(),
        "listener_now": now.astimezone(tgt_tz).strftime("%H:%M"),
        "source_now": now.astimezone(src_tz).strftime("%H:%M"),
        "source_offset": delay_mod.zone_offset_label(meta["source_timezone"], now),
        "target_offset": delay_mod.zone_offset_label(meta["target_timezone"], now),
    }


def stream_state(meta: dict, now: datetime | None = None, stats: dict | None = None,
                 procs: dict | None = None) -> dict:
    """Everything the UI needs to know about one stream."""
    now = now or delay_mod.utcnow()
    now_ts = now.timestamp()
    stub = meta["stub"]
    idx = index_for(meta)
    proc = (procs or {}).get(stub) if procs is not None else supervisor.process_info(stub)
    proc = proc or {"statename": "UNKNOWN"}
    running = proc.get("statename") == "RUNNING"
    newest = idx.newest_start()
    recording = newest is not None and (now_ts - newest) < RECORDING_FRESH_SECONDS
    if not running:
        status, status_text = "stopped", "Stopped"
    elif recording:
        status, status_text = "recording", "Recording"
    elif proc.get("statename") == "STARTING":
        status, status_text = "starting", "Starting"
    else:
        status, status_text = "source_down", "Source unavailable"
    info = delay_info(meta, now)
    instant = info["source_instant"]
    kind = meta.get("backup_track", "birdsong")
    playing = idx.entries_between(kind, instant - 12.0, instant + 0.01, live_shift(meta, now))
    playing_kind = playing[-1].kind if playing else None
    coverage = idx.coverage(now_ts - 24 * 3600, now_ts, 3600.0)
    song = songlog.song_at(stub, instant) if playing_kind == "rec" else None
    stats = stats if stats is not None else icecast.fetch_stats()
    mount = stats.get(stub, {})
    return {
        **meta,
        "status": status,
        "status_text": status_text,
        "process_state": proc.get("statename", "UNKNOWN"),
        "uptime": supervisor.uptime_text(proc) if running else "",
        "recording": recording,
        "newest_segment_age": (now_ts - newest) if newest is not None else None,
        "playing_kind": playing_kind,          # "rec", "fill" or None
        "now_playing_song": song,
        "coverage": coverage,                  # 24 hourly fractions, oldest first
        "hours_recorded": round(sum(coverage), 1),
        "disk_mb": round(idx.disk_bytes() / (1024 * 1024)),
        "listeners_mp3": mount.get("listeners", 0),
        "listeners_hls": hls_listeners(stub),
        "listeners": mount.get("listeners", 0) + hls_listeners(stub),
        "backup_label": streams.BACKUP_KINDS.get(kind, kind),
        **info,
    }


def all_states(now: datetime | None = None) -> list[dict]:
    now = now or delay_mod.utcnow()
    stats = icecast.fetch_stats()
    procs = supervisor.all_process_info()
    return [stream_state(m, now, stats, procs) for m in streams.all_streams()]


# ---------------------------------------------------------- housekeeping
_housekeeper_started = False


def prune_all(retention_hours: int) -> None:
    cutoff = time.time() - retention_hours * 3600
    for meta in streams.all_streams():
        try:
            removed = index_for(meta).prune(cutoff, meta.get("backup_track", "birdsong"), live_shift(meta))
            songlog.prune(meta["stub"], cutoff)
            if removed:
                logger.info("Pruned %d segments from %s", removed, meta["stub"])
        except Exception:  # noqa: BLE001
            logger.exception("Prune failed for %s", meta["stub"])


def start_housekeeper(get_retention_hours, interval: int = 600) -> None:
    global _housekeeper_started
    if _housekeeper_started:
        return
    _housekeeper_started = True

    def loop():
        time.sleep(60)
        while True:
            try:
                prune_all(int(get_retention_hours()))
            except Exception:  # noqa: BLE001
                logger.exception("Housekeeping failed")
            time.sleep(interval)

    threading.Thread(target=loop, name="housekeeper", daemon=True).start()


def now_playing_title(meta: dict, now: datetime | None = None) -> str:
    """Short ICY title for the MP3 relay, e.g. "11:21 London time" or "Bird song · buffer filling"."""
    now = now or delay_mod.utcnow()
    info = delay_info(meta, now)
    idx = index_for(meta)
    kind = meta.get("backup_track", "birdsong")
    instant = info["source_instant"]
    playing = idx.entries_between(kind, instant - 12.0, instant + 0.01, live_shift(meta, now))
    city = meta["source_timezone"].split("/")[-1].replace("_", " ")
    if playing and playing[-1].kind == "fill":
        if kind == "live":
            return f"Live now · recording for {info['aired_at']} {city} time"
        return f"{streams.BACKUP_KINDS.get(kind, kind)} · buffer filling"
    base = f"{info['aired_at']} {city} time"
    song = songlog.song_at(meta["stub"], instant)
    return f"{song[:90]} · {base}" if song else base
