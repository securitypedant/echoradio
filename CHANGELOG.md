# Changelog

## 2.0.7 — 2026-10-27

- Fix relay stalls in production ("Latency is too high: we must catchup N seconds" on
  `clock.icecast`, Icecast EPIPE drops): the relay now reads playlists and segments through nginx
  (gunicorn closed idle keep-alive connections after 2 s, making ffmpeg report
  "Error reading HTTP response: End of file" and stall), gunicorn keep-alive raised to 75 s, and
  both the source input and the relay input run in their own clocks behind `buffer()` so a slow
  fetch can never stall the recorder or the Icecast output.

## 2.0.6 — 2026-10-26

- Recorder runs on the steady CPU clock with a 30 s input buffer, so stalls and bursts from flaky
  HLS/Icecast sources no longer leave holes in the recording (previously dozens per hour on the
  BBC relay, each one a jump during playback).
- The "live stream" backup only covers holes of two minutes or more; shorter holes get silence
  instead of a jarring jump to live audio.
- Player: rewinding no longer snaps back to the live point after a couple of minutes; the second
  clock shows your current time so the station/you difference is visible while rewound.

## 2.0.5 — 2026-10-26

- URL test reports redirects and warns when the target is a geo-restriction message or a fixed-length file rather than a live stream.
- Stream cards and the player say "starting (about a minute)" while the live-stream backup waits for its first minute of recording.

## 2.0.4 — 2026-10-26

- MP3 relay sends a meaningful ICY title ("11:21 London time", or the fallback state) instead of
  garbled segment metadata; song titles announced in-band by the source are recorded with
  timestamps and replayed time-shifted in the ICY title, the cards, the player and the lock screen.
- Optional artwork URL per stream (auto-filled from the directory), shown on cards, the player and
  the phone lock screen; the Icecast mount advertises the player page as the stream URL.
- Player: compact header (small artwork, title, route and delay on one row) and tighter spacing so all
  controls fit on a phone screen without scrolling.

## 2.0.3 — 2026-10-25

- Streams have an editable **URL name** (Icecast mount), used for the `/listen/`, HLS and player
  links; defaults to the name-derived value and must be unique.
- **Browse stations** in the add/edit form: searches a curated BBC list and the community
  Radio Browser index, fills in name, URL and description, and pre-selects the station timezone
  when the country has a single one.
- Player: much larger play button and a four-button grid (top of hour, back/ahead 30 s, live) sized
  for use in a car; volume slider hidden on touch devices. Safari and iOS use the built-in HLS
  player; playback errors now say what failed.
- Listener count includes web-player (HLS) listeners, not just Icecast MP3 listeners.
- The "Live stream" backup now plays the station continuously (about a minute behind real time)
  while the buffer fills, instead of jumping between recent segments.
- Sleep timer shows the remaining time counting down.
- Manage menu on stream cards no longer renders behind neighbouring cards.
- Copyable stream links keep the port when the UI is served on a non-standard port.
- Dropdowns on the player page (sleep timer) work after arriving via a Listen button: global
  scripts moved to the document head so the same-document navigation does not load them twice.

## 2.0.2 — 2026-10-25

- Start-up no longer blocks on slow work. Fallback audio generation and the conversion of v1 hourly
  recordings now run in a background maintenance task after nginx, Icecast and the web app are up,
  so health checks pass and Swarm no longer restarts the task mid-conversion. Each converted hour is
  removed as soon as it is done, so an interrupted conversion resumes instead of starting over.
- Health check start period raised to two minutes.

## 2.0.1 — 2026-10-25

- Fix start-up failure (`PermissionError: /app/data/secret_key`) when the data volume is owned by
  root, as is typical for bind mounts and Docker Swarm volumes. The container now starts as root,
  fixes ownership of the data directory, then drops privileges to the `streamer` user before
  running anything. A missing or unwritable data directory produces a clear error instead of a
  traceback.

## 2.0.0 — 2026-10-25

A ground-up rework of the recording engine, the container and the web UI.

### Recording and playback
- Stations are now recorded as 10-second AAC/MPEG-TS HLS segments instead of 24 hourly MP3 files.
- The time shift is computed on every request from the station and listener timezones. Half-hour
  zones and daylight-saving changes on either side are handled exactly; the old whole-hour,
  computed-once model is gone.
- Gaps in the recording (station offline, buffer still filling) are filled with codec-matched
  fallback audio (bird song, voice, silence) or the live station, spliced with HLS discontinuities.
- New web player with a scrubbable timeline across the recent buffer, catch-up from the start of
  the hour, lock-screen / headset controls (Media Session), sleep timer and an installable PWA.
- Every stream still has a plain MP3 URL (`/listen/<stream>`) for smart speakers and car apps;
  liquidsoap relays the time-shifted playlist to Icecast.
- Configurable retention (default 30 h), rewind window (default 4 h) and per-stream bitrate.
- Log viewer (Settings → Logs) with search, regular expressions, errors-only filter, follow mode
  and download, covering the server logs and each stream's liquidsoap log.

### Container
- Liquidsoap 2.4.6 installed from Savonet's prebuilt package (amd64 and arm64). The image builds
  in under a minute instead of compiling OCaml for an hour.
- Base image is `debian:trixie-slim`; everything runs as the unprivileged `streamer` user.
- nginx fronts the web UI, HLS and the Icecast relay on a single port (8080). Port 8000 is still
  exposed for direct Icecast access.
- cron and logrotate are gone; supervisord, Icecast and the app rotate their own logs.
- `/app/data` is a declared volume; `docker-compose.yaml` uses a named volume so upgrades keep
  your configuration and recordings.
- `HEALTHCHECK` now queries the app (`/healthz`).

### Security
- Admin mode is enforced server-side on every management route (previously only hidden in the UI).
- A random Flask secret key is generated and persisted on first start (override with `SECRET_KEY`).
- CSRF protection on all forms and API calls; `SameSite=Lax`, `HttpOnly` session cookie.
- Icecast passwords are masked in the settings page.

### Upgrading from 1.x
- Settings and stream definitions are kept. v1 hourly recordings are converted into the new
  segment layout where possible; otherwise the buffer refills over the next day while fallback
  audio plays.
- The Icecast public hostname / protocol / port settings were replaced by an optional
  "Public address", since the UI and the streams now share one origin.
- If you ran 1.x without a volume, export the configuration from the old Settings page and import
  it into 2.0.
