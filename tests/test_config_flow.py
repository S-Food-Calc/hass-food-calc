"""The setup and re-authentication flows, inside a real Home Assistant."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.food_calc.api import FoodCalcAuthError, FoodCalcConnectionError
from custom_components.food_calc.const import (
    CONF_BASE_URL,
    CONF_HOUSEHOLD_ID,
    CONF_TOKEN,
    DOMAIN,
)

from .conftest import BASE_URL, HOUSEHOLD_ID, TOKEN, plan_payload

USER_INPUT = {
    CONF_BASE_URL: BASE_URL,
    CONF_HOUSEHOLD_ID: HOUSEHOLD_ID,
    CONF_TOKEN: TOKEN,
}


def _patch_week(**kwargs):
    return patch(
        "custom_components.food_calc.api.FoodCalcClient.async_get_week",
        new=AsyncMock(**kwargs),
    )


async def test_creates_an_entry(hass: HomeAssistant) -> None:
    with (
        _patch_week(return_value=plan_payload()),
        patch("custom_components.food_calc.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["title"] == f"Food Calc household {HOUSEHOLD_ID}"


async def test_trailing_slash_is_normalised_away(hass: HomeAssistant) -> None:
    """Otherwise every URL the client builds carries a double slash."""
    with (
        _patch_week(return_value=plan_payload()),
        patch("custom_components.food_calc.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_BASE_URL: f"{BASE_URL}/"}
        )
        await hass.async_block_till_done()

    assert result["data"][CONF_BASE_URL] == BASE_URL


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FoodCalcAuthError("nope"), {"base": "invalid_auth"}),
        (FoodCalcConnectionError("down"), {"base": "cannot_connect"}),
    ],
)
async def test_surfaces_errors_on_the_form(hass: HomeAssistant, error, expected) -> None:
    with _patch_week(side_effect=error):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == expected


async def test_a_bad_url_is_caught_before_any_request(hass: HomeAssistant) -> None:
    """No point asking the network about "not-a-url"."""
    with _patch_week(return_value=plan_payload()) as mocked:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_BASE_URL: "not-a-url"}
        )

    assert result["errors"] == {CONF_BASE_URL: "invalid_url"}
    mocked.assert_not_awaited()


async def test_the_same_household_cannot_be_added_twice(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=f"{BASE_URL}:{HOUSEHOLD_ID}",
    ).add_to_hass(hass)

    with _patch_week(return_value=plan_payload()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_only_the_token(hass: HomeAssistant) -> None:
    """A revoked token is the reason for reauth; retyping the URL invites typos."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=f"{BASE_URL}:{HOUSEHOLD_ID}",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with (
        _patch_week(return_value=plan_payload()),
        patch("custom_components.food_calc.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: "new-token-aB39xQzR7pW2mN0kLt"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "new-token-aB39xQzR7pW2mN0kLt"
    assert entry.data[CONF_BASE_URL] == BASE_URL
    assert entry.data[CONF_HOUSEHOLD_ID] == HOUSEHOLD_ID
