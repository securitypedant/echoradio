#!/bin/bash
# Fix permissions if needed
chown -R streamer:streamer /app

# Drop to streamer and start supervisord
exec su --preserve-environment -s /bin/bash -c "/usr/bin/supervisord -c /etc/supervisord.conf" streamer
