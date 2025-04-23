import os 
import re
import json

from zoneinfo import available_timezones
from flask import current_app

from mods.supervisord import supervisord_control

# Group timezones by region prefix (e.g., 'America', 'Europe')
def get_grouped_timezones():
    grouped = {}
    for tz in sorted(available_timezones()):
        if '/' in tz:
            region, city = tz.split('/', 1)
        else:
            region = 'Other'
            city = tz
        grouped.setdefault(region, []).append(tz)
    return grouped

def ensure_data_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def save_stream_metadata(stub, entry):
    directory = os.path.join(current_app.config['STREAMS_ROOT'], stub)
    ensure_data_dir(directory)
    metadata_file = os.path.join(directory, 'metadata.json')

    with open(metadata_file, 'w') as f:
        json.dump(entry, f, indent=2)

def get_stream_metadata(stub):
    metadata_file = os.path.join(current_app.config['STREAMS_ROOT'], stub, 'metadata.json')

    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            return json.load(f)
    else:
        return {}

def make_stub_name(name):
    # Remove all non-alphanumeric characters
    stub = re.sub(r'[^a-zA-Z0-9]', '', name)
    # Optionally, lowercase it
    return stub.lower()

def replace_in_file(filename: str, pattern: str, replacement: str):
    """
    Reads the given file, replaces the first match of the pattern with the replacement,
    and writes the result back to the file.
    
    Args:
        filename (str): Path to the file to modify.
        pattern (str): Regex pattern to search for.
        replacement (str): Replacement string to use.
    """
    with open(filename, "r") as f:
        content = f.read()

    new_content = re.sub(pattern, replacement, content, count=1)

    with open(filename, "w") as f:
        f.write(new_content)

def update_icecast_config(icecast_public_hostname='localhost', 
                          icecast_public_port='8000',
                          icecast_admin_password='ChangeMePlease!',
                          icecast_source_password='ChangeMePlease!',
                          icecast_max_sources=5
                        ):
    """
    Updates the Icecast configuration file with the latest settings.

    Args:
        icecast_public_hostname (str): The hostname for Icecast, defaults to 'localhost'.
        icecast_public_port (str): The port for Icecast, defaults to '8000'.
        icecast_password (str): The password for Icecast, defaults to 'ChangeMePlease!'.
        icecast_max_sources (int): The maximum number of sources for Icecast, defaults to '5'.
    """

    icecast_config_path = os.path.join(current_app.config['DATA_ROOT'], 'icecast.xml')
    
    # Update the hostname
    replace_in_file(icecast_config_path, r'<hostname>.*?</hostname>', f'<hostname>{icecast_public_hostname}</hostname>')

    # Update the port
    # replace_in_file(icecast_config_path, r'<port>.*?</port>', f'<port>{icecast_public_port}</port>')
    # Update the passwords
    replace_in_file(icecast_config_path, r'<admin-password>.*?</admin-password>', f'<admin-password>{icecast_admin_password}</admin-password>')
    replace_in_file(icecast_config_path, r'<source-password>.*?</source-password>', f'<source-password>{icecast_source_password}</source-password>')

    # Other config
    replace_in_file(icecast_config_path, r'<sources>.*?</sources>', f'<sources>{icecast_max_sources}</sources>')

    supervisord_control(action='restart', service='icecast')
