import os
import time

import pytest

import hls

ORIGIN = 1_700_000_000.0  # multiple of 10


def touch(path, size=100):
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)


def make_stream(tmp_path, segments, fallback=6):
    """segments: list of (start_seconds, duration_seconds)."""
    sdir = tmp_path / "stream"
    (sdir / "hls").mkdir(parents=True)
    (sdir / "fallback" / "silence").mkdir(parents=True)
    for i, (start, dur) in enumerate(segments, 1):
        touch(sdir / "hls" / f"{int(start * 1000)}_{int(dur * 1000)}_{i}.ts")
    for i in range(1, fallback + 1):
        touch(sdir / "fallback" / "silence" / f"{i}_10000.ts")
    return str(sdir)


def continuous(start, count, dur=10.0):
    return [(start + i * dur, dur) for i in range(count)]


def parse(text):
    seq = int([l for l in text.splitlines() if l.startswith("#EXT-X-MEDIA-SEQUENCE")][0].split(":")[1])
    disc = int([l for l in text.splitlines() if l.startswith("#EXT-X-DISCONTINUITY-SEQUENCE")][0].split(":")[1])
    uris = [l for l in text.splitlines() if l and not l.startswith("#")]
    return seq, disc, uris


def test_live_window_is_recorded_when_covered(tmp_path):
    start = ORIGIN + 3600
    sdir = make_stream(tmp_path, continuous(start, 100))
    idx = hls.SegmentIndex(sdir, ORIGIN)
    edge = start + 500  # inside the recording
    text = hls.live_window(idx, "silence", edge, "", count=6)
    seq, disc, uris = parse(text)
    assert len(uris) == 6
    assert all(u.startswith("seg/") for u in uris)
    assert "#EXT-X-DISCONTINUITY\n" not in text
    assert "#EXT-X-PROGRAM-DATE-TIME:2023-11-14T23:13:20.000+00:00" in text or "#EXT-X-PROGRAM-DATE-TIME" in text
    # Sequence numbers: fillers on the grid from ORIGIN to start, then the recorded ones.
    expected_first = int(3600 / 10) + (len(uris) and (int(500 / 10) - 6))
    assert seq == expected_first


def test_gap_is_filled_with_fallback_and_discontinuities(tmp_path):
    start = ORIGIN + 3600
    segs = continuous(start, 10) + continuous(start + 100 + 60, 10)  # 60 s hole
    sdir = make_stream(tmp_path, segs)
    idx = hls.SegmentIndex(sdir, ORIGIN)
    entries = idx.entries_between("silence", start, start + 260)
    kinds = [e.kind for e in entries]
    assert kinds[:10] == ["rec"] * 10
    fill = [e for e in entries if e.kind == "fill"]
    assert len(fill) == 6  # 60 s / 10 s on the grid
    assert all(e.path.startswith("fallback/silence/") for e in fill)
    # Discontinuity at rec->fill and fill->rec; consecutive fillers are continuous except where
    # the filler set wraps back to its first file.
    assert entries[10].discontinuity is True
    inner = [e.discontinuity for e in entries[11:16]]
    assert sum(inner) <= 1
    if any(inner):
        wrap = entries[11 + inner.index(True)]
        assert wrap.path.endswith("/1_10000.ts")
    assert entries[16].discontinuity is True and entries[16].kind == "rec"
    # Sequence numbers are consecutive.
    seqs = [e.seq for e in entries]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    # Rendered playlist over the gap carries the tags.
    text = hls.render_playlist(entries[8:18], "")
    seq, disc, uris = parse(text)
    assert text.count("#EXT-X-DISCONTINUITY\n") == 2 + sum(inner)
    assert disc == entries[8].disc_seq


def test_before_recording_started_everything_is_fallback(tmp_path):
    start = ORIGIN + 48 * 3600
    sdir = make_stream(tmp_path, continuous(start, 5))
    idx = hls.SegmentIndex(sdir, ORIGIN)
    edge = start - 8 * 3600  # delayed instant 8 h before the first recording
    text = hls.live_window(idx, "silence", edge, "", count=6)
    seq, disc, uris = parse(text)
    assert len(uris) == 6 and all(u.startswith("fallback/") for u in uris)
    assert seq == int((edge - ORIGIN) / 10) - 6


def test_prune_keeps_sequence_numbers_stable(tmp_path):
    start = ORIGIN + 3600
    sdir = make_stream(tmp_path, continuous(start, 400))  # 4000 s of audio
    idx = hls.SegmentIndex(sdir, ORIGIN)
    before = {e.path: (e.seq, e.disc_seq) for e in idx.entries_between("silence", start, start + 4000)}
    cutoff = start + 1000
    removed = idx.prune(cutoff, "silence")
    assert removed == 99  # segments ending before the cutoff
    assert os.path.exists(os.path.join(sdir, hls.SegmentIndex.STATE_FILE))
    idx2 = hls.SegmentIndex(sdir, ORIGIN)  # fresh instance loads the persisted base
    after = {e.path: (e.seq, e.disc_seq) for e in idx2.entries_between("silence", cutoff, start + 4000)}
    for path, pair in after.items():
        assert before[path] == pair


