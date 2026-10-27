"""Disk usage and guardrails for the data volume."""
from __future__ import annotations

import os
import shutil

from mods.config import Config

MIN_FREE_BYTES = 2 * 1024 ** 3   # keep at least 2 GB free
MIN_FREE_FRACTION = 0.05         # ... or 5 % of the volume, whichever is larger
BITRATE_BYTES_PER_HOUR = {"64k": 30e6, "96k": 45e6, "128k": 60e6, "192k": 90e6}


def usage() -> dict:
    try:
        st = shutil.disk_usage(Config.DATA_ROOT)
    except OSError:
        return {"total": 0, "used": 0, "free": 0, "low": False, "threshold": 0}
    threshold = max(MIN_FREE_BYTES, int(st.total * MIN_FREE_FRACTION))
    return {"total": st.total, "used": st.used, "free": st.free, "threshold": threshold, "low": st.free < threshold}


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def projected_bytes(streams: list[dict], retention_hours: int) -> int:
    """Rough steady-state size of all recordings at the configured retention."""
    return int(sum(BITRATE_BYTES_PER_HOUR.get(m.get("bitrate", "128k"), 60e6) for m in streams) * retention_hours)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
