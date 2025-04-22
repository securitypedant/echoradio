import os
import subprocess

from mods.streams import update_stream_metadata
from flask import current_app

def delete_stream_supervisor_config(stub):
    # Delete supervisord config
    config_file = os.path.join(current_app.config['DATA_ROOT'], 'supervisord_configs', f'{stub}.conf')

    if os.path.exists(config_file):
        os.remove(config_file)
        return True
    else:
        return False
    
def create_stream_supervisor_config(metadata):
    # Generate supervisord config
    
    config_file = os.path.join(current_app.config['DATA_ROOT'], 'supervisord_configs', f'{metadata['stub']}.conf')
    stream_log_path = os.path.join(current_app.config['STREAMS_ROOT'], metadata['stub'])
    liquidsoap_path = os.path.join(stream_log_path, 'stream.liq')

    conf_content = f"""
[program:{metadata['stub']}]
command=/home/streamer/.opam/4.14.2/bin/liquidsoap {liquidsoap_path}
autostart=false
autorestart=true
killasgroup=true
stopasgroup=true
stderr_logfile={stream_log_path}/sup_err.log
stdout_logfile={stream_log_path}/sup_out.log
user=streamer
"""

    with open(config_file, 'w') as f:
        f.write(conf_content)

def supervisord_control(action='start', service=None):
    """
    Control supervisord with actions like start, stop, restart, update, etc.

    - For 'start', 'stop', 'restart': stream_id is required.
    - For 'update', 'reread', etc: stream_id is optional and ignored.
    """
    allowed_global_actions = {"update", "reread", "reload"}
    allowed_stream_actions = {"start", "stop", "restart"}

    if action in allowed_global_actions:
        cmd = ['supervisorctl', action]
    elif action in allowed_stream_actions:
        if not service:
            return {
                "status": "error",
                "message": f"Action '{action}' requires a stream_id."
            }
        cmd = ['supervisorctl', action, service]
    else:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'."
        }

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        if service:
            if action == "start":
                status = "RUNNING"
            elif action == "stop":
                status = "STOPPED"  
            update_stream_metadata(service, {"status": status})

        return {
            "status": "success",
            "action": action,
            "stream_id": service,
            "message": result.stdout.strip()
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "action": action,
            "stream_id": service,
            "message": e.stderr.strip() if e.stderr else str(e)
        }

    except Exception as ex:
        return {
            "status": "error",
            "action": action,
            "stream_id": service,
            "message": f"Unexpected error: {str(ex)}"
        }