def test_prune_across_filler_region_is_stable(tmp_path):
    start = ORIGIN + 3600
    segs = continuous(start, 20) + continuous(start + 200 + 600, 50)  # 10 min hole
    sdir = make_stream(tmp_path, segs)
    idx = hls.SegmentIndex(sdir, ORIGIN)
    # Filler paths repeat cyclically, so key by start time (unique per entry).
    before = {e.start: (e.seq, e.disc_seq, e.path) for e in idx.entries_between("silence", start, start + 1500)}
    idx.prune(start + 500, "silence")  # cutoff inside the hole
    idx2 = hls.SegmentIndex(sdir, ORIGIN)
    after = idx2.entries_between("silence", start + 500, start + 1500)
    assert len(after) > 50
    for e in after:
        assert before[e.start] == (e.seq, e.disc_seq, e.path)


def test_coverage_buckets(tmp_path):
    start = ORIGIN + 3600
    sdir = make_stream(tmp_path, continuous(start, 180))  # 30 minutes
    idx = hls.SegmentIndex(sdir, ORIGIN)
    cov = idx.coverage(start, start + 3600, 1800.0)
    assert cov == pytest.approx([1.0, 0.0])


def test_dvr_window_bounds(tmp_path):
    start = ORIGIN + 3600
    sdir = make_stream(tmp_path, continuous(start, 100))
    idx = hls.SegmentIndex(sdir, ORIGIN)
    edge = start + 900
    text = hls.dvr_window(idx, "silence", edge, 0.1, "")  # 6 minutes
    _seq, _disc, uris = parse(text)
    assert 35 <= len(uris) <= 37


def test_fallback_set_ignores_tiny_segments(tmp_path):
    d = tmp_path / "fb"
    d.mkdir()
    touch(d / "1_80.ts")
    touch(d / "2_10000.ts")
    touch(d / "3_9980.ts")
    touch(d / "4_4500.ts")  # short tail segment: excluded, it would not fit the 10 s grid
    fs = hls.FallbackSet(str(d), "fallback/x")
    assert [n for n, _ in fs.items] == ["2_10000.ts", "3_9980.ts"]
    assert fs.item(1) == ("fallback/x/3_9980.ts", 9.98)
    assert fs.item(2) == ("fallback/x/2_10000.ts", 10.0)


def test_live_backup_maps_gaps_to_shifted_recording(tmp_path):
    # Recording started 1 h after the delayed instant; the live backup should play the recording
    # from (t + shift) for gap slots, advancing continuously and reusing nothing.
    start = ORIGIN + 3600
    sdir = make_stream(tmp_path, continuous(start, 400))  # ~67 min of audio
    idx = hls.SegmentIndex(sdir, ORIGIN)
    shift = 3600.0  # delay(1 h) - lag(0) for the test
    edge = start + 600  # delayed instant: 10 min before... no recording there? start+600 is recorded
    # Use a window entirely before the recording: [start-600, start) -> fillers via live_shift
    entries = idx.entries_between("live", start - 600, start, live_shift=shift)
    assert len(entries) == 60
    assert all(e.kind == "fill" and e.path.startswith("seg/") for e in entries)
    # Each filler is the segment ~1 h later than its timeline position, in order.
    names = [e.path for e in entries]
    assert names == sorted(names) and len(set(names)) == 60
    first_seg_start = int(entries[0].path.split("/")[1].split("_")[0]) / 1000
    assert abs(first_seg_start - (entries[0].start + shift)) < 10.0
    # Continuous: only the first filler carries a discontinuity.
    assert sum(e.discontinuity for e in entries) <= 1
    # Stable across a second build.
    again = idx.entries_between("live", start - 600, start, live_shift=shift)
    assert [(e.seq, e.path) for e in again] == [(e.seq, e.path) for e in entries]


def test_live_backup_uses_silence_for_short_holes(tmp_path):
    start = ORIGIN + 3600
    # 30 s hole (short) and a 10 min hole (long) inside the recording.
    segs = continuous(start, 30) + continuous(start + 300 + 30, 30) + continuous(start + 600 + 30 + 600, 300)
    sdir = make_stream(tmp_path, segs)
    idx = hls.SegmentIndex(sdir, ORIGIN)
    # Live content for hole time t is the recording at t + shift (here 20 min later, which exists).
    entries = idx.entries_between("live", start, start + 2000, live_shift=1200.0)
    short_hole = [e for e in entries if start + 300 <= e.start < start + 330]
    long_hole = [e for e in entries if start + 630 <= e.start < start + 1230]
    assert short_hole and all(e.kind == "fill" and e.path.startswith("fallback/silence/") for e in short_hole)
    assert long_hole and all(e.kind == "fill" and e.path.startswith("seg/") for e in long_hole)
