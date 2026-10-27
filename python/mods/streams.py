"""Stream definitions: metadata files, liquidsoap scripts, supervisor programs, fallback sets.

Everything here works without a Flask application context so that
``bootstrap.py`` can use it before the web app starts.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import time
from string import Template

from mods.config import Config, load_server_config

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36")

BACKUP_KINDS = {
    "birdsong": "Bird song",
    "voice": "Voice message",
    "silence": "Silence",
    "live": "Live stream",
}
LEGACY_BACKUP = {
    "backup_bird_song_loop": "birdsong",
    "backup_voice_loop": "voice",
    "backup_silence": "silence",
    "radio_input_stream": "live",
}
BITRATES = ("64k", "96k", "128k", "192k")
# Fallback segment names carry their exact duration: <position>_<duration_ms>.ts
FALLBACK_NAME_EXPR = '"#{m.position}_#{int_of_float(m.duration * 1000.)}.#{m.extname}"'
STUB_RE = re.compile(r"^[a-z0-9]{1,40}$")
# Public URL name (icecast mount, /listen/<mount>, /player/<mount>, /hls/<mount>/*.m3u8)
MOUNT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


# ----------------------------------------------------------------- metadata
def stream_dir(stub: str) -> str:
    return os.path.join(Config.STREAMS_ROOT, stub)


def metadata_path(stub: str) -> str:
    return os.path.join(stream_dir(stub), "metadata.json")


def make_stub(name: str) -> str:
    stub = re.sub(r"[^a-zA-Z0-9]", "", name).lower()[:40]
    return stub or "stream"


def unique_stub(name: str) -> str:
    base = make_stub(name)
    stub, n = base, 2
    while os.path.exists(stream_dir(stub)):
        stub = f"{base}{n}"
        n += 1
    return stub


def normalize_metadata(meta: dict) -> dict:
    """Fill defaults and translate v1 fields."""
    meta = dict(meta)
    meta["backup_track"] = LEGACY_BACKUP.get(meta.get("backup_track"), meta.get("backup_track") or "birdsong")
    if meta["backup_track"] not in BACKUP_KINDS:
        meta["backup_track"] = "birdsong"
    meta.setdefault("bitrate", Config.DEFAULT_BITRATE)
    if meta["bitrate"] not in BITRATES:
        meta["bitrate"] = Config.DEFAULT_BITRATE
    meta.setdefault("status", "STOPPED")
    meta.setdefault("description", "")
    if not MOUNT_RE.match(str(meta.get("mount") or "")):
        meta["mount"] = meta["stub"]
    art = str(meta.get("artwork_url") or "").strip()
    meta["artwork_url"] = art if art.lower().startswith(("http://", "https://")) and len(art) <= 500 else ""
    now = time.time()
    meta.setdefault("created_at", now)
    # Timeline grid anchor: 48 h before creation, on a 10 s boundary (see hls.py).
    meta.setdefault("timeline_origin", float(int((meta["created_at"] - 48 * 3600) // 10) * 10))
    return meta


def load_metadata(stub: str) -> dict | None:
    try:
        with open(metadata_path(stub), encoding="utf-8") as fh:
            return normalize_metadata(json.load(fh))
    except (OSError, ValueError):
        return None


def save_metadata(stub: str, meta: dict) -> None:
    os.makedirs(stream_dir(stub), exist_ok=True)
    tmp = metadata_path(stub) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    os.replace(tmp, metadata_path(stub))


def update_metadata(stub: str, **fields) -> dict | None:
    meta = load_metadata(stub)
    if meta is None:
        return None
    meta.update(fields)
    save_metadata(stub, meta)
    return meta


def resolve(name: str) -> dict | None:
    """Metadata for a stream addressed by its stub or its public URL name (mount)."""
    if not name or not MOUNT_RE.match(name):
        return None
    if STUB_RE.match(name):
        meta = load_metadata(name)
        if meta is not None:
            return meta
    for meta in all_streams():
        if meta.get("mount") == name:
            return meta
    return None


def mount_taken(mount: str, exclude_stub: str | None = None) -> bool:
    for meta in all_streams():
        if meta["stub"] == exclude_stub:
            continue
        if meta.get("mount") == mount or meta["stub"] == mount:
            return True
    return False


def all_streams() -> list[dict]:
    out = []
    try:
        names = sorted(os.listdir(Config.STREAMS_ROOT))
    except FileNotFoundError:
        return out
    for stub in names:
        if not STUB_RE.match(stub):
            continue
        meta = load_metadata(stub)
        if meta:
            out.append(meta)
    out.sort(key=lambda m: m.get("created_at", 0))
    return out


# ------------------------------------------------------------ liquidsoap
def _render(template_name: str, mapping: dict) -> str:
    with open(os.path.join(Config.LIQUIDSOAP_TEMPLATES, template_name), encoding="utf-8") as fh:
        return Template(fh.read()).substitute(mapping)


def _liq_str(value: str) -> str:
    """Escape a value for a double-quoted liquidsoap string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("#{", "#\\{")


