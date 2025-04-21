import os
import json

from flask import current_app

# This resolves to the folder above where config.py exists
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

class Config:
    # General application settings
    FLASK_ENV=os.environ.get('FLASK_ENV', 'development')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'devsecretthatiseasytoguess')

    # Config and data paths
    DATA_ROOT = os.environ.get('DATA_ROOT', os.path.join(PROJECT_ROOT, 'data'))
    STREAMS_ROOT = os.path.join(DATA_ROOT, 'streams/')
    SERVER_CONFIG_FILE = os.path.join(DATA_ROOT, 'server_config.json')

    # Icecast settings
    ICECAST_PRIVATE_HOST = os.environ.get('ICECAST_PRIVATE_HOST', 'localhost')
    ICECAST_PRIVATE_PORT = os.environ.get('ICECAST_PRIVATE_PORT', '8000')

    # Icecast defaults (fallbacks)
    ENABLE_ADMIN = False
    ADMIN_PASSWORD = ''
    ICECAST_PUBLIC_HOSTNAME = 'localhost'
    ICECAST_PUBLIC_PROTOCOL = 'http'
    ICECAST_PUBLIC_PORT = '8000'
    ICECAST_ADMIN_PASSWORD = 'ChangeMePlease'
    ICECAST_SOURCE_PASSWORD = 'ChangeMePlease'
    ICECAST_MAX_SOURCES = 5

    @classmethod
    def load_json_config(cls):
        """Load additional settings from a JSON config file and override class attributes."""
        try:
            with open(cls.SERVER_CONFIG_FILE) as f:
                config_data = json.load(f)

            for key, value in config_data.items():
                upper_key = key.upper()
                setattr(cls, upper_key, value)  # Always overwrite

        except FileNotFoundError:
            print(f"⚠️ Config file '{cls.SERVER_CONFIG_FILE}' not found. Using defaults.")
        except Exception as e:
            print(f"⚠️ Error reading config file: {e}")