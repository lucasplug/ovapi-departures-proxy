"""Configuration loaded exclusively from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 180
MIN_POLL_INTERVAL_SECONDS = 60
MAX_POLL_INTERVAL_SECONDS = 3600
DEFAULT_USER_AGENT = (
    "ovapi-departures-proxy/1.0 (+https://github.com/lucasplug/ovapi-departures-proxy)"
)
DEFAULT_PORT = 8000
# Plain HTTP: v0.ovapi.nl serves a TLS certificate issued for de.ovapi.nl, so
# HTTPS fails certificate validation (verified 2026-07). Override via
# OVAPI_BASE_URL if OVapi ever fixes this.
DEFAULT_BASE_URL = "http://v0.ovapi.nl"


@dataclass(frozen=True)
class Settings:
    tpc: str
    poll_interval_seconds: int
    user_agent: str
    port: int
    line_filter: tuple[str, ...]
    limit: int
    base_url: str


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, falling back to %d", name, raw, default)
        return default


def load_port() -> int:
    """Load and validate the HTTP port for both Uvicorn and app settings."""
    port = _int_env("PORT", DEFAULT_PORT)
    if not 1 <= port <= 65535:
        raise RuntimeError(f"PORT={port} is invalid; must be between 1 and 65535")
    return port


def load_settings() -> Settings:
    tpc = os.environ.get("OVAPI_TPC", "").strip()
    if not tpc:
        raise RuntimeError(
            "OVAPI_TPC is not set. Set it to the TimingPointCode of your stop, "
            "e.g. OVAPI_TPC=54460131 (see scripts/find_tpc.py to determine the right one)."
        )

    poll_interval = _int_env("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)
    if poll_interval < MIN_POLL_INTERVAL_SECONDS:
        logger.warning(
            "POLL_INTERVAL_SECONDS=%d is below the fair-use minimum; clamping to %d",
            poll_interval,
            MIN_POLL_INTERVAL_SECONDS,
        )
        poll_interval = MIN_POLL_INTERVAL_SECONDS
    elif poll_interval > MAX_POLL_INTERVAL_SECONDS:
        logger.warning(
            "POLL_INTERVAL_SECONDS=%d would make the data very stale; clamping to %d",
            poll_interval,
            MAX_POLL_INTERVAL_SECONDS,
        )
        poll_interval = MAX_POLL_INTERVAL_SECONDS

    line_filter = tuple(
        part.strip()
        for part in os.environ.get("LINE_FILTER", "").split(",")
        if part.strip()
    )

    limit = _int_env("LIMIT", 0)
    if limit < 0:
        limit = 0

    base_url = (os.environ.get("OVAPI_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError(
            f"OVAPI_BASE_URL={base_url!r} is invalid; only http:// and https:// are supported"
        )

    return Settings(
        tpc=tpc,
        poll_interval_seconds=poll_interval,
        user_agent=os.environ.get("USER_AGENT", "").strip() or DEFAULT_USER_AGENT,
        port=load_port(),
        line_filter=line_filter,
        limit=limit,
        base_url=base_url,
    )
