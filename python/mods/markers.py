"""Listener markers ("mark this moment") per stream, stored in <stream>/markers.json."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time

from mods import streams

MAX_MARKERS = 200
_lock = threading.Lock()


def path_for(stub: str) -> str:
    return os.path.join(streams.stream_dir(stub), "markers.json")


def load(stub: str) -> list[dict]:
    try:
        with open(path_for(stub), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(stub: str, items: list[dict]) -> None:
    tmp = path_for(stub) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh)
    os.replace(tmp, path_for(stub))


def add(stub: str, aired_at: float, label: str) -> dict:
    item = {"id": secrets.token_hex(4), "aired_at": float(aired_at), "label": (label or "").strip()[:120],
            "created": time.time()}
    with _lock:
        items = load(stub)
        items.append(item)
        items.sort(key=lambda m: m["aired_at"])
        _save(stub, items[-MAX_MARKERS:])
    return item


def remove(stub: str, marker_id: str) -> bool:
    with _lock:
        items = load(stub)
        kept = [m for m in items if m.get("id") != marker_id]
        if len(kept) == len(items):
            return False
        _save(stub, kept)
    return True


def prune(stub: str, before: float) -> None:
    with _lock:
        items = load(stub)
        kept = [m for m in items if m.get("aired_at", 0) >= before]
        if len(kept) != len(items):
            _save(stub, kept)
