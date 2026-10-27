"""Source health history: per-stream hourly recording coverage kept for 14 days (beyond retention)."""
from __future__ import annotations

import json
import os
import threading
import time

from mods import streams

KEEP_DAYS = 14
_lock = threading.Lock()


def path_for(stub: str) -> str:
    return os.path.join(streams.stream_dir(stub), "health.json")


def load(stub: str) -> dict[str, dict]:
    try:
        with open(path_for(stub), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(stub: str, data: dict[str, dict]) -> None:
    tmp = path_for(stub) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path_for(stub))


def record_completed_hours(meta: dict, index) -> None:
    """Fill in coverage for hours that have fully elapsed since the stream was created."""
    stub = meta["stub"]
    now = time.time()
    with _lock:
        data = load(stub)
        last_hour = int(now // 3600) - 1
        start_hour = max(int(meta.get("created_at", now) // 3600), last_hour - 48)
        changed = False
        for h in range(start_hour, last_hour + 1):
            key = str(h * 3600)
            if key in data:
                continue
            t0 = h * 3600
            cov = index.coverage(t0, t0 + 3600, 3600.0)[0]
            segs = [s for s in index.segments if s.start < t0 + 3600 and s.end > t0]
            gaps = sum(1 for a, b in zip(segs, segs[1:]) if b.start - a.end > 1.0)
            data[key] = {"c": round(cov, 3), "g": gaps}
            changed = True
        cutoff = str(int((now - KEEP_DAYS * 86400) // 3600 * 3600))
        for key in [k for k in data if k < cutoff and len(k) == len(cutoff)]:
            del data[key]
            changed = True
        if changed:
            save(stub, data)


def summary(stub: str, days: int = 7) -> dict:
    data = load(stub)
    now = time.time()
    first = int((now - days * 86400) // 3600) * 3600
    hours = []
    total = 0.0
    counted = 0
    for h in range(first, int(now // 3600) * 3600, 3600):
        rec = data.get(str(h))
        if rec is None:
            hours.append({"t": h, "c": None, "g": 0})
        else:
            hours.append({"t": h, "c": rec["c"], "g": rec["g"]})
            total += rec["c"]
            counted += 1
    return {"hours": hours, "uptime": (total / counted) if counted else None, "hours_known": counted,
            "gaps": sum(x["g"] for x in hours)}
