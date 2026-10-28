"""Per-session diagnostics for the web player.

When "player diagnostics" is switched on in settings, every playlist request and every client-side
event is written to ``<logs>/player.log`` tagged with the player's client id (``c=<id>``, the same
id the player sends with its playlist requests), and nginx logs segment downloads tagged the same
way to ``<logs>/segments.log``. ``lines_for(cid)`` merges the two so one session can be read as a
single timeline next to the log the player itself copies to the clipboard.
"""
from __future__ import annotations

import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler

from mods.config import Config

PLAYER_LOG = os.path.join(Config.LOGS_ROOT, "player.log")
SEGMENTS_LOG = os.path.join(Config.LOGS_ROOT, "segments.log")
SEGMENTS_LOG_MAX_BYTES = 5 * 1024 * 1024
CID_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")

_log: logging.Logger | None = None


def _logger() -> logging.Logger:
    global _log
    if _log is None:
        log = logging.getLogger("echoradio.player")
        log.propagate = False
        log.setLevel(logging.INFO)
        try:
            os.makedirs(Config.LOGS_ROOT, exist_ok=True)
            fh = RotatingFileHandler(PLAYER_LOG, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
            log.addHandler(fh)
        except OSError:
            log.addHandler(logging.NullHandler())
        _log = log
    return _log


def enabled() -> bool:
    return bool(Config.PLAYER_DEBUG)


def valid_cid(cid: str | None) -> str | None:
    return cid if cid and CID_RE.match(cid) else None


def log(stub: str, cid: str, source: str, message: str) -> None:
    """One line: ``<time> | c=<cid> | <stub> | <server|client> | <message>``."""
    if not enabled():
        return
    message = message.replace("\n", " ").strip()
    _logger().info("c=%s | %s | %s | %s", cid, stub, source, message[:600])


def _read_tagged(path: str, cid: str, limit: int) -> list[str]:
    tag = f"c={cid}"
    out: list[str] = []
    for candidate in (path + ".1", path):
        try:
            with open(candidate, encoding="utf-8", errors="replace") as fh:
                out.extend(line.rstrip("\n") for line in fh if tag in line)
        except OSError:
            continue
    return out[-limit:]


def _segment_line(raw: str) -> str:
    # nginx: 2026-10-28T10:11:12+00:00 | c=abc | /hls/x/seg/1.ts | status=200 bytes=160000 time=0.123
    ts = raw[:19].replace("T", " ")
    rest = raw[26:] if len(raw) > 26 and raw[25] == " " else raw[19:].lstrip()
    return f"{ts} {rest}"


def lines_for(cid: str, limit: int = 400) -> list[str]:
    """Server-side lines for one player session, playlists and segments merged in time order."""
    player = _read_tagged(PLAYER_LOG, cid, limit)
    segments = [_segment_line(line) for line in _read_tagged(SEGMENTS_LOG, cid, limit)]
    merged = sorted(player + segments, key=lambda line: line[:19])
    return merged[-limit:]


def trim_segments_log() -> None:
    """nginx has no rotation of its own: truncate the segment log once it grows past the cap.

    nginx opens the file with O_APPEND, so writes after a truncate simply continue at the new end.
    """
    try:
        if os.path.getsize(SEGMENTS_LOG) > SEGMENTS_LOG_MAX_BYTES:
            os.truncate(SEGMENTS_LOG, 0)
    except OSError:
        pass


def summary_header(stub: str, cid: str) -> str:
    return f"# EchoRadio player session c={cid} stream={stub} server-time={time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC"
