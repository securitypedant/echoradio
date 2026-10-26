"""Small static endpoints: web manifest, service worker, fallback audio previews."""
from __future__ import annotations

import os

from flask import abort, current_app, send_file

from mods.config import Config

FALLBACK_PREVIEWS = {"birdsong": ("birdsong", "birdsong.mp3"), "voice": ("voices", "erin.mp3")}


def manifest():
    resp = current_app.send_static_file("manifest.webmanifest")
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


def service_worker():
    resp = current_app.send_static_file("sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


def fallback_preview(kind: str):
    if kind not in FALLBACK_PREVIEWS:
        abort(404)
    sub, name = FALLBACK_PREVIEWS[kind]
    path = os.path.join(Config.FALLBACK_AUDIO_ROOT, sub, name)
    return send_file(path, mimetype="audio/mpeg", conditional=True)
