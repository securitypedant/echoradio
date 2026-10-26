"""HTML pages and form handlers."""
from __future__ import annotations

import os
import shutil
import time
from collections import deque
from zoneinfo import available_timezones

from flask import (Response, abort, current_app, flash, redirect, render_template, request, send_file,
                   session, url_for)

from mods import icecast, state, streams, supervisor
from mods.auth import auth_required, hash_password, is_admin
from mods.config import Config, load_server_config, save_server_config
from mods.logger import logger
from mods.utils import export_config_zip, grouped_timezones, import_config_zip, stream_urls

SERVER_LOGS = ("echoradio.log", "web.log", "maintenance.log", "icecast.log", "nginx.log", "supervisord.log",
               "icecast-access.log", "icecast-error.log")


def first_use() -> bool:
    return not os.path.exists(Config.SERVER_CONFIG_FILE)


def first_use_redirect():
    """Send everything to the setup page until the server has been configured once."""
    if not first_use():
        return None
    allowed = {"settings", "static", "healthz", "login", "about", "manifest", "service_worker",
               "fallback_preview", "api_delay"}
    if request.endpoint in allowed or request.path.startswith("/hls/"):
        return None
    return redirect(url_for("settings"))


def _meta_or_404(name: str) -> dict:
    """Stream by stub or public URL name."""
    meta = streams.resolve(name or "")
    if meta is None:
        abort(404)
    return meta


def _wants_fragment() -> bool:
    return bool(request.headers.get("HX-Request"))


# ------------------------------------------------------------------- pages
def home():
    states = state.all_states()
    return render_template("home.html", streams=states,
                           urls={s["stub"]: stream_urls(s) for s in states},
                           max_streams=int(current_app.config.get("ICECAST_MAX_SOURCES") or 5))


def stream_card(stub: str):
    meta = _meta_or_404(stub)
    s = state.stream_state(meta)
    return render_template("_stream_card.html", s=s, urls=stream_urls(meta))


def about():
    return render_template("about.html")


def player(stub: str):
    meta = _meta_or_404(stub)
    s = state.stream_state(meta)
    return render_template("player.html", s=s, urls=stream_urls(meta))


@auth_required
def stream_detail(stub: str):
    meta = _meta_or_404(stub)
    s = state.stream_state(meta)
    return render_template("status.html", s=s, urls=stream_urls(meta),
                           retention_hours=current_app.config.get("RETENTION_HOURS", 30))


@auth_required
def stream_detail_panel(stub: str):
    meta = _meta_or_404(stub)
    s = state.stream_state(meta)
    return render_template("_stream_detail.html", s=s)


@auth_required
def stream_log(stub: str):
    _meta_or_404(stub)
    try:
        lines = max(10, min(int(request.args.get("lines", 200)), 2000))
    except ValueError:
        lines = 200
    path = os.path.join(streams.stream_dir(stub), "liquidsoap.log")
    text = _tail(path, lines)
    return Response(text, mimetype="text/plain")


