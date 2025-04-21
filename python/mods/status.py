import os 
import xmlrpc.client

from datetime import datetime
from flask import render_template, abort, send_file, current_app
from supervisor.xmlrpc import SupervisorTransport

SUPERVISOR_SOCKET = "unix:///tmp/supervisor.sock"

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

    supervisor_status = get_process_info(stub)
    uptime = get_uptime_from_process_info(supervisor_status)

    return render_template(
        "status.html",
        stub=stub,
        mp3_files=mp3_files,
        supervisor_status=supervisor_status,
        uptime=uptime
    )

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