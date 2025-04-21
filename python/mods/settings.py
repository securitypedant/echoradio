import json

from flask import render_template, current_app

def settings():
    # Read in the server_config.json 
    with open(current_app.config['SERVER_CONFIG_FILE'], 'r') as f:
        config = json.load(f)

    return render_template(
        "settings.html",
        config=config
    )