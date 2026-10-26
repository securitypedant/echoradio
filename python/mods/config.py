"""Application configuration.

Static settings come from the environment; operator-editable settings live in
``<DATA_ROOT>/server_config.json`` and are loaded into the Flask config at start
and whenever the settings page saves them.
"""
from __future__ import annotations

import json
import os
import secrets

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DATA_ROOT = os.environ.get("DATA_ROOT", os.path.join(PROJECT_ROOT, "data"))

# Operator settings and their defaults (keys as stored in server_config.json).
SERVER_DEFAULTS: dict = {
    "enable_admin": False,
    "admin_password": "",               # bcrypt hash, empty when admin is disabled
    "icecast_admin_password": "ChangeMePlease",
    "icecast_source_password": "ChangeMePlease",
    "icecast_max_sources": 5,
    "public_base_url": "",              # e.g. https://radio.example.com (optional)
    "retention_hours": 30,              # how long recorded segments are kept
    "dvr_hours": 4,                     # seekable window in the web player
}

# Legacy keys from v1 server_config.json that are dropped on load.
LEGACY_SERVER_KEYS = ("icecast_public_hostname", "icecast_public_protocol", "icecast_public_port")


def read_secret_key() -> str:
    """Environment SECRET_KEY, else a random key persisted in the data directory."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(DATA_ROOT, "secret_key")
    try:
        with open(path, encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_ROOT, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key)
    except OSError as exc:
        # Keep running with a per-process key; sessions will not survive a restart.
        print(f"WARNING: cannot persist secret key at {path} ({exc}); using a temporary key. "
              f"Check that {DATA_ROOT} is writable by uid {os.getuid()}.", flush=True)
    return key


def load_server_config(path: str) -> dict:
    """server_config.json merged over defaults (missing file -> defaults)."""
    cfg = dict(SERVER_DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k in LEGACY_SERVER_KEYS:
                continue
            cfg[k] = v
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        pass
    cfg["icecast_max_sources"] = int(cfg.get("icecast_max_sources") or 5)
    cfg["retention_hours"] = int(cfg.get("retention_hours") or 30)
    cfg["dvr_hours"] = int(cfg.get("dvr_hours") or 4)
    cfg["enable_admin"] = bool(cfg.get("enable_admin"))
    return cfg


def save_server_config(path: str, cfg: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, path)


class Config:
    """Flask config object."""

    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = FLASK_ENV == "development"

    DATA_ROOT = DATA_ROOT
    STREAMS_ROOT = os.path.join(DATA_ROOT, "streams")
    LOGS_ROOT = os.path.join(DATA_ROOT, "logs")
    SUPERVISOR_CONF_ROOT = os.path.join(DATA_ROOT, "supervisord_configs")
    SERVER_CONFIG_FILE = os.path.join(DATA_ROOT, "server_config.json")
    ICECAST_CONFIG_FILE = os.path.join(DATA_ROOT, "icecast.xml")
    FALLBACK_AUDIO_ROOT = os.path.join(PROJECT_ROOT, "fallback_audio")
    LIQUIDSOAP_TEMPLATES = os.path.join(PROJECT_ROOT, "liquidsoap_templates")
    CONFIG_TEMPLATES = os.path.join(PROJECT_ROOT, "config_templates")

    LIQUIDSOAP_BIN = os.environ.get("LIQUIDSOAP_BIN", "/usr/bin/liquidsoap")
    SUPERVISOR_SOCKET = os.environ.get("SUPERVISOR_SOCKET", "/tmp/supervisor.sock")

    # Where liquidsoap reaches icecast and the web app from inside the container.
    ICECAST_PRIVATE_HOST = os.environ.get("ICECAST_PRIVATE_HOST", "127.0.0.1")
    ICECAST_PRIVATE_PORT = int(os.environ.get("ICECAST_PRIVATE_PORT", "8000"))
    WEB_PRIVATE_URL = os.environ.get("WEB_PRIVATE_URL", "http://127.0.0.1:5000")

    # Never serve closer to the recording edge than this (seconds).
    MIN_DELAY_SECONDS = int(os.environ.get("ECHORADIO_MIN_DELAY_SECONDS", "120"))
    # Lead applied to the relay playlist so the icecast MP3 output lands on the delayed instant.
    RELAY_LEAD_SECONDS = int(os.environ.get("ECHORADIO_RELAY_LEAD_SECONDS", "35"))
    # hls.js starts 3 target durations behind the playlist end by default.
    PLAYER_LEAD_SECONDS = 30
    DEFAULT_BITRATE = "128k"

    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    SECRET_KEY = read_secret_key()

    # Operator settings are mirrored here in upper case (ENABLE_ADMIN, RETENTION_HOURS, ...).
    @classmethod
    def apply_server_config(cls, app) -> dict:
        cfg = load_server_config(cls.SERVER_CONFIG_FILE)
        for k, v in cfg.items():
            app.config[k.upper()] = v
        app.config["SERVER_CONFIG"] = cfg
        return cfg
