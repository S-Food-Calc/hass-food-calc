"""End-to-end: set the integration up in Home Assistant and read the entities."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.food_calc.api import FoodCalcAuthError, FoodCalcError
from custom_components.food_calc.const import (
    CONF_BASE_URL,
    CONF_HOUSEHOLD_ID,
    CONF_TOKEN,
    DOMAIN,
)

from .conftest import BASE_URL, HOUSEHOLD_ID, MONDAY, TOKEN, plan_payload

ENTRY_DATA = {
    CONF_BASE_URL: BASE_URL,
    CONF_HOUSEHOLD_ID: HOUSEHOLD_ID,
    CONF_TOKEN: TOKEN,
}

# Midday Wednesday, so "today" is unambiguous and the 18:30 dinner is still ahead.
NOW = "2026-09-09 12:00:00"


@pytest.fixture(autouse=True)
async def utc_timezone(hass: HomeAssistant):
    """Pin the timezone so plan days and local days line up in assertions."""
    await hass.config.async_set_time_zone("UTC")


async def _setup(hass: HomeAssistant, weeks: dict | None = None, side_effect=None):
    """Set up the integration with a canned set of weeks."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=f"{BASE_URL}:{HOUSEHOLD_ID}")
    entry.add_to_hass(hass)

    weeks = weeks if weeks is not None else {MONDAY: plan_payload(MONDAY)}

    async def _get_week(monday: date):
        if side_effect:
            raise side_effect
        return weeks.get(monday, {"days": []})

    with patch(
        "custom_components.food_calc.api.FoodCalcClient.async_get_week",
        new=AsyncMock(side_effect=_get_week),
    ) as mocked:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, mocked


