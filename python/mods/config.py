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
    "player_debug": False,              # per-session diagnostics log (client + server) for the web player
    # Tunables (seconds). Environment variables set the defaults for a deployment; the settings
    # page overrides them per installation.
    "min_delay_seconds": int(os.environ.get("ECHORADIO_MIN_DELAY_SECONDS", "120")),
    "player_lead_seconds": int(os.environ.get("ECHORADIO_PLAYER_LEAD_SECONDS", "30")),
    "relay_lead_seconds": int(os.environ.get("ECHORADIO_RELAY_LEAD_SECONDS", "40")),
    "player_buffer_seconds": 60,        # hls.js maxBufferLength
    "player_back_buffer_seconds": 600,  # hls.js backBufferLength
    "player_buffer_hole_seconds": 0.5,  # hls.js maxBufferHole: gaps up to this are jumped silently
    "player_stall_seconds": 15,         # web player waits this long in "buffering" before nudging/reloading
    "source_buffer_seconds": 5,         # liquidsoap: pre-buffer in front of the recorder
    "source_buffer_max_seconds": 40,    # liquidsoap: most the recorder buffer may hold
    "source_timeout_seconds": 20,       # liquidsoap: input.http timeout
    "relay_buffer_seconds": 4,          # liquidsoap: pre-buffer in front of the Icecast relay
    "relay_buffer_max_seconds": 20,
}

# Settings that are baked into each stream's liquidsoap script: changing one rewrites the scripts
# and restarts running streams.
LIQUIDSOAP_TUNABLES = ("source_buffer_seconds", "source_buffer_max_seconds", "source_timeout_seconds",
                       "relay_buffer_seconds", "relay_buffer_max_seconds")

# (key, minimum, maximum) for every numeric tunable; floats where the bounds are floats.
TUNABLE_BOUNDS: dict[str, tuple[float, float]] = {
    "min_delay_seconds": (30, 900),
    "player_lead_seconds": (10, 120),
    "relay_lead_seconds": (10, 180),
    "player_buffer_seconds": (20, 300),
    "player_back_buffer_seconds": (0, 7200),
    "player_buffer_hole_seconds": (0.1, 5.0),
    "player_stall_seconds": (5, 60),
    "source_buffer_seconds": (1, 60),
    "source_buffer_max_seconds": (5, 300),
    "source_timeout_seconds": (5, 120),
    "relay_buffer_seconds": (1, 60),
    "relay_buffer_max_seconds": (5, 300),
}


def clamp_tunable(key: str, value) -> float | int:
    lo, hi = TUNABLE_BOUNDS[key]
    default = SERVER_DEFAULTS[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    v = max(lo, min(v, hi))
    return v if isinstance(default, float) else int(round(v))

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
    cfg["player_debug"] = bool(cfg.get("player_debug"))
    for key in TUNABLE_BOUNDS:
        cfg[key] = clamp_tunable(key, cfg.get(key, SERVER_DEFAULTS[key]))
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
    # liquidsoap's relay reads playlists/segments through nginx: proper keep-alive handling and
    # segments served straight from disk (gunicorn closes idle connections after a few seconds,
    # which made ffmpeg stall with "Error reading HTTP response: End of file").
    RELAY_BASE_URL = os.environ.get("ECHORADIO_RELAY_BASE_URL", "http://127.0.0.1:8080")

    # Timing tunables; the values below are only the pre-settings defaults, apply_server_config()
    # replaces them from server_config.json (they are class attributes so code running outside a
    # request, such as the housekeeper, sees the same values).
    MIN_DELAY_SECONDS = SERVER_DEFAULTS["min_delay_seconds"]      # never serve closer to the edge
    RELAY_LEAD_SECONDS = SERVER_DEFAULTS["relay_lead_seconds"]    # relay playlist lead
    PLAYER_LEAD_SECONDS = SERVER_DEFAULTS["player_lead_seconds"]  # hls.js liveSyncDuration
    PLAYER_DEBUG = False
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
        cls.MIN_DELAY_SECONDS = int(cfg["min_delay_seconds"])
        cls.RELAY_LEAD_SECONDS = int(cfg["relay_lead_seconds"])
        cls.PLAYER_LEAD_SECONDS = int(cfg["player_lead_seconds"])
        cls.PLAYER_DEBUG = bool(cfg["player_debug"])
        return cfg
