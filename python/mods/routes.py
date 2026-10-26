"""URL map."""
from __future__ import annotations

from mods import api, auth, extras, hls_routes, views


def register_routes(app) -> None:
    add = app.add_url_rule

    # Pages
    add("/", "home", views.home)
    add("/about", "about", views.about)
    add("/login", "login", auth.login, methods=["GET", "POST"])
    add("/logout", "logout", auth.logout, methods=["POST"])
    add("/player/<stub>", "player", views.player)
    add("/manifest.webmanifest", "manifest", extras.manifest)
    add("/sw.js", "service_worker", extras.service_worker)
    add("/fallback-audio/<kind>", "fallback_preview", extras.fallback_preview)

    # Streams
    add("/streams/new", "stream_new", views.stream_new, methods=["GET", "POST"])
    add("/streams/<stub>", "stream_detail", views.stream_detail)
    add("/streams/<stub>/card", "stream_card", views.stream_card)
    add("/streams/<stub>/panel", "stream_detail_panel", views.stream_detail_panel)
    add("/streams/<stub>/log", "stream_log", views.stream_log)
    add("/streams/<stub>/edit", "stream_edit", views.stream_edit, methods=["GET", "POST"])
    add("/streams/<stub>/delete", "stream_delete", views.stream_delete, methods=["POST"])
    add("/streams/<stub>/reset", "stream_reset", views.stream_reset, methods=["POST"])
    add("/streams/<stub>/start", "stream_start", views.stream_start, methods=["POST"])
    add("/streams/<stub>/stop", "stream_stop", views.stream_stop, methods=["POST"])

    # Settings
    add("/settings", "settings", views.settings, methods=["GET", "POST"])
    add("/settings/export", "settings_export", views.settings_export)
    add("/settings/import", "settings_import", views.settings_import, methods=["POST"])
    add("/logs", "logs_page", views.logs_page)
    add("/logs/<name>", "server_log", views.server_log)

    # HLS
    add("/hls/<stub>/live.m3u8", "hls_live", hls_routes.live_playlist)
    add("/hls/<stub>/dvr.m3u8", "hls_dvr", hls_routes.dvr_playlist)
    add("/hls/<stub>/relay.m3u8", "hls_relay", hls_routes.relay_playlist)
    add("/hls/<stub>/seg/<name>", "hls_segment", hls_routes.segment)
    add("/hls/<stub>/fallback/<kind>/<name>", "hls_fallback_segment", hls_routes.fallback_segment)

    # JSON API
    add("/api/streams", "api_streams", api.api_streams)
    add("/api/streams/<stub>", "api_stream", api.api_stream)
    add("/api/streams/<stub>/title", "api_title", api.api_title)
    add("/api/delay", "api_delay", api.api_delay)
    add("/api/test-url", "api_test_url", api.api_test_url, methods=["POST"])
    add("/api/directory", "api_directory", api.api_directory)
    add("/healthz", "healthz", api.healthz)
