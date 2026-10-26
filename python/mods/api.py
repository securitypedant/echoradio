"""JSON API used by the web player and the stream form."""
from __future__ import annotations

import urllib.error
import urllib.request
from zoneinfo import available_timezones

from flask import abort, current_app, jsonify, request

import delay as delay_mod
from mods import state, streams, supervisor
from mods.auth import auth_required
from mods.utils import stream_urls


def _public(s: dict) -> dict:
    keys = ("name", "stub", "description", "status", "status_text", "recording", "playing_kind",
            "source_timezone", "target_timezone", "delay_seconds", "delay_text", "aired_at",
            "aired_at_iso", "listener_now", "source_now", "source_offset", "target_offset",
            "coverage", "hours_recorded", "listeners", "listeners_mp3", "listeners_hls", "backup_track",
            "backup_label", "bitrate", "mount", "now_playing_song", "artwork_url")
    out = {k: s.get(k) for k in keys}
    out["urls"] = stream_urls(s)
    return out


def api_streams():
    return jsonify([_public(s) for s in state.all_states()])


def api_stream(stub: str):
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    s = state.stream_state(meta)
    out = _public(s)
    out["min_delay_seconds"] = current_app.config["MIN_DELAY_SECONDS"]
    out["player_lead_seconds"] = current_app.config["PLAYER_LEAD_SECONDS"]
    out["dvr_hours"] = current_app.config.get("DVR_HOURS")
    return jsonify(out)


def api_delay():
    source = request.args.get("source", "")
    target = request.args.get("target", "")
    zones = available_timezones()
    if source not in zones or target not in zones:
        return jsonify({"error": "unknown timezone"}), 400
    now = delay_mod.utcnow()
    info = state.delay_info({"source_timezone": source, "target_timezone": target}, now)
    return jsonify(info)


@auth_required
def api_test_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"ok": False, "message": "URL must start with http:// or https://"}), 400
    req = urllib.request.Request(url, headers={"User-Agent": streams.USER_AGENT, "Icy-MetaData": "1"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            ctype = resp.headers.get("Content-Type", "")
            name = resp.headers.get("icy-name", "")
            chunk = resp.read(4096)
    except urllib.error.HTTPError as exc:
        return jsonify({"ok": False, "message": f"HTTP {exc.code} {exc.reason}"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": f"Could not connect: {exc}"})
    kind = "unknown"
    lower = ctype.lower()
    if "mpegurl" in lower or url.lower().split("?")[0].endswith(".m3u8") or chunk.startswith(b"#EXTM3U"):
        kind = "HLS playlist"
    elif "mpeg" in lower or "mp3" in lower:
        kind = "MP3 stream"
    elif "aac" in lower:
        kind = "AAC stream"
    elif "ogg" in lower or "opus" in lower:
        kind = "Ogg stream"
    elif chunk[:3] == b"ID3" or (len(chunk) > 1 and chunk[0] == 0xFF and (chunk[1] & 0xE0) == 0xE0):
        kind = "MP3 stream"
    msg = f"Reachable: {kind}" + (f" ({ctype})" if ctype else "") + (f" · {name}" if name else "")
    return jsonify({"ok": True, "message": msg, "content_type": ctype, "kind": kind, "icy_name": name})


def healthz():
    info = supervisor.process_info("icecast")
    ok = info.get("statename") == "RUNNING"
    return jsonify({"ok": ok, "icecast": info.get("statename", "UNKNOWN")}), (200 if ok else 503)


@auth_required
def api_directory():
    from mods import directory
    return jsonify(directory.search(request.args.get("q", "")))


def api_title(stub: str):
    """Plain-text now-playing title used by the liquidsoap relay for ICY metadata."""
    from flask import Response
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    return Response(state.now_playing_title(meta) + "\n", mimetype="text/plain",
                    headers={"Cache-Control": "no-store"})
