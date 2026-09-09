"""The Food Calc integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FoodCalcClient
from .const import CONF_BASE_URL, CONF_HOUSEHOLD_ID, CONF_TOKEN
from .coordinator import FoodCalcConfigEntry, FoodCalcCoordinator

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: FoodCalcConfigEntry) -> bool:
    """Set up Food Calc from a config entry."""
    client = FoodCalcClient(
        session=async_get_clientsession(hass),
        base_url=entry.data[CONF_BASE_URL],
        household_id=entry.data[CONF_HOUSEHOLD_ID],
        token=entry.data[CONF_TOKEN],
    )
    coordinator = FoodCalcCoordinator(hass, entry, client)

    # Before the platforms, so a household with a dead token is told so at
    # startup rather than through a row of entities that never populate.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FoodCalcConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
