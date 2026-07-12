"""Configuration loaded exclusively from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 180
MIN_POLL_INTERVAL_SECONDS = 60
DEFAULT_USER_AGENT = (
    "ovapi-departures-proxy/1.0 (+https://github.com/lucasplug/ovapi-departures-proxy)"
)
DEFAULT_PORT = 8000
DEFAULT_BASE_URL = "https://v0.ovapi.nl"


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

    line_filter = tuple(
        part.strip()
        for part in os.environ.get("LINE_FILTER", "").split(",")
        if part.strip()
    )

    limit = _int_env("LIMIT", 0)
    if limit < 0:
        limit = 0

    return Settings(
        tpc=tpc,
        poll_interval_seconds=poll_interval,
        user_agent=os.environ.get("USER_AGENT", "").strip() or DEFAULT_USER_AGENT,
        port=_int_env("PORT", DEFAULT_PORT),
        line_filter=line_filter,
        limit=limit,
        base_url=os.environ.get("OVAPI_BASE_URL", "").strip() or DEFAULT_BASE_URL,
    )
