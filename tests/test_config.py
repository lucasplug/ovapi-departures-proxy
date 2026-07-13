"""Tests for environment-variable validation in app.config."""

from __future__ import annotations

import pytest

from app.config import (
    MAX_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
    load_settings,
)


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("OVAPI_TPC", "54460130")
    for name in ("POLL_INTERVAL_SECONDS", "PORT", "OVAPI_BASE_URL", "LIMIT"):
        monkeypatch.delenv(name, raising=False)


def test_missing_tpc_raises(monkeypatch):
    monkeypatch.delenv("OVAPI_TPC", raising=False)
    with pytest.raises(RuntimeError, match="OVAPI_TPC"):
        load_settings()


def test_poll_interval_clamped_to_fair_use_minimum(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "5")
    assert load_settings().poll_interval_seconds == MIN_POLL_INTERVAL_SECONDS


def test_poll_interval_clamped_to_maximum(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "999999")
    assert load_settings().poll_interval_seconds == MAX_POLL_INTERVAL_SECONDS


def test_invalid_port_raises(monkeypatch):
    monkeypatch.setenv("PORT", "70000")
    with pytest.raises(RuntimeError, match="PORT"):
        load_settings()


def test_base_url_trailing_slash_is_stripped(monkeypatch):
    monkeypatch.setenv("OVAPI_BASE_URL", "http://v0.ovapi.nl/")
    assert load_settings().base_url == "http://v0.ovapi.nl"


def test_base_url_requires_http_scheme(monkeypatch):
    monkeypatch.setenv("OVAPI_BASE_URL", "ftp://v0.ovapi.nl")
    with pytest.raises(RuntimeError, match="OVAPI_BASE_URL"):
        load_settings()


def test_negative_limit_becomes_unlimited(monkeypatch):
    monkeypatch.setenv("LIMIT", "-3")
    assert load_settings().limit == 0
