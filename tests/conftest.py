"""Test fixtures.

`pytest-homeassistant-custom-component` supplies the Home Assistant harness the
end-to-end tests run inside; the model and API tests need none of it, and
neither module imports Home Assistant.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

BASE_URL = "https://food-calc.example"
HOUSEHOLD_ID = 12
TOKEN = "aB3-_9xQzR7pW2mN0kLtYh4s"

# A Wednesday, so "today" and "tomorrow" sit inside one week and the tests are
# not silently exercising the Sunday boundary unless they mean to.
WEDNESDAY = date(2026, 9, 9)
MONDAY = date(2026, 9, 7)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load `custom_components/food_calc` at all."""
    return


def plan_payload(monday: date = MONDAY) -> dict:
    """One week shaped as the plan API returns it, starting at `monday`."""
    from datetime import timedelta

    wednesday = (monday + timedelta(days=2)).isoformat()
    thursday = (monday + timedelta(days=3)).isoformat()
    return {
        "days": [
            {
                "id": 1,
                "date": wednesday,
                "meals": [
                    {
                        "id": 101,
                        "slotId": 5,
                        "mealId": 900,
                        "title": "Dinner",
                        "food": [{"name": "Chilli con carne"}],
                        "time": "18:30:00",
                        "locked": True,
                        "courses": [
                            {
                                "courseId": 1,
                                "name": "Main",
                                "sortOrder": 0,
                                "components": [
                                    {
                                        "componentId": 11,
                                        "name": "Chilli",
                                        "recipe": {
                                            "id": 7,
                                            "slug": "chilli",
                                            "title": "Chilli con carne",
                                            "url": "/recipe/alice/chilli",
                                        },
                                    }
                                ],
                            }
                        ],
                        "attendees": [{"id": 1, "name": "Alice"}],
                    },
                    {
                        "id": 102,
                        "slotId": 4,
                        "title": "Breakfast",
                        "food": [{"name": "Porridge"}],
                        "time": "08:00:00",
                        "courses": [],
                    },
                ],
            },
            {
                "id": 2,
                "date": thursday,
                "meals": [
                    {
                        "id": 103,
                        "slotId": 5,
                        "title": "Dinner",
                        "food": [{"name": "Fish pie"}],
                        "time": "18:30:00",
                        "courses": [],
                    }
                ],
            },
        ]
    }
