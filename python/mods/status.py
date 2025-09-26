import os 
import re
import xmlrpc.client

from datetime import datetime
from flask import render_template, abort, send_file, current_app, Response
from supervisor.xmlrpc import SupervisorTransport

SUPERVISOR_SOCKET = "unix:///tmp/supervisor.sock"

def serve_mp3(stub, filename):
    directory = os.path.join("data", "streams", stub, "source")
    file_path = os.path.join(directory, filename)

    # Open the file in binary mode
    def generate():
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            while chunk:
                yield chunk
                chunk = f.read(8192)

    return Response(
        generate(),
        mimetype="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="%s"' % filename,
            "Accept-Ranges": "bytes"
        }
    )

def status(stub):
    source_path = os.path.join(current_app.config['STREAMS_ROOT'], stub, 'source')
    
    mp3_files = []
    if os.path.isdir(source_path):
        for filename in sorted(os.listdir(source_path)):
            if filename.lower().endswith(".mp3"):
                full_path = os.path.join(source_path, filename)
                stats = os.stat(full_path)
                mp3_files.append({
                    "name": filename,
                    "size": round(stats.st_size / (1024 * 1024), 2),  # MB
                    "last_modified": datetime.fromtimestamp(stats.st_mtime)
                })

    latest_file = max(mp3_files, key=lambda f: f['last_modified']) if mp3_files else None
    playing_file = get_now_playing(stub)

    supervisor_status = get_process_info(stub)
    uptime = get_uptime_from_process_info(supervisor_status)

    return render_template(
        "status.html",
        stub=stub,
        mp3_files=mp3_files,
        latest_file=latest_file,
        playing_file=playing_file,
        supervisor_status=supervisor_status,
        uptime=uptime
    )

def get_now_playing(stub):
    log_path = f"/app/data/streams/{stub}/stream.log"
    try:
        with open(log_path, "r") as f:
            for line in reversed(f.readlines()):
                if "Switch to single." in line:
                    match = re.search(r"single\.(\d+)", line)
                    if match:
                        return f"{match.group(1)}.mp3"
    except FileNotFoundError:
        return "Unknown"

def view_log(stub, filename):
    if stub == '_server':
        base_path = os.path.join(current_app.config['DATA_ROOT'], 'logs')
    else:
        base_path = os.path.join(current_app.config['STREAMS_ROOT'], stub)
    log_path = os.path.join(base_path, f'{filename}')

    if not os.path.exists(log_path):
        abort(404, "Log file not found")

    return send_file(log_path, mimetype="text/plain")

def get_supervisor_proxy():
    socket_path = "/tmp/supervisor.sock"
    transport = SupervisorTransport(None, None, f'unix://{socket_path}')
    return xmlrpc.client.ServerProxy('http://localhost', transport=transport)

def get_process_info(program_name):
    proxy = get_supervisor_proxy()
    try:
        return proxy.supervisor.getProcessInfo(program_name)
    except xmlrpc.client.Fault as e:
        return {"error": str(e)}

def get_uptime_from_process_info(info):
    if info["statename"] != "RUNNING":
        return "Not running"

    start = datetime.fromtimestamp(info["start"])
    now = datetime.fromtimestamp(info["now"])
    uptime = now - start

    # Format nicely: "1h 12m 5s"
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    if seconds or not parts: parts.append(f"{seconds}s")

    return " ".join(parts)