def backup_source_definition(kind: str) -> str:
    fb = Config.FALLBACK_AUDIO_ROOT
    if kind == "birdsong":
        return f'backup = mksafe(playlist(id="backup", mode="normal", reload_mode="never", "{fb}/birdsong"))'
    if kind == "voice":
        return f'backup = mksafe(playlist(id="backup", mode="normal", reload_mode="never", "{fb}/voices"))'
    if kind == "live":
        return "backup = mksafe(live)"
    return 'backup = blank(id="backup")'


def render_stream_script(meta: dict, server_cfg: dict | None = None) -> str:
    server_cfg = server_cfg or load_server_config(Config.SERVER_CONFIG_FILE)
    stub = meta["stub"]
    return _render("stream.liq", {
        "stream_name": _liq_str(meta["name"]),
        "stream_description": _liq_str(meta.get("description") or ""),
        "stream_input": _liq_str(meta["url"]),
        "stream_mount": meta.get("mount") or stub,
        "user_agent": _liq_str(USER_AGENT),
        "bitrate": meta.get("bitrate", Config.DEFAULT_BITRATE),
        "hls_dir": os.path.join(stream_dir(stub), "hls"),
        "relay_playlist_url": f"{Config.RELAY_BASE_URL}/hls/{stub}/relay.m3u8",
        "title_url": f"{Config.WEB_PRIVATE_URL}/api/streams/{stub}/title",
        "events_log": os.path.join(stream_dir(stub), "events.log"),
        "stream_url": _liq_str(f"{(server_cfg.get('public_base_url') or '').rstrip('/')}/player/{meta.get('mount') or stub}"
                               if server_cfg.get("public_base_url") else ""),
        "backup_source": backup_source_definition(meta.get("backup_track", "birdsong")),
        "icecast_host": Config.ICECAST_PRIVATE_HOST,
        "icecast_port": Config.ICECAST_PRIVATE_PORT,
        "icecast_source_password": _liq_str(server_cfg["icecast_source_password"]),
    })


def write_stream_script(meta: dict, server_cfg: dict | None = None) -> str:
    path = os.path.join(stream_dir(meta["stub"]), "stream.liq")
    os.makedirs(os.path.join(stream_dir(meta["stub"]), "hls"), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_stream_script(meta, server_cfg))
    return path


def supervisor_conf_path(stub: str) -> str:
    return os.path.join(Config.SUPERVISOR_CONF_ROOT, f"{stub}.conf")


def write_supervisor_conf(meta: dict) -> str:
    stub = meta["stub"]
    sdir = stream_dir(stub)
    conf = f"""[program:{stub}]
command={Config.LIQUIDSOAP_BIN} {sdir}/stream.liq
directory={sdir}
autostart=false
autorestart=true
startsecs=5
stopwaitsecs=20
killasgroup=true
stopasgroup=true
stdout_logfile={sdir}/liquidsoap.log
stdout_logfile_maxbytes=5MB
stdout_logfile_backups=3
redirect_stderr=true
environment=TZ="UTC",HOME="/home/streamer"
"""
    os.makedirs(Config.SUPERVISOR_CONF_ROOT, exist_ok=True)
    path = supervisor_conf_path(stub)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(conf)
    return path


