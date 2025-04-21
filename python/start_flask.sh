#!/bin/bash
echo "🔁 Starting Flask app in ${FLASK_ENV:-production} mode..."

if [ "$FLASK_ENV" = "development" ]; then
    exec python3 /app/app.py
else
    # Use python module to ensure it runs regardless of path issues
    exec python3 -m gunicorn app:app -b 0.0.0.0:8080
fi