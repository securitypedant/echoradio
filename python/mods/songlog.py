"""Time-shifted song metadata: reads the per-stream events.log written by liquidsoap."""
from __future__ import annotations

import bisect
import os
import threading
import time

from mods import streams

_cache: dict[str, tuple[float, list[float], list[str]]] = {}
_lock = threading.Lock()


def path_for(stub: str) -> str:
    return os.path.join(streams.stream_dir(stub), "events.log")


def _load(stub: str) -> tuple[list[float], list[str]]:
    path = path_for(stub)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return [], []
    with _lock:
        cached = _cache.get(stub)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
    times: list[float] = []
    labels: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                try:
                    ts = float(parts[0])
                except ValueError:
                    continue
                artist, title = parts[1].strip(), parts[2].strip()
                label = " – ".join(x for x in (artist, title) if x)
                if times and ts < times[-1]:
                    continue  # out of order (clock jump); ignore
                times.append(ts)
                labels.append(label)
    except OSError:
        return [], []
    with _lock:
        _cache[stub] = (mtime, times, labels)
    return times, labels


def song_at(stub: str, instant: float, max_age: float = 3 * 3600) -> str | None:
    """Song label that was current at ``instant`` (UTC epoch), if the source announced one."""
    times, labels = _load(stub)
    if not times:
        return None
    i = bisect.bisect_right(times, instant) - 1
    if i < 0 or instant - times[i] > max_age:
        return None
    return labels[i] or None


def prune(stub: str, before: float) -> None:
    """Drop entries older than ``before`` (called by housekeeping)."""
    times, labels = _load(stub)
    if not times or times[0] >= before:
        return
    keep = bisect.bisect_left(times, before)
    keep = max(0, keep - 1)  # keep the entry that was current at the cutoff
    path = path_for(stub)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            for ts, label in zip(times[keep:], labels[keep:]):
                artist, _, title = label.partition(" – ") if " – " in label else ("", "", label)
                fh.write(f"{int(ts)}\t{artist}\t{title}\n")
        os.replace(tmp, path)
    except OSError:
        pass
    with _lock:
        _cache.pop(stub, None)


def forget(stub: str) -> None:
    with _lock:
        _cache.pop(stub, None)
    _ = time  # keep import for potential future use
