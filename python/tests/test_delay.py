from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import delay

UTC = timezone.utc
MIN = timedelta(seconds=120)


def wall(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def test_source_wall_clock_matches_listener_wall_clock_half_hour_zone():
    now = datetime(2026, 10, 24, 15, 7, 30, tzinfo=UTC)  # 08:07 in Los Angeles
    instant = delay.source_instant(now, "Asia/Kolkata", "America/Los_Angeles", MIN)
    assert wall(instant, "Asia/Kolkata") == wall(now, "America/Los_Angeles")
    # Kolkata is UTC+5:30, LA is UTC-7 -> 12h30 difference, less than a day so no wrap
    assert delay.delay(now, "Asia/Kolkata", "America/Los_Angeles", MIN) == timedelta(hours=12, minutes=30)


def test_dst_mismatch_window_between_us_and_uk():
    # US DST started 2026-03-08, UK DST starts 2026-03-29: between those dates the gap is 4 h.
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    assert delay.delay(now, "Europe/London", "America/New_York", MIN) == timedelta(hours=4)
    # Once both are on summer time the gap is 5 h again.
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    assert delay.delay(now, "Europe/London", "America/New_York", MIN) == timedelta(hours=5)
    # Early November: UK leaves DST on 2026-10-25, US on 2026-11-01 -> 4 h window again.
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert delay.delay(now, "Europe/London", "America/New_York", MIN) == timedelta(hours=4)


def test_station_ahead_of_listener_needs_no_wrap():
    # Listening in London to a Sydney station: Sydney (UTC+11) reached 10:00 ten hours before London (UTC+1).
    now = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)  # 10:00 London (BST)
    instant = delay.source_instant(now, "Australia/Sydney", "Europe/London", MIN)
    assert wall(instant, "Australia/Sydney") == "10:00"
    assert now - instant == timedelta(hours=10)


def test_station_behind_listener_wraps_to_previous_day():
    # Listening in London to a Los Angeles station: LA's 10:00 is still in the future, so play yesterday's.
    now = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)  # 10:00 London (BST), 02:00 Los Angeles (PDT)
    instant = delay.source_instant(now, "America/Los_Angeles", "Europe/London", MIN)
    assert wall(instant, "America/Los_Angeles") == "10:00"
    assert now - instant == timedelta(hours=16)


def test_same_timezone_replays_yesterday():
    now = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
    assert delay.delay(now, "Europe/London", "Europe/London", MIN) == timedelta(hours=24)


def test_min_delay_pushes_back_a_day():
    now = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
    # Paris is 1 h ahead of London: naive delay is 1 h.
    assert delay.delay(now, "Europe/Paris", "Europe/London", MIN) == timedelta(hours=1)
    # With a 2 h minimum the delay must jump a day.
    assert delay.delay(now, "Europe/Paris", "Europe/London", timedelta(hours=2)) == timedelta(hours=25)


def test_aired_at_and_description():
    now = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
    aired = delay.aired_at(now, "Europe/London", "America/Los_Angeles", MIN)
    assert aired.tzinfo.key == "Europe/London"
    assert aired.strftime("%H:%M") == "08:00"
    assert delay.describe_delay(timedelta(hours=8, minutes=30)) == "8h 30m"
    assert delay.describe_delay(timedelta(hours=8)) == "8h"
    assert delay.describe_delay(timedelta(minutes=45)) == "45m"


@pytest.mark.parametrize("tz,label", [("Europe/London", "UTC+1"), ("Asia/Kolkata", "UTC+5:30"), ("America/Los_Angeles", "UTC-7")])
def test_zone_offset_label(tz, label):
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert delay.zone_offset_label(tz, now) == label
