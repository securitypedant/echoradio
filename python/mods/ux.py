import os
import re
import shutil
import json
import bcrypt
import glob

from flask import (render_template, 
                   request, 
                   flash, 
                   current_app, 
                   jsonify, 
                   redirect, 
                   url_for, 
                   session
                )

from mods.config import Config

from mods.utils import (get_grouped_timezones,
                        save_stream_metadata, 
                        make_stub_name, 
                        get_stream_metadata,
                        update_icecast_config
                    )
from mods.streams import (load_all_streams,
                          create_stream_script,
                          calculate_delay_hours
                    )  

from mods.supervisord import supervisord_control, delete_stream_supervisor_config, create_stream_supervisor_config

from mods.auth import auth_required

def home():
    stream_data = {}
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'start' or action == 'settings':
            configure_server(request)
    
    # Check for server_config.json and if it doesn't exist, render settings.html
    if not os.path.exists(current_app.config['SERVER_CONFIG_FILE']):
        config = {
            "enable_admin": False,
            "icecast_public_hostname": "localhost",
            "icecast_public_protocol": "http",
            "icecast_public_port": "8000",
            "icecast_source_password": "ChangeMePlease",
            "icecast_admin_password": "ChangeMePlease",
            "icecast_max_sources": 5
        }
        return render_template('settings.html', config=config, first_use=True)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            stream_url = request.form.get('stream_url')
            stream_name = request.form.get('stream_name')
            stream_description = request.form.get('stream_description')
            source_tz = request.form.get('source_tz')
            target_tz = request.form.get('target_tz')

            stream_stub = make_stub_name(stream_name)

            stream_data = {
                "name": stream_name,
                "stub": stream_stub,
                "url": stream_url,
                "status": "STOPPED",
                "description": stream_description,
                "source_timezone": source_tz,
                "target_timezone": target_tz
            }

            save_stream_metadata(stream_stub, stream_data)
            create_stream_script(stream_stub, stream_data)
            create_stream_supervisor_config(stream_data)
            supervisord_control('update')

            flash(f"Stream '{stream_name}' created and will be delayed by {calculate_delay_hours(source_tz, target_tz)} hours.", 'success')

        elif action == 'update':
            if request.form.get('submit') == 'update':
                stream_url = request.form.get('stream_url')
                stream_name = request.form.get('stream_name')
                stream_status = request.form.get('stream_status')
                stream_description = request.form.get('stream_description')
                source_tz = request.form.get('source_tz')
                target_tz = request.form.get('target_tz')
                stream_stub = request.form.get('stub')   

                stream_data = {
                    "name": stream_name,
                    "stub": stream_stub,
                    "url": stream_url,
                    "status": stream_status,
                    "description": stream_description,
                    "source_timezone": source_tz,
                    "target_timezone": target_tz
                }

                if stream_status == "RUNNING":
                    # Stop the stream first before updating the config.
                    supervisord_control('stop', stream_stub)

                create_stream_script(stream_stub, stream_data)            
                save_stream_metadata(stream_stub, stream_data)

                if stream_status == "RUNNING":
                    # Restart stream service after making changes.
                    supervisord_control('start', stream_stub)

        elif action == 'delete':
            stub = request.form.get('stub')
            if stub:
                try:
                    delete_stream(stub)
                    flash(f"Stream '{stub}' deleted successfully.", 'success')
                except FileNotFoundError as e:
                    flash(str(e), 'danger')
                except Exception as e:
                    flash(str(e), 'danger')
            else:
                flash('Radio stream not found', 'danger')
        
        elif action == 'reset':
            stub = request.form.get('stub')
            if stub:
                try:
                    reset_stream(stub)
                    flash(f"Stream '{stub}' reset successfully.", 'success')
                except FileNotFoundError as e:
                    flash(str(e), 'danger')
                except Exception as e:
                    flash(str(e), 'danger')
            else:
                flash('Radio stream not found', 'danger')                
        elif action == 'edit':
            stub = request.form.get('stub')
            stream_data = get_stream_metadata(stub)
            session['edit_stream_data'] = stream_data

        return redirect(url_for('home'))
    elif 'edit_stream_data' in session:
        stream_data = session.pop('edit_stream_data', None)

    timezones_grouped = get_grouped_timezones()
    streams = load_all_streams(current_app.config['STREAMS_ROOT'])

    return render_template('home.html', 
                           timezones_grouped=timezones_grouped,
                           streams=streams,
                           stream_data=stream_data,
                           config=current_app.config,
                           icecast_public_hostname=f"{current_app.config['ICECAST_PUBLIC_PROTOCOL']}://{current_app.config['ICECAST_PUBLIC_HOSTNAME']}:{current_app.config['ICECAST_PUBLIC_PORT']}",
                        )

