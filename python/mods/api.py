"""JSON API used by the web player and the stream form."""
from __future__ import annotations

import urllib.error
import urllib.request
from zoneinfo import available_timezones

from flask import abort, current_app, jsonify, request

import delay as delay_mod
from mods import playerlog, state, streams, supervisor
from mods.auth import auth_required
from mods.utils import stream_urls


def _public(s: dict) -> dict:
    keys = ("name", "stub", "description", "status", "status_text", "recording", "playing_kind",
            "source_timezone", "target_timezone", "delay_seconds", "delay_text", "aired_at",
            "aired_at_iso", "listener_now", "source_now", "source_offset", "target_offset",
            "coverage", "hours_recorded", "listeners", "listeners_mp3", "listeners_hls", "backup_track",
            "backup_label", "bitrate", "mount", "now_playing_song", "artwork_url", "aired_day", "source_city", "target_city", "now_programme", "recording_mode", "fill_label")
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
            final_url = resp.geturl()
            content_length = resp.headers.get("Content-Length")
            chunk = resp.read(4096)
    except urllib.error.HTTPError as exc:
        return jsonify({"ok": False, "message": f"HTTP {exc.code} {exc.reason}"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": f"Could not connect: {exc}"})
    warnings = []
    if final_url != url:
        warnings.append(f"redirects to {final_url}")
    lower_final = final_url.lower()
    if any(k in lower_final for k in ("georestrict", "geo-restrict", "geoblock", "barker", "notavailable", "unavailable")):
        warnings.append("this looks like a geo-restriction message, not the station (the server's location may be blocked)")
    elif content_length and not ("mpegurl" in ctype.lower() or lower_final.endswith(".m3u8")):
        warnings.append(f"a fixed-length file ({int(content_length) // 1024} KB), not a live stream")
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
    if warnings:
        msg += " — Warning: " + "; ".join(warnings)
    return jsonify({"ok": not any("geo-restriction" in w for w in warnings), "message": msg, "content_type": ctype,
                    "kind": kind, "icy_name": name, "final_url": final_url, "warnings": warnings})


def healthz():
    info = supervisor.process_info("icecast")
    ok = info.get("statename") == "RUNNING"
    d = state.disk_status()
    return jsonify({"ok": ok, "icecast": info.get("statename", "UNKNOWN"),
                    "disk_free": d.get("free"), "disk_low": d.get("low")}), (200 if ok else 503)


def api_health(stub: str):
    from mods import health
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    days = max(1, min(int(request.args.get("days", 7)), 14))
    return jsonify(health.summary(meta["stub"], days=days))


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


# ------------------------------------------------------------------ markers
def api_markers(stub: str):
    from mods import markers
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    if request.method == "GET":
        return jsonify(markers.load(meta["stub"]))
    data = request.get_json(silent=True) or {}
    try:
        aired_at = float(data.get("aired_at"))
    except (TypeError, ValueError):
        return jsonify({"error": "aired_at (epoch seconds) required"}), 400
    item = markers.add(meta["stub"], aired_at, str(data.get("label") or ""))
    return jsonify(item), 201


def api_marker_delete(stub: str, marker_id: str):
    from mods import markers
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    return jsonify({"ok": markers.remove(meta["stub"], marker_id)})


# -------------------------------------------------------------------- guide
def api_guide(stub: str):
    from mods import guide
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    try:
        t_from = float(request.args.get("from"))
        t_to = float(request.args.get("to"))
    except (TypeError, ValueError):
        return jsonify({"error": "from and to (epoch seconds) required"}), 400
    if t_to <= t_from or t_to - t_from > 3 * 86400:
        return jsonify({"error": "window must be positive and at most 3 days"}), 400
    settings = guide.load_settings(meta["stub"])
    return jsonify({"provider": settings["provider"], "programmes": guide.programmes(meta, t_from, t_to)})


@auth_required
def api_streams_order():
    data = request.get_json(silent=True) or {}
    order = [str(x) for x in (data.get("order") or []) if streams.STUB_RE.match(str(x))]
    n = streams.set_order(order)
    from mods import backups
    backups.snapshot("reorder")
    return jsonify({"ok": True, "ordered": n})


# ------------------------------------------------------------- player diagnostics
def api_client_log(stub: str):
    """The web player uploads its diagnostics lines here (diagnostics mode only).

    Body: {"c": "<client id>", "lines": ["<HH:MM:SS.mmm> <message>", ...]}. The reply carries the
    server-side lines for the same session so the player can offer one merged report to copy.
    """
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    if not playerlog.enabled():
        return jsonify({"ok": False, "enabled": False, "server": []})
    data = request.get_json(silent=True) or {}
    cid = playerlog.valid_cid(str(data.get("c") or ""))
    if cid is None:
        abort(400)
    lines = data.get("lines") or []
    if not isinstance(lines, list):
        abort(400)
    for line in lines[:500]:
        playerlog.log(meta["stub"], cid, "client", str(line)[:400])
    return jsonify({"ok": True, "enabled": True, "server": playerlog.lines_for(cid)})


def api_player_log(stub: str):
    """Merged server-side lines (playlists + segment downloads) for one player session, as text."""
    meta = streams.resolve(stub)
    if meta is None:
        abort(404)
    cid = playerlog.valid_cid(request.args.get("c"))
    if cid is None:
        abort(400)
    body = playerlog.summary_header(meta["stub"], cid) + "\n" + "\n".join(playerlog.lines_for(cid, 2000)) + "\n"
    return current_app.response_class(body, mimetype="text/plain", headers={"Cache-Control": "no-store"})
