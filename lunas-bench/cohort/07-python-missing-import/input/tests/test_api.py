"""Tests for src.api.get_time."""

import asyncio

import pytest

from src.api import get_time


def test_get_time_returns_iso_timestamp() -> None:
    body = asyncio.run(get_time())
    assert "now" in body
    assert "T" in body["now"]
