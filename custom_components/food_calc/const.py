"""Constants shared across the Food Calc integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "food_calc"

CONF_BASE_URL = "base_url"
CONF_HOUSEHOLD_ID = "household_id"
CONF_TOKEN = "token"

# The plan changes when somebody edits it, which is rarely and never urgently.
# Fifteen minutes keeps "what's for dinner" honest without making a household's
# Home Assistant the heaviest client its own app has.
DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)

# How long a meal occupies the calendar when its slot has a time. The API gives
# a start and no end, and an hour is the least surprising thing to show for a
# meal; a slot with no time becomes an all-day event instead.
DEFAULT_MEAL_DURATION = timedelta(hours=1)

ATTRIBUTION = "Data provided by Food Calc"
