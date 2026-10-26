#!/bin/bash
# Container entrypoint.
#
# Starts as root only long enough to make sure the data directory (a volume or bind mount that
# is usually root-owned when first created, e.g. in Docker Swarm) belongs to the app user, then
# drops privileges to "streamer" and re-executes itself. Everything else runs unprivileged.
set -euo pipefail
export DATA_ROOT="${DATA_ROOT:-/app/data}"
APP_USER="${APP_USER:-streamer}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_ROOT" /tmp/nginx
    # Only touch files that are not already owned by the app user (fast when nothing to do).
    find "$DATA_ROOT" /tmp/nginx ! -user "$APP_USER" -exec chown "$APP_USER:$APP_USER" {} + 2>/dev/null || true
    exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups bash "$0" "$@"
fi

export HOME="${HOME:-/home/$APP_USER}"
mkdir -p /tmp/nginx
if ! mkdir -p "$DATA_ROOT" 2>/dev/null || [ ! -w "$DATA_ROOT" ]; then
    echo "ERROR: $DATA_ROOT is not writable by uid $(id -u)." >&2
    echo "       Either let the container start as root (default) so it can fix ownership, or" >&2
    echo "       chown the mounted directory to uid $(id -u) on the host." >&2
    exit 1
fi

cd /app
python -m bootstrap
exec supervisord -c /app/supervisord.conf
