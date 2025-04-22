# Use the Savonet file for the base
# FROM savonet/liquidsoap:v2.3.0
FROM ubuntu:noble

# Accept a build-time argument
ARG FLASK_ENV=production
ENV FLASK_ENV=${FLASK_ENV}

# Install basic system dependencies
RUN apt-get update && apt-get install -y \
    icecast2 supervisor python3 python3-pip nano

# Install Liquidsoap via opam
# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl git m4 bubblewrap unzip build-essential \
    pkg-config opam sudo \
    libmp3lame-dev libcurl4-gnutls-dev libfaad-dev libmad0-dev libtag1-dev \
    libavcodec-dev libavdevice-dev libavfilter-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -s /bin/bash streamer && \
    mkdir -p /app/data/logs/

# Create a dedicated group for supervisor access
RUN groupadd -r supervisor && \
    usermod -aG supervisor streamer

# Switch to non-root user
USER streamer
WORKDIR /home/streamer

# Initialize OPAM and install liquidsoap
RUN opam init --bare --disable-sandboxing && \
    opam switch create 4.14.2 && \    
    eval $(opam env) && \
    opam update && \
    opam install -y opam-depext && \
    opam depext -y ffmpeg taglib mad lame faad cry liquidsoap && \
    opam install -y ffmpeg taglib mad lame faad cry liquidsoap

# Setup Liquidsoap PATH for future shells
ENV OPAMROOT=/home/streamer/.opam
ENV PATH=/home/streamer/.opam/4.14.2/bin:$PATH

# Configure application environment
WORKDIR /app

# Setup python environment
COPY python/ /app
RUN pip install --break-system-packages -r /app/requirements.txt
RUN rm -rf /app/data/streams /app/data/supervisord_configs

# Optional: install extra tools in dev
RUN if [ "$FLASK_ENV" = "development" ]; then pip install --break-system-packages debugpy; fi

USER root
# Install and configure logrotation
RUN apt-get update && apt-get install -y logrotate
COPY logrotate_configs/iceandsuper /etc/logrotate.d/iceandsuper
COPY logrotate_configs/streams /etc/logrotate.d/streams

# Configure Icecast and supervisor
COPY supervisord.conf /etc/supervisord.conf
# Make sure streamer owns the /app directory
RUN chmod +x /app/start_flask.sh
RUN chown -R streamer:streamer /app

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]

# Expose ports (8000 for Icecast, 8080 for Flask)
EXPOSE 8000 8080

# Health check to ensure processes are running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD pgrep -u streamer -f "icecast2" || exit 1