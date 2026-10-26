"""Icecast configuration file management and statistics (no Flask dependency)."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from string import Template
from xml.sax.saxutils import escape

from mods.config import Config, load_server_config


def render_icecast_config(server_cfg: dict | None = None) -> str:
    server_cfg = server_cfg or load_server_config(Config.SERVER_CONFIG_FILE)
    with open(os.path.join(Config.CONFIG_TEMPLATES, "icecast.xml.tmpl"), encoding="utf-8") as fh:
        tmpl = Template(fh.read())
    public = server_cfg.get("public_base_url") or ""
    host = re.sub(r"^https?://", "", public).split("/")[0].split(":")[0] or "localhost"
    return tmpl.substitute({
        "icecast_max_sources": int(server_cfg.get("icecast_max_sources") or 5),
        "icecast_admin_password": escape(server_cfg.get("icecast_admin_password") or "ChangeMePlease"),
        "icecast_source_password": escape(server_cfg.get("icecast_source_password") or "ChangeMePlease"),
        "icecast_hostname": escape(host),
    })


def write_icecast_config(server_cfg: dict | None = None) -> str:
    path = Config.ICECAST_CONFIG_FILE
    content = render_icecast_config(server_cfg)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)
    return path


def fetch_stats(timeout: float = 2.0) -> dict[str, dict]:
    """Per-mount stats from icecast's status-json.xsl, keyed by mount name without slash."""
    url = f"http://{Config.ICECAST_PRIVATE_HOST}:{Config.ICECAST_PRIVATE_PORT}/status-json.xsl"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        return {}
    sources = (data.get("icestats") or {}).get("source") or []
    if isinstance(sources, dict):
        sources = [sources]
    out = {}
    for src in sources:
        listenurl = src.get("listenurl") or ""
        mount = listenurl.rsplit("/", 1)[-1]
        if mount:
            out[mount] = {
                "listeners": int(src.get("listeners") or 0),
                "listener_peak": int(src.get("listener_peak") or 0),
                "title": src.get("title") or "",
            }
    return out