def remove_supervisor_conf(stub: str) -> bool:
    try:
        os.remove(supervisor_conf_path(stub))
        return True
    except FileNotFoundError:
        return False


def delete_stream_files(stub: str) -> None:
    shutil.rmtree(stream_dir(stub), ignore_errors=True)


# ---------------------------------------------------------- fallback sets
def fallback_dir(stub: str, kind: str) -> str:
    return os.path.join(stream_dir(stub), "fallback", kind)


def fallback_ready(stub: str, kind: str) -> bool:
    return os.path.exists(os.path.join(fallback_dir(stub, kind), ".done"))


def run_segmenter(source_def: str, out_dir: str, bitrate: str, name_expr: str,
                  timeout: int = 600, max_segments: int = 0) -> subprocess.CompletedProcess:
    """Run the one-shot liquidsoap segmenter (faster than real time) into ``out_dir``."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    script = _render("segment_files.liq", {
        "source_def": source_def, "out_dir": out_dir, "bitrate": bitrate, "name_expr": name_expr,
        "max_segments": int(max_segments),
    })
    script_path = os.path.join(out_dir, "segment.liq")
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(script)
    env = dict(os.environ, TZ="UTC", HOME=os.environ.get("HOME", "/home/streamer"))
    return subprocess.run([Config.LIQUIDSOAP_BIN, script_path], capture_output=True, text=True,
                          timeout=timeout, env=env)


FALLBACK_SEGMENTS = 8  # ~80 s of looped fallback audio per set


def fallback_source_def(kind: str) -> str:
    """Looping source; the segmenter stops after FALLBACK_SEGMENTS full segments."""
    fb = Config.FALLBACK_AUDIO_ROOT
    if kind == "birdsong":
        return f's = playlist(mode="normal", loop=true, reload_mode="never", "{fb}/birdsong")'
    if kind == "voice":
        return f's = playlist(mode="normal", loop=true, reload_mode="never", "{fb}/voices")'
    return "s = blank()"


def ensure_fallback_sets(meta: dict, kinds: tuple[str, ...] | None = None, log=None) -> None:
    """Generate codec-matched fallback segments for the stream (silence + its chosen kind)."""
    stub = meta["stub"]
    bitrate = meta.get("bitrate", Config.DEFAULT_BITRATE)
    wanted = set(kinds or ("silence", meta.get("backup_track", "birdsong")))
    wanted.discard("live")
    wanted.add("silence")
    for kind in sorted(wanted):
        if fallback_ready(stub, kind):
            continue
        if log:
            log(f"[{stub}] generating {kind} fallback segments at {bitrate}")
        try:
            res = run_segmenter(fallback_source_def(kind), fallback_dir(stub, kind), bitrate,
                                FALLBACK_NAME_EXPR, max_segments=FALLBACK_SEGMENTS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if log:
                log(f"[{stub}] segmenter for {kind} failed: {exc}")
            continue
        if res.returncode != 0 and log:
            log(f"[{stub}] segmenter for {kind} exited {res.returncode}: {res.stdout[-800:]}")
        if glob.glob(os.path.join(fallback_dir(stub, kind), "*.ts")):
            open(os.path.join(fallback_dir(stub, kind), ".done"), "w").close()


def rebuild_fallback_sets(meta: dict, log=None) -> None:
    shutil.rmtree(os.path.join(stream_dir(meta["stub"]), "fallback"), ignore_errors=True)
    ensure_fallback_sets(meta, log=log)


# --------------------------------------------------------------- creation
def materialize(meta: dict, server_cfg: dict | None = None, fallback: bool = True, log=None) -> dict:
    """Write metadata, script, supervisor program and (optionally) fallback sets for a stream."""
    meta = normalize_metadata(meta)
    save_metadata(meta["stub"], meta)
    write_stream_script(meta, server_cfg)
    write_supervisor_conf(meta)
    if fallback:
        ensure_fallback_sets(meta, log=log)
    return meta