def stream_control(action=None, stream_id=None):
    """Control a stream either from server code or an Ajax request."""
    # If no parameters sent, assume we're being called from an Ajax request
    if action is None or stream_id is None:
        data = request.get_json(force=True)  # force=True avoids None if no headers
        action = data.get("action")
        stream_id = data.get("stream_id")

    if not action or not stream_id:
        raise ValueError("Both 'action' and 'stream_id' are required")

    result = supervisord_control(action, stream_id)

    # If called via Flask route (Ajax), return JSON
    if request and request.is_json:
        return jsonify(result)

    # Otherwise, return plain Python result
    return result

def reset_stream(stub: str) -> None:
    directory = os.path.join(current_app.config['STREAMS_ROOT'], stub)

    if not os.path.exists(directory):
        raise FileNotFoundError(f"Stream '{stub}' does not exist at {directory}")

    try:
        stream_control(action='stop', stream_id=stub)
        # Reset source folder
        source_dir = os.path.join(directory, "source")
        if os.path.exists(source_dir):
            shutil.rmtree(source_dir)
        os.makedirs(source_dir, exist_ok=True)

        # Delete all .log files at the top level
        for file_path in glob.glob(os.path.join(directory, "*.log")):
            os.remove(file_path)

        stream_control(action='start', stream_id=stub)

    except Exception as e:
        raise RuntimeError(f"Failed to reset stream '{stub}': {e}") from e


def delete_stream(stub):
    directory = os.path.join(current_app.config['STREAMS_ROOT'], stub)

    if not os.path.exists(directory):
        raise FileNotFoundError(f"Stream '{stub}' does not exist.")

    try:
        shutil.rmtree(directory)
        if not delete_stream_supervisor_config(stub):
            raise Exception(f"Supervisor config for '{stub}' could not be deleted.")
        return True
    except Exception as e:
        raise Exception(f"Failed to delete stream '{stub}': {str(e)}") from e
    
def configure_server(request):
    
    enable_admin = 'enable_admin' in request.form
    plain_admin_password = request.form.get('admin_password') if enable_admin else None
    # Hash the password before saving
    if plain_admin_password:
        admin_password = bcrypt.hashpw(plain_admin_password.encode("utf-8"), bcrypt.gensalt())
        admin_password = admin_password.decode("utf-8")
    else:
        admin_password = ""

    icecast_admin_password = request.form.get('icecast_admin_password')
    icecast_source_password = request.form.get('icecast_source_password')
    icecast_public_hostname = request.form.get('icecast_public_hostname')
    icecast_public_protocol = request.form.get('icecast_public_protocol')
    icecast_max_sources = request.form.get('icecast_max_sources')
    icecast_public_port = request.form.get('icecast_public_port')

    # Now save the configuration to server_config.json
    config = {
        "enable_admin": enable_admin,
        "admin_password": admin_password, 
        "icecast_public_hostname": icecast_public_hostname,
        "icecast_public_protocol": icecast_public_protocol,
        "icecast_public_port": icecast_public_port,
        "icecast_source_password": icecast_source_password,
        "icecast_admin_password": icecast_admin_password,
        "icecast_max_sources": icecast_max_sources
    }

    update_icecast_config(
                        icecast_public_hostname=icecast_public_hostname,
                        icecast_public_port=icecast_public_port,
                        icecast_admin_password=icecast_admin_password,
                        icecast_source_password=icecast_source_password,
                        icecast_max_sources=icecast_max_sources
                    )
    
    update_liquidstream_configs(icecast_source_password=icecast_source_password)

    with open(current_app.config['SERVER_CONFIG_FILE'], 'w') as f:
        json.dump(config, f, indent=4)

    # Load the JSON config into the Config class
    Config.load_json_config()
    updated_config = {
        key: getattr(Config, key)
        for key in dir(Config)
            if key.isupper() and not key.startswith('__')
    }

    current_app.config.update(updated_config)

    if not enable_admin and 'logged_in' in session:
        session.pop('logged_in', None)

    flash("Server configuration updated successfully.", 'success')
    return redirect(url_for('home'))

def update_liquidstream_configs(icecast_source_password):
    LIQ_ROOT = current_app.config['STREAMS_ROOT']
    EXCLUDE_DIR = "supervisord_configs"

    for dirpath, dirnames, filenames in os.walk(LIQ_ROOT):
        # Skip the supervisord_configs directory
        if EXCLUDE_DIR in dirpath:
            continue

        for filename in filenames:
            if filename == "stream.liq":
                filepath = os.path.join(dirpath, filename)

                with open(filepath, "r") as f:
                    content = f.read()

                # Replace the password line using regex
                updated_content = re.sub(
                    r'(password\s*=\s*")[^"]*(")',
                    rf'\1{icecast_source_password}\2',
                    content
                )

                if content != updated_content:
                    with open(filepath, "w") as f:
                        f.write(updated_content)                