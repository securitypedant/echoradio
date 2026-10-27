"""HLS timeline, segment index and playlist generation for EchoRadio.

Liquidsoap records each station as ~10 s MPEG-TS/AAC segments named
``<epoch>_<position>.ts`` where ``epoch`` is the wall-clock second at which the
segment was opened. This module turns that directory into a continuous
*timeline* of playlist entries: recorded segments where they exist and
codec-matched fallback segments (birdsong, voice, silence or the newest live
audio) where recording was missing. From the timeline it renders

* a time-shifted "live" playlist (sliding window ending at the delayed instant),
* a DVR playlist (long window, seekable in the web player), and
* the relay playlist liquidsoap consumes to feed icecast.

Sequence numbers must be stable across requests and across pruning, so:

* fillers sit on a fixed 10 s grid anchored at the stream's ``timeline_origin``;
* the timeline is always built from a persisted *base* (time, sequence,
  discontinuity count); pruning moves the base forward and re-persists it.

Standard library only.
"""
from __future__ import annotations

import bisect
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

SEGMENT_SECONDS = 10.0
GAP_MIN_SECONDS = 5.0          # a hole shorter than this is left as a PDT jump, not filled
LIVE_MIN_GAP_SECONDS = 120.0   # "live stream" backup only covers holes at least this long; shorter get silence
TARGET_DURATION = 11           # EXT-X-TARGETDURATION (integer, >= every declared duration)
FALLBACK_KINDS = ("birdsong", "voice", "silence", "live")

# Recorded: <start_ms>_<duration_ms>_<position>.ts ; fallback: <position>_<duration_ms>.ts
_SEGMENT_RE = re.compile(r"^(?P<start>\d{12,14})_(?P<dur>\d{1,6})_(?P<pos>\d+)\.ts$")
_FALLBACK_RE = re.compile(r"^(?P<pos>\d+)_(?P<dur>\d{1,6})\.ts$")
MIN_FALLBACK_SECONDS = 9.5     # fillers must be full-length so they fit the 10 s grid


@dataclass(frozen=True)
class Segment:
    start: float
    duration: float
    name: str

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class Entry:
    """One playlist line: a recorded segment or a fallback filler."""
    seq: int
    start: float
    duration: float
    path: str           # URL path relative to /hls/<stub>/
    kind: str           # "rec" or "fill"
    discontinuity: bool  # an EXT-X-DISCONTINUITY tag precedes this entry
    disc_seq: int       # discontinuity tags at or before this entry (own tag included)

    @property
    def end(self) -> float:
        return self.start + self.duration


class FallbackSet:
    """A directory of pre-encoded fallback segments named <position>_<duration_ms>.ts."""

    def __init__(self, directory: str, url_prefix: str):
        self.directory = directory
        self.url_prefix = url_prefix
        self.items: list[tuple[str, float]] = []
        self._mtime: float | None = None
        self.refresh()

    def refresh(self) -> None:
        try:
            mtime = os.stat(self.directory).st_mtime
        except OSError:
            self.items = []
            self._mtime = None
            return
        if mtime == self._mtime:
            return
        items: list[tuple[int, str, float]] = []
        try:
            with os.scandir(self.directory) as it:
                for de in it:
                    m = _FALLBACK_RE.match(de.name)
                    if m:
                        dur = int(m.group("dur")) / 1000.0
                        if dur >= MIN_FALLBACK_SECONDS:
                            items.append((int(m.group("pos")), de.name, dur))
        except OSError:
            self.items = []
            return
        items.sort()
        self.items = [(name, dur) for _pos, name, dur in items]
        self._mtime = mtime

    def __len__(self) -> int:
        return len(self.items)

    def item(self, i: int) -> tuple[str, float]:
        name, dur = self.items[i % len(self.items)]
        return f"{self.url_prefix}/{name}", dur


def _format_pdt(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}+00:00"


