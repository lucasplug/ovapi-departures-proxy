"""Poller tests: backoff schedule and logging during an OVapi outage."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings
from app.poller import MAX_BACKOFF_SECONDS, DepartureCache, next_delay, poll_once


def _settings(interval: int = 180) -> Settings:
    return Settings(
        tpc="54460130",
        poll_interval_seconds=interval,
        user_agent="test/1.0",
        port=8000,
        line_filter=(),
        limit=0,
        base_url="http://ovapi.test",
    )


def test_next_delay_backs_off_and_caps():
    settings = _settings(180)
    delays = [next_delay(settings, failures) for failures in range(6)]
    assert delays == [180, 180, 360, 720, MAX_BACKOFF_SECONDS, MAX_BACKOFF_SECONDS]


def test_next_delay_never_below_configured_interval():
    # An interval above the backoff cap is kept as-is.
    assert next_delay(_settings(3600), 3) == 3600


def test_only_first_failure_logs_traceback(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> DepartureCache:
        cache = DepartureCache()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for _ in range(3):
                await poll_once(client, _settings(), cache)
        return cache

    with caplog.at_level(logging.WARNING, logger="app.poller"):
        cache = asyncio.run(run())

    assert cache.consecutive_failures == 3
    with_traceback = [r for r in caplog.records if r.exc_info]
    assert len(with_traceback) == 1
    assert len(caplog.records) == 3
