"""API tests: response shape of /departures and /health, without touching OVapi."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ovapi import OVAPI_TZ, Pass, parse_tpc_response

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("OVAPI_TPC", "54460131")
    monkeypatch.setenv("LINE_FILTER", "385")
    monkeypatch.setenv("LIMIT", "4")
    # Point the poller at a closed local port so no real network traffic is
    # attempted; the first poll fails fast and the cache stays empty/stale.
    monkeypatch.setenv("OVAPI_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "3600")

    from app.main import app

    with TestClient(app) as test_client:
        # Wait for the first (deliberately failing) poll so it cannot race
        # with tests that populate the cache afterwards; the next poll is
        # an hour away (POLL_INTERVAL_SECONDS=3600).
        cache = app.state.cache
        deadline = time.monotonic() + 5
        while cache.consecutive_failures == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        yield test_client


def _load_cache_from_fixture(client: TestClient) -> None:
    payload = json.loads((FIXTURES / "tpc_sample.json").read_text())
    stop_name, passes = parse_tpc_response(payload)
    cache = client.app.state.cache
    # Shift absolute instants in UTC so this remains correct during the
    # repeated local hour when daylight saving time ends.
    fixture_now_utc = datetime(
        2026, 7, 12, 16, 50, 0, tzinfo=OVAPI_TZ
    ).astimezone(timezone.utc)
    offset = datetime.now(timezone.utc) - fixture_now_utc
    cache.passes = [
        Pass(
            line=p.line,
            destination=p.destination,
            transport_type=p.transport_type,
            planned=(p.planned.astimezone(timezone.utc) + offset).astimezone(OVAPI_TZ),
            expected=(p.expected.astimezone(timezone.utc) + offset).astimezone(OVAPI_TZ),
            status=p.status,
        )
        for p in passes
    ]
    cache.stop_name = stop_name
    cache.updated = datetime.now(OVAPI_TZ)
    cache.consecutive_failures = 0
    cache.has_data = True
    cache.last_error = None


def test_departures_before_first_successful_poll(client):
    body = client.get("/departures").json()
    assert body["stale"] is True
    assert body["updated"] is None
    assert body["departures"] == []  # empty list is a valid response, not an error


def test_departures_shape_and_env_filtering(client):
    _load_cache_from_fixture(client)
    response = client.get("/departures")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"stop_name", "updated", "age_seconds", "stale", "departures"}
    assert body["age_seconds"] >= 0
    assert body["stop_name"] == "Katwijk, Gemeentehuis"
    assert body["stale"] is False
    # LINE_FILTER=385 and LIMIT=4 from the environment apply.
    assert 0 < len(body["departures"]) <= 4
    assert all(d["line"] == "385" for d in body["departures"])


def test_departures_query_params_override_env(client):
    _load_cache_from_fixture(client)
    body = client.get("/departures", params={"line": "31", "limit": 1}).json()
    assert len(body["departures"]) == 1
    assert body["departures"][0]["line"] == "31"


def test_departures_limit_is_bounded(client):
    assert client.get("/departures", params={"limit": 51}).status_code == 422
    assert client.get("/departures", params={"limit": 0}).status_code == 422


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "consecutive_failures" in body
    assert "age_seconds" in body
    assert "last_error" in body


def test_readiness_requires_first_successful_poll(client):
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"

    _load_cache_from_fixture(client)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["last_update"] is not None
