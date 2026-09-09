"""What every Food Calc entity shares."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import FoodCalcCoordinator


class FoodCalcEntity(CoordinatorEntity[FoodCalcCoordinator]):
    """A Food Calc entity, hung off the household it reads."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: FoodCalcCoordinator) -> None:
        super().__init__(coordinator)
        household_id = coordinator.client.household_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(household_id))},
            name="Food Calc",
            manufacturer="Food Calc",
            model=f"Household {household_id}",
            configuration_url=f"{coordinator.client.base_url}/h/{household_id}/plan",
        )
