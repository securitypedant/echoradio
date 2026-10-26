"""EchoRadio Flask application factory."""
from __future__ import annotations

import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "2.0.5"


def create_app() -> Flask:
    from mods import state, streams, supervisor
    from mods.auth import admin_enabled, check_csrf, csrf_token, is_admin
    from mods.config import Config
    from mods.logger import logger
    from mods.routes import register_routes
    from mods.utils import public_base_url
    from mods.views import first_use_redirect

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, static_folder=os.path.join(root, "static"),
                template_folder=os.path.join(root, "templates"))
    app.config.from_object(Config)
    Config.apply_server_config(app)
    # nginx (and Cloudflare Tunnel in front of it) set the forwarded headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    register_routes(app)
    app.before_request(first_use_redirect)
    app.before_request(check_csrf)

    from flask import url_for

    def asset_url(filename: str) -> str:
        """Static URL with a cache-busting version derived from the file's mtime."""
        try:
            v = int(os.stat(os.path.join(app.static_folder, filename)).st_mtime)
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)

    @app.context_processor
    def inject_globals():
        return {
            "csrf_token": csrf_token,
            "is_admin": is_admin(),
            "admin_enabled": admin_enabled(),
            "app_version": VERSION,
            "public_base_url": public_base_url,
            "asset_url": asset_url,
        }

    @app.template_filter("pct")
    def pct(value):
        try:
            return f"{round(float(value) * 100)}%"
        except (TypeError, ValueError):
            return "0%"

    logger.info("Echo Radio %s starting (data at %s)", VERSION, Config.DATA_ROOT)
    state.start_housekeeper(lambda: app.config.get("RETENTION_HOURS", 30))

    if os.environ.get("ECHORADIO_AUTOSTART", "1") != "0":
        for meta in streams.all_streams():
            if meta.get("status") == "RUNNING":
                res = supervisor.control("start", meta["stub"])
                logger.info("Autostart %s: %s", meta["stub"], res.get("status"))
    return app
