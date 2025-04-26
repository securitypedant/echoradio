#!/bin/bash
export HOME=/home/streamer
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$HOME/.local/lib/python3.12/site-packages:$PYTHONPATH"

# Use first argument as FLASK_ENV
FLASK_ENV="${FLASK_ENV:-production}"
export FLASK_ENV

env > /tmp/env_from_supervisord.txt

# Automatically set FLASK_DEBUG if in development
if [ "$FLASK_ENV" = "development" ]; then
    export FLASK_DEBUG=1
fi

echo "🔁 Starting Flask app in ${FLASK_ENV} mode..."

if [ "$FLASK_ENV" = "development" ]; then
    exec python3 /app/app.py
else
    exec python3 -m gunicorn app:app -b 0.0.0.0:8080
fi