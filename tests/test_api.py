"""Tests for the HTTP client, against a fake session rather than a real server."""

from __future__ import annotations

import asyncio
from datetime import date

import aiohttp
import pytest

from custom_components.food_calc.api import (
    FoodCalcAuthError,
    FoodCalcClient,
    FoodCalcConnectionError,
    FoodCalcError,
)

BASE = "https://food-calc.example"
TOKEN = "aB3-_9xQzR7pW2mN0kLtYh4s"
MONDAY = date(2026, 9, 7)


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records the URL it was asked for and hands back a canned response."""

    def __init__(self, response=None, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.requested_url = None

    def get(self, url, **kwargs):
        self.requested_url = url
        if self._raises:
            raise self._raises
        return self._response


def _client(session) -> FoodCalcClient:
    return FoodCalcClient(session=session, base_url=BASE, household_id=12, token=TOKEN)


def test_builds_the_documented_url() -> None:
    session = FakeSession(FakeResponse(200, {"days": []}))
    asyncio.run(_client(session).async_get_week(MONDAY))
    assert str(session.requested_url) == f"{BASE}/api/plans/12/2026-09-07?token={TOKEN}"


def test_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    session = FakeSession(FakeResponse(200, {"days": []}))
    client = FoodCalcClient(session=session, base_url=f"{BASE}/", household_id=12, token=TOKEN)
    asyncio.run(client.async_get_week(MONDAY))
    assert "//api/plans" not in str(session.requested_url)


def test_a_token_needing_encoding_is_encoded_once() -> None:
    session = FakeSession(FakeResponse(200, {"days": []}))
    client = FoodCalcClient(session=session, base_url=BASE, household_id=12, token="a b&c")
    asyncio.run(client.async_get_week(MONDAY))
    url = str(session.requested_url)
    assert "token=a+b%26c" in url or "token=a%20b%26c" in url


def test_returns_the_payload() -> None:
    payload = {"days": [{"date": "2026-09-07", "meals": []}]}
    session = FakeSession(FakeResponse(200, payload))
    assert asyncio.run(_client(session).async_get_week(MONDAY)) == payload


@pytest.mark.parametrize("status", [401, 403, 404])
def test_rejection_statuses_are_auth_errors(status: int) -> None:
    """404 included: the API answers that for a bad token on purpose."""
    session = FakeSession(FakeResponse(status))
    with pytest.raises(FoodCalcAuthError):
        asyncio.run(_client(session).async_get_week(MONDAY))


@pytest.mark.parametrize("status", [400, 500, 502])
def test_other_failures_are_plain_errors_not_auth_ones(status: int) -> None:
    """A 500 must not trigger reauth — the token is fine, the server is not."""
    session = FakeSession(FakeResponse(status))
    with pytest.raises(FoodCalcError) as excinfo:
        asyncio.run(_client(session).async_get_week(MONDAY))
    assert not isinstance(excinfo.value, FoodCalcAuthError)


def test_a_dead_server_is_a_connection_error() -> None:
    session = FakeSession(raises=aiohttp.ClientError("no route to host"))
    with pytest.raises(FoodCalcConnectionError):
        asyncio.run(_client(session).async_get_week(MONDAY))


def test_a_timeout_is_a_connection_error() -> None:
    session = FakeSession(raises=TimeoutError())
    with pytest.raises(FoodCalcConnectionError):
        asyncio.run(_client(session).async_get_week(MONDAY))


def test_an_empty_plan_still_counts_as_valid_credentials() -> None:
    """A household that has not planned this week is set up correctly, not broken."""
    session = FakeSession(FakeResponse(200, {"days": []}))
    asyncio.run(_client(session).async_check_credentials(date(2026, 9, 9)))
    assert "2026-09-07" in str(session.requested_url)
