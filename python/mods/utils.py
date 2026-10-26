"""Small helpers: timezone lists, config export/import, URL helpers."""
from __future__ import annotations

import io
import os
import zipfile
from zoneinfo import available_timezones

from flask import current_app, request

_SKIP_TZ_PREFIXES = ("Etc/", "SystemV/", "US/", "posix/", "right/")


def grouped_timezones() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for tz in sorted(available_timezones()):
        if tz.startswith(_SKIP_TZ_PREFIXES) or "/" not in tz:
            if tz != "UTC":
                continue
        region = tz.split("/", 1)[0] if "/" in tz else "Other"
        grouped.setdefault(region, []).append(tz)
    return dict(sorted(grouped.items()))


def public_base_url() -> str:
    """Configured public base URL, else the origin the current request arrived on."""
    configured = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    return request.url_root.rstrip("/")


def stream_urls(meta: dict) -> dict[str, str]:
    """Public URLs for a stream, using its URL name (mount)."""
    base = public_base_url()
    name = meta.get("mount") or meta["stub"]
    return {
        "mp3": f"{base}/listen/{name}",
        "hls": f"{base}/hls/{name}/live.m3u8",
        "player": f"{base}/player/{name}",
    }


def export_config_zip() -> io.BytesIO:
    """server_config.json + every stream's metadata.json."""
    data_root = current_app.config["DATA_ROOT"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        cfg = os.path.join(data_root, "server_config.json")
        if os.path.exists(cfg):
            zf.write(cfg, "server_config.json")
        streams_root = current_app.config["STREAMS_ROOT"]
        if os.path.isdir(streams_root):
            for stub in sorted(os.listdir(streams_root)):
                meta = os.path.join(streams_root, stub, "metadata.json")
                if os.path.exists(meta):
                    zf.write(meta, f"streams/{stub}/metadata.json")
    buf.seek(0)
    return buf


def import_config_zip(fileobj) -> list[str]:
    """Restore server_config.json and stream metadata from an export. Returns imported stubs."""
    data_root = os.path.abspath(current_app.config["DATA_ROOT"])
    imported: list[str] = []
    with zipfile.ZipFile(fileobj) as zf:
        for member in zf.namelist():
            if not (member == "server_config.json" or
                    (member.startswith("streams/") and member.endswith("/metadata.json"))):
                continue
            target = os.path.abspath(os.path.join(data_root, member))
            if not target.startswith(data_root + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            if member.startswith("streams/"):
                imported.append(member.split("/")[1])
    return imported