class TestSetup:
    async def test_entry_loads(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        entry, _ = await _setup(hass)
        assert entry.state is ConfigEntryState.LOADED

    async def test_a_rejected_token_asks_for_reauth(self, hass: HomeAssistant, freezer) -> None:
        """A revoked token must send the household to reauth, not just log."""
        freezer.move_to(NOW)
        entry, _ = await _setup(hass, side_effect=FoodCalcAuthError("revoked"))
        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert any(
            flow["context"]["source"] == "reauth"
            for flow in hass.config_entries.flow.async_progress()
        )

    async def test_a_server_error_retries_rather_than_reauthing(
        self, hass: HomeAssistant, freezer
    ) -> None:
        """A 500 is not the token's fault; asking for a new one would be wrong."""
        freezer.move_to(NOW)
        entry, _ = await _setup(hass, side_effect=FoodCalcError("boom"))
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert not hass.config_entries.flow.async_progress()

    async def test_unload(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        entry, _ = await _setup(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED


class TestSensors:
    async def test_state_is_the_meal_not_the_slot(self, hass: HomeAssistant, freezer) -> None:
        """The payload's `title` is the slot; getting this wrong shows "Dinner"."""
        freezer.move_to(NOW)
        await _setup(hass)
        state = hass.states.get("sensor.food_calc_dinner_today")
        assert state is not None
        assert state.state == "Chilli con carne"

    async def test_one_sensor_per_slot_per_day(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        ids = {e for e in hass.states.async_entity_ids("sensor") if "food_calc" in e}
        assert ids == {
            "sensor.food_calc_breakfast_today",
            "sensor.food_calc_breakfast_tomorrow",
            "sensor.food_calc_dinner_today",
            "sensor.food_calc_dinner_tomorrow",
        }

    async def test_tomorrow_reads_tomorrow(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        assert hass.states.get("sensor.food_calc_dinner_tomorrow").state == "Fish pie"

    async def test_nothing_planned_is_unknown_not_a_magic_string(
        self, hass: HomeAssistant, freezer
    ) -> None:
        """Breakfast is planned for Wednesday only, so tomorrow's has no meal."""
        freezer.move_to(NOW)
        await _setup(hass)
        state = hass.states.get("sensor.food_calc_breakfast_tomorrow")
        assert state.state == "unknown"
        assert state.attributes["planned"] is False
        assert state.attributes["date"] == "2026-09-10"

    async def test_attributes_carry_courses_recipes_and_diners(
        self, hass: HomeAssistant, freezer
    ) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        attrs = hass.states.get("sensor.food_calc_dinner_today").attributes
        assert attrs["planned"] is True
        assert attrs["slot"] == "Dinner"
        assert attrs["meal_time"] == "18:30:00"
        assert attrs["locked"] is True
        assert attrs["attendees"] == ["Alice"]
        assert attrs["recipe_urls"] == [f"{BASE_URL}/recipe/alice/chilli"]
        assert attrs["courses"][0]["name"] == "Main"

    async def test_recipe_links_are_absolute(self, hass: HomeAssistant, freezer) -> None:
        """The payload gives them relative; a relative link is useless in HA."""
        freezer.move_to(NOW)
        await _setup(hass)
        for url in hass.states.get("sensor.food_calc_dinner_today").attributes["recipe_urls"]:
            assert url.startswith("https://")


class TestWeekFetching:
    async def test_midweek_needs_only_one_week(self, hass: HomeAssistant, freezer) -> None:
        """On a Wednesday tomorrow is the same week, so there is nothing else to ask for."""
        freezer.move_to(NOW)
        _, mocked = await _setup(hass)
        assert {call.args[0] for call in mocked.await_args_list} == {MONDAY}

    async def test_sunday_needs_two_weeks(self, hass: HomeAssistant, freezer) -> None:
        """Sunday's tomorrow is the next Monday, which is a different payload."""
        freezer.move_to("2026-09-13 12:00:00")
        _, mocked = await _setup(hass, weeks={})
        assert {call.args[0] for call in mocked.await_args_list} == {
            MONDAY,
            MONDAY + timedelta(days=7),
        }

    async def test_on_sunday_tomorrow_comes_from_the_next_payload(
        self, hass: HomeAssistant, freezer
    ) -> None:
        """The boundary case: Sunday's tomorrow is a different week entirely."""
        freezer.move_to("2026-09-13 12:00:00")  # the Sunday ending MONDAY's week
        next_monday = MONDAY + timedelta(days=7)
        weeks = {
            MONDAY: {"days": []},
            next_monday: {
                "days": [
                    {
                        "id": 9,
                        "date": next_monday.isoformat(),
                        "meals": [
                            {
                                "id": 201,
                                "slotId": 5,
                                "title": "Dinner",
                                "food": [{"name": "Monday roast"}],
                                "time": "18:30:00",
                                "courses": [],
                            }
                        ],
                    }
                ]
            },
        }
        await _setup(hass, weeks=weeks)
        assert hass.states.get("sensor.food_calc_dinner_tomorrow").state == "Monday roast"


class TestCalendar:
    async def test_calendar_entity_exists_and_shows_the_next_meal(
        self, hass: HomeAssistant, freezer
    ) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        state = hass.states.get("calendar.food_calc_meal_plan")
        assert state is not None
        assert state.attributes["message"] == "Dinner: Chilli con carne"

    async def test_events_are_returned_for_a_range(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        result = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": "calendar.food_calc_meal_plan",
                "start_date_time": datetime(2026, 9, 9, 0, 0, tzinfo=dt_util.UTC),
                "end_date_time": datetime(2026, 9, 11, 0, 0, tzinfo=dt_util.UTC),
            },
            blocking=True,
            return_response=True,
        )
        events = result["calendar.food_calc_meal_plan"]["events"]
        summaries = [e["summary"] for e in events]
        assert "Dinner: Chilli con carne" in summaries
        assert "Breakfast: Porridge" in summaries
        assert "Dinner: Fish pie" in summaries

    async def test_a_timed_meal_is_not_all_day(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        result = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": "calendar.food_calc_meal_plan",
                "start_date_time": datetime(2026, 9, 9, 0, 0, tzinfo=dt_util.UTC),
                "end_date_time": datetime(2026, 9, 10, 0, 0, tzinfo=dt_util.UTC),
            },
            blocking=True,
            return_response=True,
        )
        dinner = next(
            e
            for e in result["calendar.food_calc_meal_plan"]["events"]
            if e["summary"] == "Dinner: Chilli con carne"
        )
        # An all-day event would come back as a bare date; this one has a time.
        assert "T18:30:00" in dinner["start"]

    async def test_description_carries_the_recipe_link(self, hass: HomeAssistant, freezer) -> None:
        freezer.move_to(NOW)
        await _setup(hass)
        result = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": "calendar.food_calc_meal_plan",
                "start_date_time": datetime(2026, 9, 9, 0, 0, tzinfo=dt_util.UTC),
                "end_date_time": datetime(2026, 9, 10, 0, 0, tzinfo=dt_util.UTC),
            },
            blocking=True,
            return_response=True,
        )
        dinner = next(
            e
            for e in result["calendar.food_calc_meal_plan"]["events"]
            if e["summary"] == "Dinner: Chilli con carne"
        )
        assert f"{BASE_URL}/recipe/alice/chilli" in dinner["description"]