class SegmentIndex:
    """Index of one stream's recorded and fallback segments, plus the derived timeline."""

    STATE_FILE = "hls_index.json"

    def __init__(self, stream_dir: str, timeline_origin: float, refresh_interval: float = 2.0):
        self.stream_dir = stream_dir
        self.hls_dir = os.path.join(stream_dir, "hls")
        self.fallback_root = os.path.join(stream_dir, "fallback")
        self.timeline_origin = float(timeline_origin)
        self.refresh_interval = refresh_interval
        self._lock = threading.RLock()
        self._last_refresh = 0.0
        self.segments: list[Segment] = []
        self._entries: list[Entry] = []
        self._entry_starts: list[float] = []
        self._fallbacks: dict[str, FallbackSet] = {}
        self._base = self._load_base()
        self._built_key: tuple | None = None

    # ------------------------------------------------------------------ state
    @property
    def base_time(self) -> float:
        return self._base["time"]

    def _state_path(self) -> str:
        return os.path.join(self.stream_dir, self.STATE_FILE)

    def _load_base(self) -> dict:
        try:
            with open(self._state_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            return {"time": float(data["time"]), "seq": int(data["seq"]),
                    "disc": int(data["disc"]), "first_disc": bool(data.get("first_disc", False))}
        except (OSError, ValueError, KeyError, TypeError):
            return {"time": self.timeline_origin, "seq": 0, "disc": 0, "first_disc": False}

    def _save_base(self) -> None:
        os.makedirs(self.stream_dir, exist_ok=True)
        tmp = self._state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._base, fh)
        os.replace(tmp, self._state_path())

    # --------------------------------------------------------------- scanning
    def scan(self) -> list[Segment]:
        """Read the segment directory (no caching). Returns completed segments after the base."""
        found: list[Segment] = []
        try:
            with os.scandir(self.hls_dir) as it:
                for de in it:
                    m = _SEGMENT_RE.match(de.name)
                    if m:
                        found.append(Segment(start=int(m.group("start")) / 1000.0,
                                             duration=int(m.group("dur")) / 1000.0, name=de.name))
        except FileNotFoundError:
            return []
        found.sort(key=lambda s: (s.start, s.name))
        base_time = self._base["time"]
        segments: list[Segment] = []
        last_end = -1.0
        for seg in found:
            if seg.start < base_time or seg.duration < 0.2:
                continue
            if seg.start < last_end - 0.5:
                continue  # overlapping duplicate (e.g. two recorders ran at once): keep the first
            segments.append(seg)
            last_end = seg.end
        return segments

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_refresh < self.refresh_interval:
                return
            self.segments = self.scan()
            self._last_refresh = now
            self._built_key = None

    def fallback(self, kind: str) -> FallbackSet | None:
        fs = self._fallbacks.get(kind)
        if fs is None:
            fs = FallbackSet(os.path.join(self.fallback_root, kind), f"fallback/{kind}")
            self._fallbacks[kind] = fs
        else:
            fs.refresh()
        return fs if len(fs) else None

    def _fillers(self, kind: str):
        """Pre-encoded filler set for ``kind`` (for "live", the silence set backs up missing live audio)."""
        for candidate in (kind, "silence", "birdsong", "voice"):
            if candidate == "live":
                continue
            fs = self.fallback(candidate)
            if fs is not None:
                return fs
        return None

    # --------------------------------------------------------------- timeline
    def _grid_after(self, t: float) -> float:
        """First grid time >= t."""
        k = math.ceil((t - self.timeline_origin) / SEGMENT_SECONDS - 1e-9)
        return self.timeline_origin + k * SEGMENT_SECONDS

    def _build_entries(self, kind: str, until: float, live_shift: float | None = None) -> None:
        """Build the timeline from the base up to ``until``.

        ``live_shift`` (seconds) is used for the "live" backup kind: a gap at timeline time ``t`` is
        filled with the recording from ``t + live_shift`` (the station as it sounds about now),
        which advances continuously and is stable across reloads.
        """
        live_mode = kind == "live" and live_shift is not None
        key = (len(self.segments), self.segments[-1].name if self.segments else None, kind,
               math.floor(until / SEGMENT_SECONDS), round(live_shift or 0.0))
        if key == self._built_key:
            return
        fillers = self._fillers(kind)
        base = self._base
        entries: list[Entry] = []
        running_disc = base["disc"]
        prev_kind: str | None = None
        prev_fill_idx: int | None = None
        prev_live: Segment | None = None
        starts = [seg.start for seg in self.segments]

        def live_segment_at(t: float) -> Segment | None:
            target = t + live_shift
            i = bisect.bisect_right(starts, target) - 1
            if i >= 0:
                seg = self.segments[i]
                if seg.start <= target < seg.end + 0.5:
                    return seg
            return None

        def add(start: float, duration: float, path: str, kind_: str, disc: bool) -> None:
            nonlocal running_disc
            if not entries:
                disc = base["first_disc"]
            if disc:
                running_disc += 1
            entries.append(Entry(seq=base["seq"] + len(entries), start=start, duration=duration,
                                 path=path, kind=kind_, discontinuity=disc, disc_seq=running_disc))

        def fill(a: float, b: float) -> None:
            """Place fillers on the grid inside [a, b)."""
            nonlocal prev_kind, prev_fill_idx, prev_live
            if fillers is None and not live_mode:
                return
            # Short holes inside a recording get silence; jumping to live audio for a few seconds
            # is far more jarring than a brief pause. Long holes (buffer not filled yet, outages)
            # use the live station.
            use_live = live_mode and (b - a) >= LIVE_MIN_GAP_SECONDS
            t = self._grid_after(a)
            while t < b - GAP_MIN_SECONDS:
                if use_live:
                    seg = live_segment_at(t)
                    if seg is not None:
                        continuous = prev_kind == "fill" and prev_live is not None and abs(seg.start - prev_live.end) < 0.5
                        add(t, seg.duration, f"seg/{seg.name}", "fill", not continuous)
                        prev_kind, prev_fill_idx, prev_live = "fill", None, seg
                        t += SEGMENT_SECONDS
                        continue
                    prev_live = None
                if fillers is None:
                    t += SEGMENT_SECONDS
                    continue
                idx = (base["seq"] + len(entries)) % len(fillers)
                path, dur = fillers.item(idx)
                # Consecutive files of a set carry continuous timestamps; wrapping to the first does not.
                continuous = (prev_kind == "fill" and prev_fill_idx is not None and idx == prev_fill_idx + 1)
                add(t, dur, path, "fill", not continuous)
                prev_kind, prev_fill_idx = "fill", idx
                t += SEGMENT_SECONDS

        t = base["time"]
        for seg in self.segments:
            if seg.start < t:
                continue
            fill(t, seg.start)
            add(seg.start, seg.duration, f"seg/{seg.name}", "rec", prev_kind == "fill")
            prev_kind, prev_fill_idx, prev_live = "rec", None, None
            t = seg.end
        if until > t:
            fill(t, until)

        self._entries = entries
        self._entry_starts = [e.start for e in entries]
        self._built_key = key

    def entries_between(self, kind: str, t_from: float, t_to: float,
                        live_shift: float | None = None) -> list[Entry]:
        """Entries whose start lies in [t_from, t_to)."""
        self.refresh()
        with self._lock:
            self._build_entries(kind, t_to, live_shift)
            lo = bisect.bisect_left(self._entry_starts, t_from)
            hi = bisect.bisect_left(self._entry_starts, t_to)
            return self._entries[lo:hi]

    def entries_ending_at(self, kind: str, t_to: float, count: int,
                          live_shift: float | None = None) -> list[Entry]:
        """The last ``count`` entries starting before ``t_to``."""
        self.refresh()
        with self._lock:
            self._build_entries(kind, t_to, live_shift)
            hi = bisect.bisect_left(self._entry_starts, t_to)
            return self._entries[max(0, hi - count):hi]

    # -------------------------------------------------------------- reporting
    def coverage(self, t_from: float, t_to: float, bucket_seconds: float = 3600.0) -> list[float]:
        """Fraction of each bucket in [t_from, t_to) that has recorded audio."""
        self.refresh()
        buckets = max(1, int(math.ceil((t_to - t_from) / bucket_seconds - 1e-9)))
        covered = [0.0] * buckets
        for seg in self.segments:
            if seg.end <= t_from or seg.start >= t_to:
                continue
            b0 = int((max(seg.start, t_from) - t_from) // bucket_seconds)
            b1 = int((min(seg.end, t_to) - t_from - 1e-6) // bucket_seconds)
            for b in range(b0, min(b1, buckets - 1) + 1):
                bs = t_from + b * bucket_seconds
                covered[b] += max(0.0, min(seg.end, bs + bucket_seconds) - max(seg.start, bs))
        return [min(1.0, c / bucket_seconds) for c in covered]

    def newest_start(self) -> float | None:
        """Start time of the newest segment file on disk (including the one being written)."""
        try:
            with os.scandir(self.hls_dir) as it:
                starts = [int(m.group("start")) / 1000.0 for de in it if (m := _SEGMENT_RE.match(de.name))]
        except FileNotFoundError:
            return None
        return max(starts) if starts else None

    def oldest_start(self) -> float | None:
        self.refresh()
        return self.segments[0].start if self.segments else None

    def disk_bytes(self) -> int:
        total = 0
        try:
            with os.scandir(self.hls_dir) as it:
                for de in it:
                    if de.is_file():
                        total += de.stat().st_size
        except FileNotFoundError:
            pass
        return total

    # ---------------------------------------------------------------- pruning
    def prune(self, before: float, kind: str = "silence", live_shift: float | None = None) -> int:
        """Delete segments ending before ``before`` and move the timeline base forward."""
        removed = 0
        with self._lock:
            self.refresh(force=True)
            self._build_entries(kind, max(before, time.time()), live_shift)
            keep_from = next((e for e in self._entries if e.end >= before), None)
            cutoff_start = keep_from.start if keep_from else before
            for seg in self.segments:
                if seg.start < cutoff_start and seg.end < before:
                    removed += self._unlink(seg.name)
            if keep_from is not None and keep_from.start > self._base["time"]:
                self._base = {"time": keep_from.start, "seq": keep_from.seq,
                              "disc": keep_from.disc_seq - (1 if keep_from.discontinuity else 0),
                              "first_disc": keep_from.discontinuity}
                self._save_base()
            elif keep_from is None and self._entries:
                last = self._entries[-1]
                self._base = {"time": self._grid_after(before), "seq": last.seq + 1,
                              "disc": last.disc_seq, "first_disc": True}
                self._save_base()
            self._last_refresh = 0.0
            self._built_key = None
        return removed

    def _unlink(self, name: str) -> int:
        try:
            os.unlink(os.path.join(self.hls_dir, name))
            return 1
        except OSError:
            return 0


# ------------------------------------------------------------------ rendering
def render_playlist(entries: Iterable[Entry], url_base: str) -> str:
    entries = list(entries)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{TARGET_DURATION}"]
    if not entries:
        lines += ["#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-DISCONTINUITY-SEQUENCE:0"]
        return "\n".join(lines) + "\n"
    first = entries[0]
    lines.append(f"#EXT-X-MEDIA-SEQUENCE:{first.seq}")
    lines.append(f"#EXT-X-DISCONTINUITY-SEQUENCE:{first.disc_seq}")
    for i, e in enumerate(entries):
        if e.discontinuity and i > 0:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{_format_pdt(e.start)}")
        lines.append(f"#EXTINF:{e.duration:.3f},")
        lines.append(f"{url_base}/{e.path}" if url_base else e.path)
    return "\n".join(lines) + "\n"


def live_window(index: SegmentIndex, kind: str, edge: float, url_base: str, count: int = 6,
                live_shift: float | None = None) -> str:
    """Sliding live playlist whose newest entry starts before ``edge``."""
    return render_playlist(index.entries_ending_at(kind, edge, count, live_shift), url_base)


def dvr_window(index: SegmentIndex, kind: str, edge: float, hours: float, url_base: str,
               live_shift: float | None = None) -> str:
    start = max(index.base_time, edge - hours * 3600.0)
    return render_playlist(index.entries_between(kind, start, edge, live_shift), url_base)