def _tail(path: str, lines: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "".join(deque(fh, maxlen=lines))
    except OSError:
        return "(no log yet)\n"


def _log_catalog() -> list[dict]:
    """All viewable logs: server logs plus one liquidsoap log per stream."""
    items = []
    for name in SERVER_LOGS:
        path = os.path.join(Config.LOGS_ROOT, name)
        if os.path.exists(path):
            items.append({"id": name, "label": name, "group": "Server", "path": path})
    for meta in streams.all_streams():
        path = os.path.join(streams.stream_dir(meta["stub"]), "liquidsoap.log")
        items.append({"id": f"stream-{meta['stub']}.log", "label": f"{meta['name']} (liquidsoap)",
                      "group": "Streams", "path": path})
    return items


def _log_path(name: str) -> str | None:
    for item in _log_catalog():
        if item["id"] == name:
            return item["path"]
    return None


@auth_required
def logs_page():
    catalog = _log_catalog()
    selected = request.args.get("file") or (catalog[0]["id"] if catalog else "")
    return render_template("logs.html", catalog=catalog, selected=selected)


@auth_required
def server_log(name: str):
    path = _log_path(name)
    if path is None:
        abort(404)
    try:
        lines = max(50, min(int(request.args.get("lines", 1000)), 20000))
    except ValueError:
        lines = 1000
    return Response(_tail(path, lines), mimetype="text/plain", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------ stream forms
def _parse_stream_form(form, exclude_stub: str | None = None) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = (form.get("stream_name") or "").strip()[:80]
    mount = (form.get("stream_mount") or "").strip().lower()
    url = (form.get("stream_url") or "").strip()
    description = (form.get("stream_description") or "").strip()[:200]
    source_tz = form.get("source_tz") or ""
    target_tz = form.get("target_tz") or ""
    backup = form.get("backup_track") or "birdsong"
    bitrate = form.get("bitrate") or Config.DEFAULT_BITRATE
    zones = available_timezones()
    if not name or not streams.make_stub(name).strip():
        errors.append("Give the stream a name.")
    if not url.lower().startswith(("http://", "https://")):
        errors.append("The stream URL must start with http:// or https://.")
    if source_tz not in zones:
        errors.append("Choose the station's timezone.")
    if target_tz not in zones:
        errors.append("Choose your playback timezone.")
    if backup not in streams.BACKUP_KINDS:
        errors.append("Unknown backup audio choice.")
    if bitrate not in streams.BITRATES:
        errors.append("Unknown bitrate.")
    if mount:
        if not streams.MOUNT_RE.match(mount):
            errors.append("The URL name may only contain lowercase letters, digits, dashes and underscores.")
        elif streams.mount_taken(mount, exclude_stub):
            errors.append(f"The URL name “{mount}” is already used by another stream.")
    fields = {"name": name, "url": url, "description": description, "source_timezone": source_tz,
              "target_timezone": target_tz, "backup_track": backup, "bitrate": bitrate}
    if mount:
        fields["mount"] = mount
    return (fields, errors)


def _form_context(**extra) -> dict:
    ctx = {"timezones": grouped_timezones(), "backup_kinds": streams.BACKUP_KINDS,
           "bitrates": streams.BITRATES}
    ctx.update(extra)
    return ctx


@auth_required
def stream_new():
    if request.method == "POST":
        fields, errors = _parse_stream_form(request.form)
        max_streams = int(current_app.config.get("ICECAST_MAX_SOURCES") or 5)
        if len(streams.all_streams()) >= max_streams:
            errors.append(f"Maximum number of streams reached ({max_streams}). Raise it in Settings.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("stream_form.html", **_form_context(stream=fields, mode="new"))
        stub = streams.unique_stub(fields["name"])
        fields.setdefault("mount", stub)
        if fields["mount"] != stub and streams.mount_taken(fields["mount"]):
            flash(f"The URL name “{fields['mount']}” is already in use.", "danger")
            return render_template("stream_form.html", **_form_context(stream=fields, mode="new"))
        meta = {**fields, "stub": stub, "status": "STOPPED", "created_at": time.time()}
        logger.info("Creating stream %s (%s)", fields["name"], stub)
        meta = streams.materialize(meta, current_app.config["SERVER_CONFIG"], log=logger.info)
        supervisor.reread_update()
        res = supervisor.control("start", stub)
        if res["status"] == "success":
            streams.update_metadata(stub, status="RUNNING")
            flash(f"Stream “{meta['name']}” created and recording. Playback runs {state.delay_info(meta)['delay_text']} behind the station.", "success")
        else:
            flash(f"Stream created but could not start: {res.get('message')}", "warning")
        return redirect(url_for("home"))
    return render_template("stream_form.html", **_form_context(stream={}, mode="new"))


@auth_required
def stream_edit(stub: str):
    meta = _meta_or_404(stub)
    stub = meta["stub"]
    if request.method == "POST":
        fields, errors = _parse_stream_form(request.form, exclude_stub=stub)
        fields.setdefault("mount", stub)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("stream_form.html", **_form_context(stream={**meta, **fields}, mode="edit"))
        was_running = supervisor.process_info(stub).get("statename") == "RUNNING"
        if was_running:
            supervisor.control("stop", stub)
        bitrate_changed = fields["bitrate"] != meta.get("bitrate")
        meta.update(fields)
        if bitrate_changed:
            streams.rebuild_fallback_sets(meta, log=logger.info)
        logger.info("Updating stream %s", stub)
        meta = streams.materialize(meta, current_app.config["SERVER_CONFIG"], log=logger.info)
        supervisor.reread_update()
        if was_running:
            supervisor.control("start", stub)
        flash(f"Stream “{meta['name']}” updated.", "success")
        return redirect(url_for("home"))
    return render_template("stream_form.html", **_form_context(stream=meta, mode="edit"))


@auth_required
def stream_delete(stub: str):
    meta = _meta_or_404(stub)
    logger.info("Deleting stream %s", stub)
    supervisor.control("stop", stub)
    streams.remove_supervisor_conf(stub)
    supervisor.reread_update()
    streams.delete_stream_files(stub)
    state.forget_index(stub)
    flash(f"Stream “{meta['name']}” deleted.", "success")
    return redirect(url_for("home"))


@auth_required
def stream_reset(stub: str):
    meta = _meta_or_404(stub)
    logger.info("Resetting recordings for %s", stub)
    was_running = supervisor.process_info(stub).get("statename") == "RUNNING"
    supervisor.control("stop", stub)
    sdir = streams.stream_dir(stub)
    shutil.rmtree(os.path.join(sdir, "hls"), ignore_errors=True)
    for f in ("hls_index.json", "liquidsoap.log"):
        try:
            os.remove(os.path.join(sdir, f))
        except OSError:
            pass
    os.makedirs(os.path.join(sdir, "hls"), exist_ok=True)
    state.forget_index(stub)
    if was_running:
        supervisor.control("start", stub)
    flash(f"Recordings for “{meta['name']}” were cleared.", "success")
    return redirect(url_for("home"))


def _control(stub: str, action: str):
    meta = _meta_or_404(stub)
    res = supervisor.control(action, stub)
    if res["status"] == "success":
        streams.update_metadata(stub, status="RUNNING" if action == "start" else "STOPPED")
    elif not _wants_fragment():
        flash(f"Could not {action} stream: {res.get('message')}", "danger")
    if _wants_fragment():
        time.sleep(0.3)  # let supervisord report the new state
        return stream_card(stub)
    return redirect(url_for("home"))


@auth_required
def stream_start(stub: str):
    return _control(stub, "start")


@auth_required
def stream_stop(stub: str):
    return _control(stub, "stop")


# ---------------------------------------------------------------- settings
@auth_required
def settings():
    cfg = load_server_config(Config.SERVER_CONFIG_FILE)
    if request.method == "POST":
        errors: list[str] = []
        form = request.form
        new = dict(cfg)
        new["enable_admin"] = "enable_admin" in form
        pw = form.get("admin_password") or ""
        if new["enable_admin"]:
            if pw:
                new["admin_password"] = hash_password(pw)
            elif not cfg.get("admin_password"):
                errors.append("Set an admin password to require admin login.")
        else:
            new["admin_password"] = ""
        for key in ("icecast_admin_password", "icecast_source_password"):
            val = (form.get(key) or "").strip()
            if not val:
                errors.append("Icecast passwords cannot be empty.")
            elif any(c in val for c in "<>&\"'"):
                errors.append("Icecast passwords cannot contain < > & \" or '.")
            new[key] = val
        try:
            new["icecast_max_sources"] = max(1, min(int(form.get("icecast_max_sources") or 5), 50))
            new["dvr_hours"] = max(1, min(int(form.get("dvr_hours") or 4), 24))
            new["retention_hours"] = max(new["dvr_hours"] + 25, min(int(form.get("retention_hours") or 30), 168))
        except ValueError:
            errors.append("Numeric settings must be whole numbers.")
        public = (form.get("public_base_url") or "").strip().rstrip("/")
        if public and not public.lower().startswith(("http://", "https://")):
            errors.append("Public base URL must start with http:// or https://.")
        new["public_base_url"] = public
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("settings.html", config=new, first_use=first_use(), logs=SERVER_LOGS)

        was_first_use = first_use()
        save_server_config(Config.SERVER_CONFIG_FILE, new)
        icecast_keys = ("icecast_admin_password", "icecast_source_password", "icecast_max_sources", "public_base_url")
        if was_first_use or any(new[k] != cfg.get(k) for k in icecast_keys):
            icecast.write_icecast_config(new)
            supervisor.control("restart", "icecast")
        if new["icecast_source_password"] != cfg.get("icecast_source_password"):
            for meta in streams.all_streams():
                streams.write_stream_script(meta, new)
                if supervisor.process_info(meta["stub"]).get("statename") == "RUNNING":
                    supervisor.control("restart", meta["stub"])
        Config.apply_server_config(current_app)
        if not new["enable_admin"]:
            session.pop("logged_in", None)
        elif pw:
            session["logged_in"] = True
        logger.info("Server configuration updated")
        flash("Settings saved." if not was_first_use else "Welcome! Echo Radio is configured. Add your first stream.", "success")
        return redirect(url_for("home"))
    return render_template("settings.html", config=cfg, first_use=first_use(), logs=SERVER_LOGS)


@auth_required
def settings_export():
    return send_file(export_config_zip(), as_attachment=True, download_name="echoradio-config.zip",
                     mimetype="application/zip")


@auth_required
def settings_import():
    file = request.files.get("config_file")
    if not file or not file.filename.lower().endswith(".zip"):
        flash("Upload the .zip exported from Settings.", "danger")
        return redirect(url_for("settings"))
    try:
        imported = import_config_zip(file.stream)
    except Exception as exc:  # noqa: BLE001
        flash(f"Import failed: {exc}", "danger")
        return redirect(url_for("settings"))
    cfg = load_server_config(Config.SERVER_CONFIG_FILE)
    icecast.write_icecast_config(cfg)
    supervisor.control("restart", "icecast")
    for stub in imported:
        meta = streams.load_metadata(stub)
        if meta:
            streams.materialize(meta, cfg, log=logger.info)
    supervisor.reread_update()
    for stub in imported:
        meta = streams.load_metadata(stub)
        if meta and meta.get("status") == "RUNNING":
            supervisor.control("start", stub)
    Config.apply_server_config(current_app)
    logger.info("Configuration imported (%d streams)", len(imported))
    flash(f"Configuration imported ({len(imported)} streams).", "success")
    return redirect(url_for("home"))
