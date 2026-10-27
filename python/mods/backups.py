"""Configuration backups: a zip of server_config.json and every stream's definition files,
written to <DATA_ROOT>/backups on every change (and on demand). Recordings are never included."""
from __future__ import annotations

import io
import os
import re
import time
import zipfile

from mods.config import Config

KEEP = 30
NAME_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9_-]{1,40}\.zip$")
STREAM_FILES = ("metadata.json", "schedule.json", "markers.json")


def backups_dir() -> str:
    return os.path.join(Config.DATA_ROOT, "backups")


def build_zip() -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(Config.SERVER_CONFIG_FILE):
            zf.write(Config.SERVER_CONFIG_FILE, "server_config.json")
        if os.path.isdir(Config.STREAMS_ROOT):
            for stub in sorted(os.listdir(Config.STREAMS_ROOT)):
                for name in STREAM_FILES:
                    path = os.path.join(Config.STREAMS_ROOT, stub, name)
                    if os.path.exists(path):
                        zf.write(path, f"streams/{stub}/{name}")
    buf.seek(0)
    return buf


def snapshot(reason: str = "change") -> str | None:
    """Write a backup zip and prune old ones. Returns the file name."""
    reason = re.sub(r"[^a-z0-9_-]", "", reason.lower())[:40] or "change"
    try:
        os.makedirs(backups_dir(), exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{reason}.zip"
        path = os.path.join(backups_dir(), name)
        with open(path, "wb") as fh:
            fh.write(build_zip().getvalue())
        prune()
        return name
    except OSError:
        return None


def list_backups() -> list[dict]:
    out = []
    try:
        for name in os.listdir(backups_dir()):
            if NAME_RE.match(name):
                st = os.stat(os.path.join(backups_dir(), name))
                out.append({"name": name, "size": st.st_size, "mtime": st.st_mtime,
                            "reason": name[16:-4], "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    except FileNotFoundError:
        pass
    out.sort(key=lambda b: b["name"], reverse=True)
    return out


def prune(keep: int = KEEP) -> None:
    for b in list_backups()[keep:]:
        try:
            os.remove(os.path.join(backups_dir(), b["name"]))
        except OSError:
            pass


def restore(name: str) -> list[str]:
    """Restore server_config.json and stream definition files from a backup. Returns stream stubs."""
    if not NAME_RE.match(name):
        raise ValueError("bad backup name")
    path = os.path.join(backups_dir(), name)
    data_root = os.path.abspath(Config.DATA_ROOT)
    stubs: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            parts = member.split("/")
            ok = member == "server_config.json" or (
                len(parts) == 3 and parts[0] == "streams" and re.match(r"^[a-z0-9]+$", parts[1]) and parts[2] in STREAM_FILES)
            if not ok:
                continue
            target = os.path.abspath(os.path.join(data_root, member))
            if not target.startswith(data_root + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
            if member.startswith("streams/"):
                stubs.append(parts[1])
    return sorted(set(stubs))
