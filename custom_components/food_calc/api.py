"""The thin HTTP client for the Food Calc plan API.

Home Assistant imports are kept out so this can be exercised against a fake
session in tests. The coordinator translates these exceptions into the ones
Home Assistant wants.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class FoodCalcError(Exception):
    """Any failure to get a plan."""


class FoodCalcAuthError(FoodCalcError):
    """The token was rejected, or does not belong to this household."""


class FoodCalcConnectionError(FoodCalcError):
    """The server could not be reached, or did not answer in time."""


class FoodCalcClient:
    """Reads one household's plans, a week at a time."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        household_id: int,
        token: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._household_id = household_id
        self._token = token

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def household_id(self) -> int:
        return self._household_id

    def _url(self, monday: date) -> URL:
        """The plan URL for one week.

        The token goes on via yarl rather than an f-string so it is encoded
        once, correctly, and never by hand.
        """
        return URL(
            f"{self._base_url}/api/plans/{self._household_id}/{monday.isoformat()}"
        ).with_query({"token": self._token})

    async def async_get_week(self, monday: date) -> dict[str, Any]:
        """One week's plan payload.

        A 404 is the API declining to say *why* — a malformed token, a revoked
        one, and a real token for somebody else's household all answer the
        same, on purpose, so this endpoint cannot be used to probe for either.
        That makes it indistinguishable from bad credentials here, which is the
        right thing to report: it is the only cause the household can act on.
        """
        try:
            async with self._session.get(self._url(monday), timeout=REQUEST_TIMEOUT) as response:
                if response.status in (401, 403, 404):
                    raise FoodCalcAuthError(
                        f"Food Calc rejected the token for household "
                        f"{self._household_id} ({response.status})"
                    )
                if response.status >= 400:
                    raise FoodCalcError(
                        f"Food Calc returned {response.status} for week {monday.isoformat()}"
                    )
                return await response.json()
        except TimeoutError as err:
            raise FoodCalcConnectionError(
                f"Food Calc timed out fetching week {monday.isoformat()}"
            ) from err
        except aiohttp.ClientError as err:
            raise FoodCalcConnectionError(f"Could not reach Food Calc: {err}") from err

    async def async_check_credentials(self, today: date) -> None:
        """Fetch one week purely to see whether the token works.

        An empty plan is a perfectly good answer — a household that has not
        planned this week still has valid credentials — so only an error means
        anything here.
        """
        from .model import monday_of

        await self.async_get_week(monday_of(today))
