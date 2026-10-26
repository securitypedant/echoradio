"""Prepare the data directory before supervisord starts.

Runs as ``python -m bootstrap`` from the container entrypoint. Idempotent.
Standard library plus the ``mods`` package (no Flask app needed).
"""
from __future__ import annotations

import glob
import os
import sys

from mods import icecast, streams
from mods.config import Config, load_server_config, read_secret_key

def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def ensure_dirs() -> None:
    for d in (Config.DATA_ROOT, Config.STREAMS_ROOT, Config.LOGS_ROOT, Config.SUPERVISOR_CONF_ROOT):
        os.makedirs(d, exist_ok=True)


def ensure_icecast_config(server_cfg: dict) -> None:
    if not os.path.exists(Config.ICECAST_CONFIG_FILE):
        icecast.write_icecast_config(server_cfg)
        log("wrote icecast.xml")


def refresh_streams(server_cfg: dict) -> None:
    for meta in streams.all_streams():
        # Fast only: scripts and supervisor programs. Fallback sets and legacy conversion run in
        # the background (maintenance.py) once the services are up.
        streams.materialize(meta, server_cfg, fallback=False, log=log)
    # Drop supervisor programs for streams that no longer exist.
    known = {m["stub"] for m in streams.all_streams()}
    for conf in glob.glob(os.path.join(Config.SUPERVISOR_CONF_ROOT, "*.conf")):
        stub = os.path.splitext(os.path.basename(conf))[0]
        if stub not in known:
            os.remove(conf)


def main() -> int:
    ensure_dirs()
    read_secret_key()
    server_cfg = load_server_config(Config.SERVER_CONFIG_FILE)
    ensure_icecast_config(server_cfg)
    refresh_streams(server_cfg)
    log("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
