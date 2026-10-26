#!/bin/bash
# Starts the web app: gunicorn in production, the Flask dev server (with debugpy) in development.
set -euo pipefail
cd /app
if [ "${FLASK_ENV:-production}" = "development" ]; then
    export FLASK_DEBUG=1
    exec python app.py
fi
exec gunicorn --workers 1 --threads 8 --bind 127.0.0.1:5000 --timeout 120 --access-logfile - app:app
