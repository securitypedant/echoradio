import os
import json

from flask import render_template, abort, current_app

def player(stub):
    # Load metadata
    metadata_file = os.path.join('data/streams', stub, 'metadata.json')
    if not os.path.exists(metadata_file):
        abort(404)
    with open(metadata_file) as f:
        metadata = json.load(f)
    return render_template(
        "player.html",
        stream=metadata
        ,icecast_public_hostname=f"{current_app.config['ICECAST_PUBLIC_PROTOCOL']}://{current_app.config['ICECAST_PUBLIC_HOSTNAME']}:{current_app.config['ICECAST_PUBLIC_PORT']}",
        )
