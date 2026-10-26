"""Playlist and segment endpoints under /hls/<stub>/."""
from __future__ import annotations

import os

from flask import Response, abort, current_app, request, send_from_directory

import hls
from mods import state, streams

PLAYLIST_HEADERS = {
    "Content-Type": "application/vnd.apple.mpegurl",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
}


def _meta_or_404(name: str) -> dict:
    meta = streams.resolve(name)
    if meta is None:
        abort(404)
    return meta


def _url_base(meta: dict) -> str:
    # Segment URLs are absolute and use the stub (directory name) so nginx can serve them
    # even when the playlist was requested through the stream's public URL name.
    return f"/hls/{meta['stub']}"


def _playlist(text: str) -> Response:
    return Response(text, headers=PLAYLIST_HEADERS)


def _note_listener(meta: dict) -> None:
    key = request.args.get("c") or f"{request.remote_addr}|{(request.headers.get('User-Agent') or '')[:80]}"
    state.note_listener(meta["stub"], key)


def live_playlist(stub: str):
    meta = _meta_or_404(stub)
    _note_listener(meta)
    idx = state.index_for(meta)
    edge = state.source_instant(meta).timestamp() + current_app.config["PLAYER_LEAD_SECONDS"]
    return _playlist(hls.live_window(idx, meta["backup_track"], edge, _url_base(meta), count=6,
                                     live_shift=state.live_shift(meta)))


def dvr_playlist(stub: str):
    meta = _meta_or_404(stub)
    _note_listener(meta)
    idx = state.index_for(meta)
    edge = state.source_instant(meta).timestamp() + current_app.config["PLAYER_LEAD_SECONDS"]
    hours = float(current_app.config.get("DVR_HOURS") or 4)
    return _playlist(hls.dvr_window(idx, meta["backup_track"], edge, hours, _url_base(meta),
                                    live_shift=state.live_shift(meta)))


def relay_playlist(stub: str):
    """Consumed by liquidsoap inside the container only."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    meta = _meta_or_404(stub)
    idx = state.index_for(meta)
    edge = state.source_instant(meta).timestamp() + current_app.config["RELAY_LEAD_SECONDS"]
    return _playlist(hls.live_window(idx, meta["backup_track"], edge, _url_base(meta), count=6,
                                     live_shift=state.live_shift(meta)))


def segment(stub: str, name: str):
    """Recorded segment (nginx normally serves these directly)."""
    meta = _meta_or_404(stub)
    if not hls._SEGMENT_RE.match(name):
        abort(404)
    directory = os.path.join(streams.stream_dir(meta["stub"]), "hls")
    resp = send_from_directory(directory, name, mimetype="video/mp2t", conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def fallback_segment(stub: str, kind: str, name: str):
    meta = _meta_or_404(stub)
    if kind not in hls.FALLBACK_KINDS or not hls._FALLBACK_RE.match(name):
        abort(404)
    directory = streams.fallback_dir(meta["stub"], kind)
    resp = send_from_directory(directory, name, mimetype="video/mp2t", conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
