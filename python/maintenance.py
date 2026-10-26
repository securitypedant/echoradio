"""Background maintenance run once at start-up by supervisord (after the services are up).

* Generates missing fallback segment sets for every stream.
* Converts v1 hourly recordings (``source/HH.mp3``) into the HLS layout, newest first, deleting
  each source file as soon as it has been converted so an interrupted run resumes where it left off.

Runs at low CPU priority so the recorders and the web app stay responsive.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

from mods import streams
from mods.config import Config, load_server_config

LEGACY_HOUR_RE = re.compile(r"^(\d{2})\.mp3$")


def log(msg: str) -> None:
    print(f"[maintenance] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def legacy_files(stub: str) -> list[tuple[datetime, str]]:
    """(air start UTC, path) for each convertible v1 hourly file, newest first."""
    source_dir = os.path.join(streams.stream_dir(stub), "source")
    out = []
    now = datetime.now(timezone.utc)
    for path in glob.glob(os.path.join(source_dir, "*.mp3")):
        m = LEGACY_HOUR_RE.match(os.path.basename(path))
        if not m:
            continue
        hour = int(m.group(1))
        mtime = datetime.fromtimestamp(os.stat(path).st_mtime, tz=timezone.utc)
        day = mtime.date()
        if mtime.hour < hour:
            day = (mtime - timedelta(days=1)).date()
        start = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
        if (now - start) > timedelta(hours=30) or os.stat(path).st_size < 100_000:
            out.append((start, path, False))
        else:
            out.append((start, path, True))
    out.sort(reverse=True)
    return out


def convert_legacy(meta: dict) -> None:
    stub = meta["stub"]
    source_dir = os.path.join(streams.stream_dir(stub), "source")
    if not os.path.isdir(source_dir):
        return
    hls_dir = os.path.join(streams.stream_dir(stub), "hls")
    os.makedirs(hls_dir, exist_ok=True)
    for start, path, convert in legacy_files(stub):
        if not convert:
            log(f"[{stub}] dropping legacy {os.path.basename(path)} (older than retention or empty)")
            os.remove(path)
            continue
        base_ms = int(start.timestamp() * 1000)
        tmp_out = os.path.join(streams.stream_dir(stub), f"migrate_{start:%H}")
        log(f"[{stub}] converting legacy {os.path.basename(path)} (aired {start:%Y-%m-%d %H:%M} UTC)")
        name_expr = ('acc = acc_ref(); d = int_of_float(m.duration * 1000.); acc_ref := acc + d; '
                     '"#{acc}_#{d}_#{m.position}.#{m.extname}"')
        source_def = f'acc_ref = ref({base_ms})\ns = once(single("{path}"))'
        t0 = time.time()
        try:
            res = streams.run_segmenter(source_def, tmp_out, meta.get("bitrate", Config.DEFAULT_BITRATE),
                                        name_expr, timeout=3600)
            ok = res.returncode == 0
        except Exception as exc:  # noqa: BLE001
            log(f"[{stub}] conversion failed: {exc}")
            ok = False
        moved = 0
        for seg in glob.glob(os.path.join(tmp_out, "*.ts")):
            shutil.move(seg, os.path.join(hls_dir, os.path.basename(seg)))
            moved += 1
        shutil.rmtree(tmp_out, ignore_errors=True)
        if moved:
            os.remove(path)  # done with this hour; a restart will not redo it
        log(f"[{stub}] {os.path.basename(path)}: {moved} segments in {time.time() - t0:.0f}s")
    if not glob.glob(os.path.join(source_dir, "*.mp3")):
        shutil.rmtree(source_dir, ignore_errors=True)
    for old in glob.glob(os.path.join(streams.stream_dir(stub), "*.log*")):
        if os.path.basename(old).startswith(("stream.log", "sup_")):
            os.remove(old)


def main() -> int:
    try:
        os.nice(10)
    except OSError:
        pass
    load_server_config(Config.SERVER_CONFIG_FILE)
    all_meta = streams.all_streams()
    for meta in all_meta:
        streams.ensure_fallback_sets(meta, log=log)
    for meta in all_meta:
        convert_legacy(meta)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
