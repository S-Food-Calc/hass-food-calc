"""A sensor per meal slot, for today and for tomorrow.

Slots are not fixed: a household defines its own ("Breakfast", "Dinner",
"Friday takeaway"), so the entities are discovered from the plan rather than
hard-coded, and a slot added later turns up without reconfiguring anything.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FoodCalcConfigEntry, FoodCalcCoordinator
from .entity import FoodCalcEntity
from .model import Slot, meal_for, slots_in

# Home Assistant refuses a state longer than 255 characters outright, which
# would lose the whole reading rather than the tail of a long meal name.
MAX_STATE_LENGTH = 255

# Which days get a sensor each. Tomorrow is the one that earns its keep: it is
# what an evening automation needs to say anything useful about defrosting.
DAY_OFFSETS = {0: "today", 1: "tomorrow"}


def _slot_key(slot: Slot) -> str:
    """A stable identity for a slot, preferring its id over its name.

    A renamed slot keeps its id and so keeps its entity and its history; a
    household whose slots somehow have no id falls back to the name, which is
    at least stable while nobody renames it.
    """
    return str(slot.slot_id) if slot.slot_id is not None else f"name:{slot.name}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FoodCalcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a sensor per slot per day."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_slots() -> None:
        """Add entities for slots not seen before.

        Runs on every refresh rather than only at setup: a household that adds
        a slot mid-week should get its sensors then, not at the next restart.
        """
        new: list[SensorEntity] = []
        for slot in slots_in(coordinator.meals()):
            key = _slot_key(slot)
            if key in known:
                continue
            known.add(key)
            new.extend(
                FoodCalcMealSensor(coordinator, entry, slot, offset) for offset in DAY_OFFSETS
            )
        if new:
            async_add_entities(new)

    _add_new_slots()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_slots))


class FoodCalcMealSensor(FoodCalcEntity, SensorEntity):
    """What is planned in one slot on one day."""

    def __init__(
        self,
        coordinator: FoodCalcCoordinator,
        entry: FoodCalcConfigEntry,
        slot: Slot,
        offset: int,
    ) -> None:
        super().__init__(coordinator)
        self._slot = slot
        self._offset = offset
        when = DAY_OFFSETS[offset]
        self._attr_name = f"{slot.name} {when}"
        self._attr_unique_id = f"{entry.entry_id}_{_slot_key(slot)}_{when}"

    @property
    def _meal(self):
        """The meal this sensor is about, or ``None`` if nothing is planned."""
        day = self.coordinator.today() + timedelta(days=self._offset)
        return meal_for(self.coordinator.meals(), day, self._slot)

    @property
    def native_value(self) -> str | None:
        """The meal's name.

        ``None`` — so the state reads "unknown" — when nothing is planned,
        which is a normal state for a household that has not planned that far
        ahead, and one a template can test for without matching on a magic
        string.
        """
        meal = self._meal
        if meal is None or not meal.name:
            return None
        return meal.name[:MAX_STATE_LENGTH]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The courses, recipes and diners behind the state.

        The day is always reported, even with nothing planned, so an automation
        can tell "no dinner on Thursday" from "this sensor is broken".
        """
        day = self.coordinator.today() + timedelta(days=self._offset)
        meal = self._meal
        if meal is None:
            return {"date": day.isoformat(), "slot": self._slot.name, "planned": False}
        return {"planned": True, **meal.as_attributes()}
