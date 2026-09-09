"""Setting up Food Calc: a base URL, a household, and a plan API token."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import FoodCalcAuthError, FoodCalcClient, FoodCalcConnectionError, FoodCalcError
from .const import CONF_BASE_URL, CONF_HOUSEHOLD_ID, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Required(CONF_HOUSEHOLD_ID): vol.Coerce(int),
        vol.Required(CONF_TOKEN): str,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})


def normalise_base_url(value: str) -> str:
    """The base URL, trimmed and without a trailing slash.

    Rejects anything that is not http(s) with a host, so a typo becomes a
    message on the form rather than a config entry that can never load.
    """
    candidate = (value or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"not a URL: {value!r}")
    return candidate


class FoodCalcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setting up and re-authenticating a household."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, str]:
        """Try the credentials, returning form errors keyed as the schema wants."""
        try:
            base_url = normalise_base_url(data[CONF_BASE_URL])
        except ValueError:
            return {CONF_BASE_URL: "invalid_url"}

        client = FoodCalcClient(
            session=async_get_clientsession(self.hass),
            base_url=base_url,
            household_id=data[CONF_HOUSEHOLD_ID],
            token=data[CONF_TOKEN].strip(),
        )
        try:
            await client.async_check_credentials(dt_util.now().date())
        except FoodCalcAuthError:
            # The API will not say whether it was the token or the household,
            # so neither will this: pointing at one of them would be a guess,
            # and a wrong guess sends somebody looking in the wrong place.
            return {"base": "invalid_auth"}
        except FoodCalcConnectionError:
            return {"base": "cannot_connect"}
        except FoodCalcError:
            _LOGGER.exception("Unexpected error validating Food Calc credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add a household."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate(user_input)
            if not errors:
                base_url = normalise_base_url(user_input[CONF_BASE_URL])
                household_id = user_input[CONF_HOUSEHOLD_ID]

                # One entry per household per server: a second one would be a
                # duplicate set of entities reading exactly the same plan.
                await self.async_set_unique_id(f"{base_url}:{household_id}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Food Calc household {household_id}",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_HOUSEHOLD_ID: household_id,
                        CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                    },
                )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after a token stopped being accepted."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Take a fresh token for an existing household.

        Only the token is asked for: a revoked token is the reason this step
        exists, and making somebody retype the URL and household id to fix it
        is a good way to have them mistype one.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            errors = await self._async_validate(candidate)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=candidate)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"household": str(entry.data[CONF_HOUSEHOLD_ID])},
        )
