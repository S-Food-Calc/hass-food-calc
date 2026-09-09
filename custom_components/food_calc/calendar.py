"""The household's plan as a calendar.

The app already publishes an ICS feed, which Home Assistant can subscribe to on
its own. This entity exists for what the ICS cannot carry: the courses, the
recipe links and the diners come straight off the JSON, and it shares the
coordinator's cache with the sensors rather than being a second subscription to
keep in step.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_MEAL_DURATION
from .coordinator import FoodCalcConfigEntry, FoodCalcCoordinator
from .entity import FoodCalcEntity
from .model import PlannedMeal, event_description, event_summary, event_timing

# How far ahead the "next event" property looks. Far enough to still say
# something during a quiet fortnight, short enough not to drag a year of plans
# into memory to answer it.
UPCOMING_WINDOW = timedelta(days=14)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoodCalcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the plan calendar."""
    async_add_entities([FoodCalcCalendar(entry.runtime_data, entry)])


class FoodCalcCalendar(FoodCalcEntity, CalendarEntity):
    """Every planned meal, as calendar events."""

    _attr_name = "Meal plan"

    def __init__(self, coordinator: FoodCalcCoordinator, entry: FoodCalcConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"

    def _to_event(self, meal: PlannedMeal) -> CalendarEvent:
        """One meal as a calendar event.

        The model works in naive local terms on purpose; the timezone is
        attached here, where Home Assistant's own is known. An all-day meal
        keeps plain dates — giving those a timezone is what makes an all-day
        event drift a day either side of the date it was planned for.
        """
        timing = event_timing(meal, DEFAULT_MEAL_DURATION)
        if timing.all_day:
            start: date | datetime = timing.start
            end: date | datetime = timing.end
        else:
            start = dt_util.as_local(timing.start)
            end = dt_util.as_local(timing.end)
        return CalendarEvent(
            summary=event_summary(meal),
            start=start,
            end=end,
            description=event_description(meal) or None,
        )

    @property
    def event(self) -> CalendarEvent | None:
        """The next meal, which is what the entity's state reports.

        Read from the cache rather than fetched: this is a property, so it
        cannot await, and the coordinator has already loaded the days either
        side of today by the time anything asks.
        """
        today = self.coordinator.today()
        horizon = today + UPCOMING_WINDOW
        upcoming = [meal for meal in self.coordinator.meals() if today <= meal.day <= horizon]
        if not upcoming:
            return None

        now = dt_util.now()
        for meal in upcoming:
            event = self._to_event(meal)
            end = event.end
            # An all-day event's end is the exclusive next midnight, so compare
            # it as a date; a timed one compares as the instant it is.
            if isinstance(end, datetime):
                if dt_util.as_local(end) > now:
                    return event
            elif end > now.date():
                return event
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Every meal in the range the calendar view is asking for.

        Home Assistant hands this aware datetimes for a window the user has
        scrolled to, which may be nowhere near the cached weeks — so the
        coordinator fetches what it is missing rather than reporting an empty
        month that only looks like an empty plan.
        """
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date()
        meals = await self.coordinator.async_meals_between(start, end)
        return [self._to_event(meal) for meal in meals]
