# syntax=docker/dockerfile:1
#
# EchoRadio runtime image.
# Liquidsoap comes from Savonet's prebuilt .deb (amd64 + arm64), so no OCaml toolchain is needed.
ARG LIQUIDSOAP_VERSION=2.4.6
ARG LIQUIDSOAP_DEB_SUFFIX=debian-trixie-ocaml4.14.2-3

FROM debian:trixie-slim
ARG LIQUIDSOAP_VERSION
ARG LIQUIDSOAP_DEB_SUFFIX
ARG TARGETARCH
ARG FLASK_ENV=production

ENV DEBIAN_FRONTEND=noninteractive \
    FLASK_ENV=${FLASK_ENV} \
    TZ=UTC \
    DATA_ROOT=/app/data \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# System packages + liquidsoap .deb (FFmpeg is statically linked into the package).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl tzdata icecast2 nginx python3 python3-venv; \
    curl -fsSL -o /tmp/liquidsoap.deb \
        "https://github.com/savonet/liquidsoap/releases/download/v${LIQUIDSOAP_VERSION}/liquidsoap_${LIQUIDSOAP_VERSION}-${LIQUIDSOAP_DEB_SUFFIX}_${TARGETARCH}.deb"; \
    apt-get install -y --no-install-recommends /tmp/liquidsoap.deb; \
    rm -f /tmp/liquidsoap.deb; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; \
    useradd --uid 1000 --create-home --shell /bin/bash streamer; \
    mkdir -p /app/data

# Python virtualenv
COPY python/requirements.txt python/requirements-dev.txt /tmp/req/
RUN set -eux; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/req/requirements.txt; \
    if [ "$FLASK_ENV" = "development" ]; then \
        /opt/venv/bin/pip install --no-cache-dir -r /tmp/req/requirements-dev.txt; \
    fi; \
    rm -rf /tmp/req

# Application
COPY --chown=streamer:streamer python/ /app/
RUN chmod +x /app/entrypoint.sh /app/start_web.sh && rm -rf /app/data && mkdir -p /app/data && chown streamer:streamer /app/data

USER streamer
WORKDIR /app
ENV HOME=/home/streamer

# Pre-compile the liquidsoap standard library cache so stream start-up is fast.
RUN liquidsoap --cache-stdlib

# The entrypoint starts as root only to fix ownership of the mounted data directory,
# then drops to "streamer" (see entrypoint.sh).
USER root

VOLUME ["/app/data"]
EXPOSE 8080 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["bash", "/app/entrypoint.sh"]
