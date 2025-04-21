import os
import json

from flask import current_app
from string import Template
from datetime import datetime
from zoneinfo import ZoneInfo

def calculate_delay_hours(source_tz_str, target_tz_str):
    source_offset = datetime.now(ZoneInfo(source_tz_str)).utcoffset()
    target_offset = datetime.now(ZoneInfo(target_tz_str)).utcoffset()
    delay = (target_offset - source_offset).total_seconds() / 3600
    return int(delay)

def update_stream_metadata(stub, entry):
    metadata_file = os.path.join(current_app.config['STREAMS_ROOT'], stub, 'metadata.json')

    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
    else:
        metadata = {}

    metadata.update(entry)

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

def create_stream_script(stub, metadata, template="template_combined.liq"):
    
    directory = os.path.join(current_app.config['STREAMS_ROOT'], stub)

    # Create the liquidsoap configuration file based on metadata
    ls_template_file = os.path.join('liquidsoap_templates', template)

    # Figure out stream delay.
    delay = calculate_delay_hours(metadata['source_timezone'], metadata['target_timezone'])

    with open(ls_template_file) as f:
        template = Template(f.read())

    ls_config_content = template.substitute({
        "stream_stub": metadata['stub'],
        "stream_input": metadata['url'],    
        "icecast_private_host": current_app.config['ICECAST_PRIVATE_HOST'],
        "icecast_private_port": current_app.config['ICECAST_PRIVATE_PORT'],
        "icecast_source_password": current_app.config['ICECAST_SOURCE_PASSWORD'],
        "stream_name": metadata['name'],
        "stream_description": metadata['description'],
        "stream_mount": metadata['stub'],
        "stream_switch_block": generate_stream_switch_block(delay)
    })

    # Create a Liquidsoap configuration file for the stream
    ls_config_file = os.path.join(directory, "stream.liq")

    with open(ls_config_file, 'w') as f:
        f.write(ls_config_content)
    
def load_all_streams(streams_dir: str) -> list[dict]:
    stream_entries = []

    if not os.path.exists(streams_dir):
        return stream_entries

    for stub in os.listdir(streams_dir):
        meta_path = os.path.join(streams_dir, stub, 'metadata.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                try:
                    metadata = json.load(f)
                    stream_entries.append(metadata)
                except json.JSONDecodeError:
                    continue  # skip corrupted files
    return stream_entries

def generate_stream_switch_block(stream_delay):
    # Names of sources from zero to twentythree
    stream_names = [
        'zero', 'one', 'two', 'three', 'four', 'five',
        'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
        'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
        'seventeen', 'eighteen', 'nineteen', 'twenty',
        'twentyone', 'twentytwo', 'twentythree'
    ]
    
    lines = ["icecast_stream = switch(track_sensitive=false,["]
    for hour in range(24):
        source_index = (hour + stream_delay) % 24
        source_name = stream_names[source_index]
        lines.append(f"   ({{{hour}h}}, {source_name}),")
    lines[-1] = lines[-1].rstrip(',')  # Remove trailing comma on the last entry
    lines.append("])")

    return '\n'.join(lines)


