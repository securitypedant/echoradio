"""Admin login, per-request authorization and CSRF protection."""
from __future__ import annotations

import hmac
import json
import secrets
from functools import wraps

import bcrypt
from flask import abort, current_app, flash, redirect, render_template, request, session, url_for

from mods.logger import logger


def admin_enabled() -> bool:
    return bool(current_app.config.get("ENABLE_ADMIN"))


def is_admin() -> bool:
    """True when no admin password is required or the session is logged in."""
    return (not admin_enabled()) or bool(session.get("logged_in"))


def auth_required(view):
    """Require an admin session when admin mode is on. Returns 401 JSON for API/htmx calls."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if is_admin():
            return view(*args, **kwargs)
        if request.path.startswith("/api/") or request.headers.get("HX-Request"):
            abort(401)
        session["next"] = request.full_path if request.method == "GET" else url_for("home")
        return redirect(url_for("login"))
    return wrapper


def check_admin_password(password: str) -> bool:
    try:
        with open(current_app.config["SERVER_CONFIG_FILE"], encoding="utf-8") as fh:
            stored = json.load(fh).get("admin_password") or ""
    except (OSError, ValueError):
        return False
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def login():
    if not admin_enabled():
        return redirect(url_for("home"))
    if request.method == "POST":
        password = request.form.get("admin_password", "")
        if password and check_admin_password(password):
            session["logged_in"] = True
            session.permanent = True
            logger.info("Admin logged in")
            nxt = session.pop("next", None) or url_for("home")
            return redirect(nxt)
        flash("Invalid password", "danger")
    return render_template("auth.html")


def logout():
    session.pop("logged_in", None)
    logger.info("Admin logged out")
    flash("Logged out", "success")
    return redirect(url_for("home"))


# ------------------------------------------------------------------ CSRF
def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def check_csrf() -> None:
    """before_request hook: every state-changing request must carry the session token."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    if request.path.startswith("/hls/"):
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    if request.is_json and not sent:
        sent = (request.get_json(silent=True) or {}).get("csrf_token", "")
    expected = session.get("_csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Invalid or missing CSRF token. Reload the page and try again.")
