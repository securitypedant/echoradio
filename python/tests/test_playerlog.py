"""Player diagnostics log: tagging, merging with the nginx segment log, and settings clamps."""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mods import playerlog  # noqa: E402
from mods.config import Config, SERVER_DEFAULTS, clamp_tunable, load_server_config  # noqa: E402


def _use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(playerlog, "PLAYER_LOG", str(tmp_path / "player.log"))
    monkeypatch.setattr(playerlog, "SEGMENTS_LOG", str(tmp_path / "segments.log"))
    monkeypatch.setattr(Config, "PLAYER_DEBUG", True)
    log = logging.getLogger("echoradio.player.test")
    log.propagate = False
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(str(tmp_path / "player.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.handlers = [fh]
    monkeypatch.setattr(playerlog, "_log", log)


def test_lines_are_tagged_and_merged_in_time_order(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    playerlog.log("bbc", "abc12345", "server", "playlist dvr entries=3")
    playerlog.log("bbc", "other999", "server", "playlist dvr entries=9")
    playerlog.log("bbc", "abc12345", "client", "10:00:00.000 media waiting\nsecond line")
    # An nginx segment line stamped a day earlier must sort first and gain a readable timestamp.
    (tmp_path / "segments.log").write_text(
        "2020-01-01T00:00:00+00:00 | c=abc12345 | /hls/bbc/seg/1_10000_1.ts | status=200 bytes=5 time=0.010\n"
        "2020-01-01T00:00:01+00:00 | c=other999 | /hls/bbc/seg/2_10000_2.ts | status=200 bytes=5 time=0.010\n")
    lines = playerlog.lines_for("abc12345")
    assert len(lines) == 3
    assert lines[0].startswith("2020-01-01 00:00:00 | c=abc12345 | /hls/bbc/seg/1_10000_1.ts")
    assert "| bbc | server | playlist dvr entries=3" in lines[1]
    assert lines[2].endswith("| bbc | client | 10:00:00.000 media waiting second line")
    assert not any("other999" in line for line in lines)


def test_logging_is_a_no_op_when_diagnostics_are_off(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(Config, "PLAYER_DEBUG", False)
    playerlog.log("bbc", "abc12345", "server", "ignored")
    assert playerlog.lines_for("abc12345") == []
    assert playerlog.valid_cid("abc12345") == "abc12345"
    assert playerlog.valid_cid("../etc") is None and playerlog.valid_cid("") is None


def test_segments_log_is_truncated_past_the_cap(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(playerlog, "SEGMENTS_LOG_MAX_BYTES", 10)
    (tmp_path / "segments.log").write_text("x" * 50)
    playerlog.trim_segments_log()
    assert (tmp_path / "segments.log").stat().st_size == 0


def test_tunables_are_clamped_and_defaulted(tmp_path):
    assert clamp_tunable("player_buffer_seconds", 5) == 20          # below the minimum
    assert clamp_tunable("player_buffer_seconds", "1000") == 300    # above the maximum
    assert clamp_tunable("player_buffer_seconds", "junk") == SERVER_DEFAULTS["player_buffer_seconds"]
    assert clamp_tunable("player_buffer_hole_seconds", 0.25) == 0.25  # float tunable keeps decimals
    path = tmp_path / "server_config.json"
    path.write_text('{"player_debug": 1, "min_delay_seconds": 1, "source_buffer_seconds": "7"}')
    cfg = load_server_config(str(path))
    assert cfg["player_debug"] is True
    assert cfg["min_delay_seconds"] == 30
    assert cfg["source_buffer_seconds"] == 7
    assert cfg["relay_buffer_seconds"] == SERVER_DEFAULTS["relay_buffer_seconds"]
