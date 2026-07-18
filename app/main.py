"""FastAPI app: serves the cached OVapi departures to Home Assistant."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, Query, Request, Response

from .config import load_settings
from .ovapi import OVAPI_TZ, build_departures
from .poller import REQUEST_TIMEOUT_SECONDS, DepartureCache, poll_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    cache = DepartureCache()
    app.state.settings = settings
    app.state.cache = cache

    client = httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    task = asyncio.create_task(poll_loop(client, settings, cache))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await client.aclose()


app = FastAPI(
    title="ovapi-departures-proxy",
    description="Caching proxy for OVapi real-time departures (unofficial).",
    lifespan=lifespan,
)


@app.get("/departures")
async def departures(
    request: Request,
    line: str | None = Query(default=None, description="Override LINE_FILTER, comma-separated"),
    limit: int | None = Query(default=None, ge=1, le=50, description="Override LIMIT"),
) -> dict:
    settings = request.app.state.settings
    cache: DepartureCache = request.app.state.cache

    if line is not None:
        line_filter = tuple(part.strip() for part in line.split(",") if part.strip())
    else:
        line_filter = settings.line_filter
    effective_limit = limit if limit is not None else settings.limit

    now = datetime.now(OVAPI_TZ)
    return {
        "stop_name": cache.stop_name,
        "updated": cache.updated.isoformat() if cache.updated else None,
        "age_seconds": cache.age_seconds(),
        "stale": cache.stale,
        "departures": build_departures(
            cache.passes, now=now, line_filter=line_filter, limit=effective_limit
        ),
    }


@app.get("/health")
async def health(request: Request) -> dict:
    cache: DepartureCache = request.app.state.cache
    # Always 200 while the web server runs: an OVapi outage should surface as
    # "degraded"/stale data, not as a container restart loop.
    return {
        "status": "ok" if not cache.stale else "degraded",
        "last_update": cache.updated.isoformat() if cache.updated else None,
        "age_seconds": cache.age_seconds(),
        "consecutive_failures": cache.consecutive_failures,
        "last_error": cache.last_error,
    }


@app.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    """Report whether at least one OVapi response has been cached successfully."""
    cache: DepartureCache = request.app.state.cache
    if not cache.has_data:
        response.status_code = 503
    return {
        "status": "ready" if cache.has_data else "not_ready",
        "last_update": cache.updated.isoformat() if cache.updated else None,
        "age_seconds": cache.age_seconds(),
        "stale": cache.stale,
        "last_error": cache.last_error,
    }
