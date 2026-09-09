"""Fetches plan weeks and keeps the entities fed from one cache.

Every entity in this integration reads the same plan, so they share one
coordinator rather than each fetching for itself. The cache is keyed by the
week's Monday, which is also how the API is keyed, so a calendar asking for a
range and a sensor asking for tomorrow hit the same entries.
"""

from __future__ import annotations

import logging
from datetime import date, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FoodCalcAuthError, FoodCalcClient, FoodCalcError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .model import PlannedMeal, monday_of, parse_plan, weeks_covering

_LOGGER = logging.getLogger(__name__)


class FoodCalcCoordinator(DataUpdateCoordinator[list[PlannedMeal]]):
    """Keeps the current and next plan weeks, and fetches others on demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FoodCalcClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self._weeks: dict[date, list[PlannedMeal]] = {}

    def today(self) -> date:
        """Today in the household's timezone, not the server's.

        Home Assistant's configured timezone is the household's own, and a plan
        day is a calendar day to the people eating it. Using UTC here would
        show tomorrow's dinner after midnight UTC to anyone west of Greenwich,
        and hold yesterday's back for anyone east.
        """
        return dt_util.now().date()

    async def _async_update_data(self) -> list[PlannedMeal]:
        """Refresh the weeks the sensors need, plus any the calendar has asked for.

        The current week alone is not enough: whenever today is Sunday,
        "tomorrow" is the Monday of the *next* week and lives in a different
        payload entirely. Weeks fetched earlier for the calendar are refreshed
        rather than dropped, so scrolling back through a month does not
        re-fetch it on every tick.
        """
        today = self.today()
        wanted = {monday_of(today), monday_of(today + timedelta(days=1))}
        wanted.update(self._weeks)

        for monday in sorted(wanted):
            await self._async_fetch_week(monday)

        return self.meals()

    async def _async_fetch_week(self, monday: date) -> list[PlannedMeal]:
        """Fetch one week and put it in the cache."""
        try:
            payload = await self.client.async_get_week(monday)
        except FoodCalcAuthError as err:
            # Reauth rather than retry: the token will not start working on its
            # own, and the household has to mint a new one to fix it.
            raise ConfigEntryAuthFailed(str(err)) from err
        except FoodCalcError as err:
            raise UpdateFailed(str(err)) from err

        meals = parse_plan(payload, self.client.base_url)
        self._weeks[monday] = meals
        return meals

    def meals(self) -> list[PlannedMeal]:
        """Every cached meal, in day then time order."""
        return sorted(
            (meal for week in self._weeks.values() for meal in week),
            key=lambda m: (m.day, m.meal_time is None, m.meal_time or time.min, m.slot_name),
        )

    async def async_meals_between(self, start: date, end: date) -> list[PlannedMeal]:
        """Every meal in the inclusive range, fetching weeks the cache lacks.

        A calendar can be scrolled anywhere, so a range the cache does not
        cover is fetched rather than answered with a misleading nothing.
        """
        for monday in weeks_covering(start, end):
            if monday not in self._weeks:
                await self._async_fetch_week(monday)
        return [meal for meal in self.meals() if start <= meal.day <= end]


# Defined after the class so the subscript resolves; `type` statements would be
# tidier but need Python 3.12, and this file is also imported by the tests.
FoodCalcConfigEntry = ConfigEntry[FoodCalcCoordinator]
