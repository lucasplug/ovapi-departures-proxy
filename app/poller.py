"""Background poller that fetches OVapi periodically and keeps an in-memory cache.

Fair use: OVapi is a semi-private, non-commercial project. The poll interval
is clamped to at least 60 seconds (see config) and every request carries an
identifying User-Agent. On errors the last good data is kept and served with
``stale: true`` instead of failing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .config import Settings
from .ovapi import OVAPI_TZ, Pass, parse_tpc_response

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15


@dataclass
class DepartureCache:
    """Last successfully fetched & parsed OVapi data."""

    stop_name: str | None = None
    passes: list[Pass] = field(default_factory=list)
    updated: datetime | None = None
    consecutive_failures: int = 0
    has_data: bool = False
    last_error: str | None = None

    @property
    def stale(self) -> bool:
        return self.consecutive_failures > 0 or not self.has_data

    def age_seconds(self, now: datetime | None = None) -> int | None:
        """Seconds since the last successful OVapi fetch, or None if never."""
        if self.updated is None:
            return None
        now = now or datetime.now(timezone.utc)
        elapsed = now.astimezone(timezone.utc) - self.updated.astimezone(timezone.utc)
        return max(0, int(elapsed.total_seconds()))


async def poll_once(client: httpx.AsyncClient, settings: Settings, cache: DepartureCache) -> None:
    """Fetch the TPC endpoint once and update the cache (never raises)."""
    url = f"{settings.base_url}/tpc/{settings.tpc}"
    try:
        response = await client.get(url)
        response.raise_for_status()
        fetched_at = datetime.now(OVAPI_TZ)
        stop_name, passes = parse_tpc_response(response.json(), reference=fetched_at)
    except Exception as exc:
        cache.consecutive_failures += 1
        cache.last_error = f"{type(exc).__name__}: {exc}"
        logger.exception(
            "OVapi poll failed (attempt %d); serving cached data as stale",
            cache.consecutive_failures,
        )
        return

    cache.stop_name = stop_name or cache.stop_name
    cache.passes = passes
    cache.updated = fetched_at
    cache.consecutive_failures = 0
    cache.has_data = True
    cache.last_error = None
    logger.info("OVapi poll ok: %d passes at %s", len(passes), stop_name)


async def poll_loop(client: httpx.AsyncClient, settings: Settings, cache: DepartureCache) -> None:
    logger.info(
        "Starting OVapi poller: tpc=%s interval=%ds line_filter=%s",
        settings.tpc,
        settings.poll_interval_seconds,
        ",".join(settings.line_filter) or "<none>",
    )
    while True:
        await poll_once(client, settings, cache)
        await asyncio.sleep(settings.poll_interval_seconds)
