"""Unit tests for OVapi parsing — no network involved.

``tpc_sample.json`` mirrors the /tpc/<TPC> response format (dynamic TPC key,
Stop + Passes, naive local timestamps). Regenerate it from the live API with:

    python scripts/find_tpc.py 54460130 54460131 --line 385 --dest "Den Haag" \
        --save-fixture tests/fixtures/tpc_live.json

``test_live_fixture_parses`` picks that capture up automatically if present.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.ovapi import (
    OVAPI_TZ,
    Pass,
    build_departures,
    parse_ovapi_time,
    parse_tpc_response,
)
from app.poller import DepartureCache

FIXTURES = Path(__file__).parent / "fixtures"

# Reference "now" matching the sample fixture: 12 July 2026, 16:50 NL time.
NOW_NL = datetime(2026, 7, 12, 16, 50, 0, tzinfo=OVAPI_TZ)


@pytest.fixture()
def sample_payload() -> dict:
    return json.loads((FIXTURES / "tpc_sample.json").read_text())


@pytest.fixture()
def sample_passes(sample_payload) -> list:
    _, passes = parse_tpc_response(sample_payload)
    return passes


def test_parse_stop_name_and_pass_count(sample_payload):
    stop_name, passes = parse_tpc_response(sample_payload)
    assert stop_name == "Katwijk, Gemeentehuis"
    assert len(passes) == 5


def test_time_parsing_is_europe_amsterdam():
    dt = parse_ovapi_time("2026-07-12T16:58:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 2 * 3600  # CEST in July
    # Same instant as 14:58 UTC
    assert dt.astimezone(timezone.utc).hour == 14


def test_filter_sort_and_delay_for_line_385(sample_passes):
    departures = build_departures(sample_passes, now=NOW_NL, line_filter=("385",), limit=4)

    assert [d["line"] for d in departures] == ["385", "385", "385"]
    assert all(d["destination"] == "Den Haag CS" for d in departures)
    assert all(d["transport_type"] == "BUS" for d in departures)

    # Sorted on expected departure time.
    expected_times = [d["expected"] for d in departures]
    assert expected_times == sorted(expected_times)
    assert expected_times[0] == "2026-07-12T16:59:30+02:00"

    # Delay = Expected - Target: 90s rounds to 2 minutes; on-time trips get 0.
    assert [d["delay_minutes"] for d in departures] == [2, 0, 0]
    assert [d["minutes_until"] for d in departures] == [9, 38, 68]


def test_departed_and_passed_trips_are_hidden(sample_passes):
    departures = build_departures(sample_passes, now=NOW_NL)
    # The 16:45 trip has TripStopStatus PASSED and lies in the past.
    assert all(d["expected"] > NOW_NL.isoformat() for d in departures)
    assert len(departures) == 4  # 3x line 385 + 1x line 31


def test_no_line_filter_includes_other_lines(sample_passes):
    departures = build_departures(sample_passes, now=NOW_NL)
    assert {d["line"] for d in departures} == {"385", "31"}


def test_limit_is_applied(sample_passes):
    departures = build_departures(sample_passes, now=NOW_NL, limit=1)
    assert len(departures) == 1
    assert departures[0]["expected"] == "2026-07-12T16:59:30+02:00"


def test_missing_expected_time_falls_back_to_target(sample_passes):
    departures = build_departures(sample_passes, now=NOW_NL, line_filter=("385",))
    last = departures[-1]
    assert last["expected"] == last["planned"] == "2026-07-12T17:58:00+02:00"
    assert last["delay_minutes"] == 0


def test_empty_passes_is_valid_not_an_error():
    payload = {"54460131": {"Stop": {"TimingPointName": "Katwijk, Gemeentehuis"}, "Passes": {}}}
    stop_name, passes = parse_tpc_response(payload)
    assert stop_name == "Katwijk, Gemeentehuis"
    assert build_departures(passes, now=NOW_NL) == []


def test_minutes_until_correct_when_now_is_utc(sample_passes):
    """Container clocks in UTC must yield the same results as NL time."""
    now_utc = NOW_NL.astimezone(timezone.utc)
    assert now_utc.hour == 14  # sanity: the wall clock really differs

    nl = build_departures(sample_passes, now=NOW_NL, line_filter=("385",))
    utc = build_departures(sample_passes, now=now_utc, line_filter=("385",))
    assert nl == utc
    assert utc[0]["minutes_until"] == 9


def test_unrecognized_payload_raises():
    with pytest.raises(ValueError):
        parse_tpc_response({"foo": "bar"})


def test_live_fixture_parses():
    """Schema-level check against a real capture, if one has been recorded."""
    live = FIXTURES / "tpc_live.json"
    if not live.exists():
        pytest.skip("no live capture recorded (run scripts/find_tpc.py --save-fixture)")
    stop_name, passes = parse_tpc_response(json.loads(live.read_text()))
    assert stop_name
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    for record in build_departures(passes, now=now):
        assert set(record) == {
            "line",
            "destination",
            "transport_type",
            "planned",
            "expected",
            "delay_minutes",
            "minutes_until",
        }
        assert record["minutes_until"] >= 0


def test_fall_back_ambiguous_time_uses_last_update_offset():
    payload = {
        "54460131": {
            "Stop": {"TimingPointName": "Katwijk, Gemeentehuis"},
            "Passes": {
                "trip": {
                    "LastUpdateTimeStamp": "2026-10-25T02:10:00+01:00",
                    "TargetDepartureTime": "2026-10-25T02:50:00",
                    "ExpectedDepartureTime": "2026-10-25T02:50:00",
                    "TripStopStatus": "DRIVING",
                    "LinePublicNumber": "385",
                    "DestinationName50": "Den Haag CS",
                    "TransportType": "BUS",
                }
            },
        }
    }
    _, passes = parse_tpc_response(payload)
    now = datetime(2026, 10, 25, 2, 10, tzinfo=OVAPI_TZ, fold=1)
    departures = build_departures(passes, now=now)

    assert passes[0].expected.fold == 1
    assert departures[0]["expected"] == "2026-10-25T02:50:00+01:00"
    assert departures[0]["minutes_until"] == 40


def test_fall_back_drops_departure_from_first_fold():
    departed = Pass(
        line="385",
        destination="Den Haag CS",
        transport_type="BUS",
        planned=datetime(2026, 10, 25, 2, 50, tzinfo=OVAPI_TZ, fold=0),
        expected=datetime(2026, 10, 25, 2, 50, tzinfo=OVAPI_TZ, fold=0),
        status="DRIVING",
    )
    now = datetime(2026, 10, 25, 2, 10, tzinfo=OVAPI_TZ, fold=1)

    assert build_departures([departed], now=now) == []


def test_cache_age_uses_elapsed_time_across_fall_back():
    updated = datetime(2026, 10, 25, 2, 50, tzinfo=OVAPI_TZ, fold=0)
    now = datetime(2026, 10, 25, 2, 10, tzinfo=OVAPI_TZ, fold=1)
    cache = DepartureCache(updated=updated)

    assert cache.age_seconds(now=now) == 20 * 60


def test_fall_back_ambiguous_time_uses_poll_reference_without_last_update():
    payload = {
        "54460131": {
            "Stop": {"TimingPointName": "Katwijk, Gemeentehuis"},
            "Passes": {
                "trip": {
                    "TargetDepartureTime": "2026-10-25T02:50:00",
                    "ExpectedDepartureTime": "2026-10-25T02:50:00",
                    "TripStopStatus": "DRIVING",
                    "LinePublicNumber": "385",
                    "DestinationName50": "Den Haag CS",
                    "TransportType": "BUS",
                }
            },
        }
    }
    poll_time = datetime(2026, 10, 25, 2, 10, tzinfo=OVAPI_TZ, fold=1)
    _, passes = parse_tpc_response(payload, reference=poll_time)
    departures = build_departures(passes, now=poll_time)

    assert passes[0].expected.fold == 1
    assert departures[0]["expected"] == "2026-10-25T02:50:00+01:00"
    assert departures[0]["minutes_until"] == 40
