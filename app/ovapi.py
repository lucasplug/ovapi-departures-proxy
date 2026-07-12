"""Parsing of OVapi /tpc/<TPC> responses into departure records.

All functions here are pure (no I/O) so they can be unit-tested against a
recorded fixture. OVapi returns local Dutch wall-clock times *without* a UTC
offset; they are parsed explicitly as Europe/Amsterdam so the service also
works when the container clock runs in UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

OVAPI_TZ = ZoneInfo("Europe/Amsterdam")

# Passes in these states are gone or not coming; never show them.
_SKIPPED_STATUSES = frozenset({"PASSED", "CANCEL", "CANCELLED"})


@dataclass(frozen=True)
class Pass:
    """One upcoming vehicle pass at the stop, as reported by OVapi."""

    line: str
    destination: str
    transport_type: str
    planned: datetime
    expected: datetime
    status: str


def parse_ovapi_time(value: str) -> datetime:
    """Parse an OVapi timestamp.

    OVapi sends naive local times like ``2026-07-12T16:58:00``; those are
    interpreted as Europe/Amsterdam. Timestamps that do carry an offset
    (e.g. LastUpdateTimeStamp) are kept as-is.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=OVAPI_TZ)
    return dt


def parse_tpc_response(payload: dict[str, Any]) -> tuple[str | None, list[Pass]]:
    """Extract the stop name and all passes from a /tpc/<TPC> response.

    The top-level key is the (dynamic) TimingPointCode, so the stop entry is
    located by shape rather than by key.
    """
    stop_entry: dict[str, Any] | None = None
    for value in payload.values():
        if isinstance(value, dict) and ("Passes" in value or "Stop" in value):
            stop_entry = value
            break
    if stop_entry is None:
        raise ValueError("Unrecognized OVapi response: no TPC entry with Stop/Passes")

    stop = stop_entry.get("Stop") or {}
    stop_name = stop.get("TimingPointName")

    passes: list[Pass] = []
    for journey in (stop_entry.get("Passes") or {}).values():
        if not isinstance(journey, dict):
            continue
        planned_raw = journey.get("TargetDepartureTime")
        expected_raw = journey.get("ExpectedDepartureTime") or planned_raw
        if not expected_raw:
            continue
        passes.append(
            Pass(
                line=str(journey.get("LinePublicNumber", "")),
                destination=str(journey.get("DestinationName50", "")),
                transport_type=str(journey.get("TransportType", "")),
                planned=parse_ovapi_time(planned_raw or expected_raw),
                expected=parse_ovapi_time(expected_raw),
                status=str(journey.get("TripStopStatus", "")).upper(),
            )
        )
    return stop_name, passes


def build_departures(
    passes: list[Pass],
    now: datetime,
    line_filter: tuple[str, ...] = (),
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Filter, sort and shape passes into the /departures JSON records.

    Departures whose expected time is in the past (already left) are dropped,
    as are cancelled/passed trips. ``minutes_until`` is computed against
    ``now`` at request time, so it stays fresh between OVapi polls.
    """
    departures: list[dict[str, Any]] = []
    for p in sorted(passes, key=lambda p: p.expected):
        if p.status in _SKIPPED_STATUSES:
            continue
        if p.expected < now:
            continue
        if line_filter and p.line not in line_filter:
            continue
        delay_minutes = round((p.expected - p.planned).total_seconds() / 60)
        minutes_until = int((p.expected - now).total_seconds() // 60)
        departures.append(
            {
                "line": p.line,
                "destination": p.destination,
                "transport_type": p.transport_type,
                "planned": p.planned.isoformat(),
                "expected": p.expected.isoformat(),
                "delay_minutes": delay_minutes,
                "minutes_until": minutes_until,
            }
        )
        if limit and len(departures) >= limit:
            break
    return departures
