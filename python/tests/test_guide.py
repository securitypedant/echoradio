"""Parser-level tests for the programme guide adapters (no network)."""
import datetime

import pytest

from mods import guide


def test_iso_helpers():
    assert guide._iso_ts("2026-10-27T06:00:00+00:00") == 1793080800.0
    assert guide._iso_ts("2026-10-27T06:00:00Z") == 1793080800.0
    assert guide._iso_ts("2026-10-27T06:00:00+0000") == 1793080800.0  # ABC style offset
    assert guide._iso_duration("PT3H") == 3 * 3600
    assert guide._iso_duration("PT1H30M") == 5400
    assert guide._iso_duration("P1DT2H") == 26 * 3600


def test_fill_ends_uses_next_start():
    items = [guide._item(100, 0, "b"), guide._item(0, 0, "a")]
    out = guide._fill_ends(items, default_len=50)
    assert [(p["title"], p["start"], p["end"]) for p in out] == [("a", 0, 100), ("b", 100, 150)]


def test_radiodns_pi_parsing(monkeypatch):
    xml = b"""<?xml version="1.0"?>
<epg xmlns="http://www.worlddab.org/schemas/spi/31"><schedule>
 <programme id="crid://x/1">
  <mediumName>Early Breakfast</mediumName><longName>Early Breakfast with Jennifer Reoch</longName>
  <location><time time="2026-10-27T04:00:00+00:00" duration="PT2H30M"/></location>
  <mediaDescription><longDescription>Music to start the day.</longDescription>
   <multimedia url="https://img.example/1.jpg" width="600" height="320"/></mediaDescription>
 </programme>
 <programme id="crid://x/2">
  <mediumName>Best of</mediumName>
  <location><time time="2026-10-27T06:30:00+00:00" duration="PT3H"/></location>
  <credits><person name="Jane Doe"/></credits>
 </programme>
</schedule></epg>"""
    monkeypatch.setattr(guide, "_get", lambda url, **kw: xml)
    guide._cache.clear()
    items = guide._radiodns_day("http://epg.example/{date}_PI.xml", datetime.date(2026, 10, 27))
    assert [p["title"] for p in items] == ["Early Breakfast with Jennifer Reoch", "Best of"]
    assert items[0]["end"] - items[0]["start"] == 9000
    assert items[0]["synopsis"] == "Music to start the day."
    assert items[0]["image"] == "https://img.example/1.jpg"
    assert items[1]["subtitle"] == "Jane Doe"


def test_rte_parsing_local_times(monkeypatch):
    data = b"""[{"active": true, "data": [{}, {"showName": "Morning Ireland", "showTime": "07:00",
        "showEndDate": "2026-10-27 09:00:00", "image": "x.jpg"}]},
        {"active": false, "data": [{"showName": "Late Date", "showTime": "23:00", "showEndDate": "2026-10-28 02:00:00"}]}]"""
    monkeypatch.setattr(guide, "_get", lambda url, **kw: data)
    guide._cache.clear()
    items = guide._rte_day("radio1", datetime.date(2026, 10, 27))
    assert [p["title"] for p in items] == ["Morning Ireland", "Late Date"]
    # 07:00 Dublin on 27 Oct (GMT) == 07:00 UTC
    assert items[0]["start"] == datetime.datetime(2026, 10, 27, 7, tzinfo=datetime.timezone.utc).timestamp()
    assert items[1]["end"] - items[1]["start"] == 3 * 3600


def test_orf_flat_list(monkeypatch):
    data = b"""[{"programTitle": "Radiokolleg", "title": "Was bleibt?", "subtitle": "<p>Vom Sammeln</p>",
                "startISO": "2026-10-27T09:05:00+01:00", "endISO": "2026-10-27T09:30:00+01:00",
                "description": "<b>Desc</b>", "moderator": "Anna"}]"""
    monkeypatch.setattr(guide, "_get", lambda url, **kw: data)
    guide._cache.clear()
    items = guide._orf_day("oe1", datetime.date(2026, 10, 27))
    assert items[0]["title"] == "Radiokolleg"
    assert items[0]["subtitle"] == "Was bleibt? · Anna"
    assert items[0]["synopsis"] == "Desc"
    assert items[0]["end"] - items[0]["start"] == 1500


@pytest.mark.parametrize("url,provider,service", [
    ("http://lsn.lv/bbcradio.m3u8?station=bbc_radio_two&bitrate=96000", "bbc", "bbc_radio_two"),
    ("https://orf-live.ors-shoutcast.at/fm4-q2a", "orf", "fm4"),
    ("https://streaming.abc-cdn.net.au/audio/hls/triplejnsw.m3u8", "abc", "triplej"),
    ("http://icecast.rte.ie/2fm", "rte", "2fm"),
    ("https://kexp-mp3-128.streamguys1.com/kexp128.mp3", "kexp", ""),
])
def test_guess_provider_and_service_offline(url, provider, service, monkeypatch):
    monkeypatch.setattr(guide, "radiodns_lookup", lambda u: "")
    monkeypatch.setattr(guide, "bauer_code_for_url", lambda u: "")
    assert guide.guess_provider(url) == provider
    assert guide.guess_service(provider, url) == service
