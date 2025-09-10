import os

from flask import Flask

from mods.routes import register_routes
from mods.infra import check_app_infra
from mods.config import Config
from mods.streams import load_all_streams
from mods.ux import stream_control
from mods.logger import logger

# Load the JSON config into the Config class
Config.load_json_config()

app = Flask(__name__)
logger.info("Starting Flask app...")
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

# Register routes from routes.py
logger.info("Registering routes...")
register_routes(app)

# Check general app structure and required files/folders
logger.info("Checking app infrastructure...")
check_app_infra()

# Check the status of each stream and start if needed.
for stream in load_all_streams(app.config['STREAMS_ROOT']):
    if stream['status'] == 'RUNNING':
        stream_control(action='start', stream_id=stream['stub'])

# Only run the Flask development server if executed directly
if __name__ == '__main__':
    print("Starting Echo Radio Flask app...")
    import debugpy
    if os.environ.get("FLASK_ENV") == "development":
        debugpy.listen(("0.0.0.0", 5678))
        print("🪛 Waiting for debugger to attach...")
        debugpy.wait_for_client()
        app.run(host='0.0.0.0', port=8080, debug=True, use_reloader=False)
    else:
        print("⚠️ Do not run this file in production. Use gunicorn instead.")