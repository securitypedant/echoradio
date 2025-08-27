from mods.ux import home, stream_control
from mods.status import status, view_log, serve_mp3
from mods.settings import settings
from mods.auth import auth, logout, login
from mods.player import player

def register_routes(app):
    app.add_url_rule("/", "home", home, methods=['GET','POST'])
    app.add_url_rule("/auth", "auth", auth, methods=['GET','POST'])
    app.add_url_rule("/auth/logout", "logout", logout)
    app.add_url_rule("/auth/login", "login", login)
    app.add_url_rule("/settings", "settings", settings, methods=['GET','POST'])
    app.add_url_rule("/player/<stub>", "player", player)
    app.add_url_rule("/stream_control", "stream_control", stream_control, methods=['POST'])
    app.add_url_rule("/status/<stub>", "status", status)
    app.add_url_rule("/stream/<stub>/source/<filename>", "serve_mp3", serve_mp3)
    app.add_url_rule("/logs/<stub>/<filename>", "view_log", view_log)
