"""Tests for the pure plan-shaping logic.

`model.py` imports no Home Assistant of its own — these are the parts most
likely to be quietly wrong, and keeping them separable is what lets them be
tested this directly.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from custom_components.food_calc.model import (
    PlannedMeal,
    Slot,
    absolute_recipe_url,
    event_description,
    event_summary,
    event_timing,
    meal_for,
    monday_of,
    parse_iso_day,
    parse_meal_time,
    parse_plan,
    slots_in,
    weeks_covering,
)

BASE = "https://food-calc.example"


class TestMondayOf:
    """`monday_of` has to agree with the app's `mondayOf`, Sunday included."""

    @pytest.mark.parametrize(
        ("day", "expected"),
        [
            ("2026-09-07", "2026-09-07"),  # a Monday is its own week start
            ("2026-09-09", "2026-09-07"),  # Wednesday rounds back
            ("2026-09-12", "2026-09-07"),  # Saturday rounds back
            ("2026-09-13", "2026-09-07"),  # Sunday ENDS that week, not starts one
            ("2026-09-14", "2026-09-14"),  # the following Monday
        ],
    )
    def test_rounds_back_to_monday(self, day: str, expected: str) -> None:
        assert monday_of(date.fromisoformat(day)).isoformat() == expected

    def test_sunday_does_not_round_forward(self) -> None:
        """The case the app's own comment calls out as the awkward one."""
        sunday = date(2026, 9, 13)
        assert sunday.weekday() == 6
        assert monday_of(sunday) == date(2026, 9, 7)
        assert monday_of(sunday) < sunday

    def test_every_day_of_a_week_shares_a_monday(self) -> None:
        monday = date(2026, 9, 7)
        assert {monday_of(monday + timedelta(days=n)) for n in range(7)} == {monday}


class TestWeeksCovering:
    def test_single_day_is_one_week(self) -> None:
        day = date(2026, 9, 9)
        assert weeks_covering(day, day) == [date(2026, 9, 7)]

    def test_spans_the_sunday_monday_boundary(self) -> None:
        """Sunday to Monday is two payloads, which is the whole reason this exists."""
        assert weeks_covering(date(2026, 9, 13), date(2026, 9, 14)) == [
            date(2026, 9, 7),
            date(2026, 9, 14),
        ]

    def test_covers_every_week_in_a_long_range(self) -> None:
        weeks = weeks_covering(date(2026, 9, 9), date(2026, 10, 6))
        assert weeks == [
            date(2026, 9, 7),
            date(2026, 9, 14),
            date(2026, 9, 21),
            date(2026, 9, 28),
            date(2026, 10, 5),
        ]

    def test_backwards_range_is_empty_not_endless(self) -> None:
        assert weeks_covering(date(2026, 9, 14), date(2026, 9, 7)) == []


class TestParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-09-09", date(2026, 9, 9)),
            ("2026-09-09T00:00:00.000Z", date(2026, 9, 9)),  # a timestamp still yields the day
            ("not a date", None),
            ("2026-13-01", None),
            (None, None),
            (12345, None),
        ],
    )
    def test_parse_iso_day(self, value, expected) -> None:
        assert parse_iso_day(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("18:30:00", time(18, 30)),
            ("18:30", time(18, 30)),
            ("  08:00:00  ", time(8, 0)),
            ("", None),
            (None, None),
            ("teatime", None),
        ],
    )
    def test_parse_meal_time(self, value, expected) -> None:
        assert parse_meal_time(value) == expected

    @pytest.mark.parametrize(
        ("base", "url", "expected"),
        [
            (BASE, "/recipe/alice/chilli", f"{BASE}/recipe/alice/chilli"),
            (f"{BASE}/", "/recipe/alice/chilli", f"{BASE}/recipe/alice/chilli"),
            (BASE, "recipe/alice/chilli", f"{BASE}/recipe/alice/chilli"),
            (BASE, None, None),
            (BASE, "", None),
        ],
    )
    def test_absolute_recipe_url(self, base, url, expected) -> None:
        assert absolute_recipe_url(base, url) == expected


def _payload() -> dict:
    """A week shaped exactly as `getSavedPlan` returns it.

    Note `title` is the slot and `food[0].name` is the meal — the two fields
    that read like each other's job.
    """
    return {
        "days": [
            {
                "id": 1,
                "date": "2026-09-07",
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
                                    },
                                    {"componentId": 12, "name": "Rice", "recipe": None},
                                ],
                            }
                        ],
                        "attendees": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
                    },
                    {
                        "id": 102,
                        "slotId": 4,
                        "mealId": 901,
                        "title": "Breakfast",
                        "food": [{"name": "Porridge"}],
                        "time": "08:00:00",
                        "locked": False,
                        "courses": [],
                        "member": {"id": 2, "name": "Bob"},
                    },
                ],
            },
            {
                "id": 2,
                "date": "2026-09-08",
                "meals": [
                    {
                        "id": 103,
                        "slotId": 6,
                        "title": "Packed lunch",
                        "food": [{"name": "Leftovers"}],
                        "time": None,
                        "leftoverOf": 101,
                        "courses": [],
                    }
                ],
            },
        ]
    }


class TestParsePlan:
    def test_meal_name_comes_from_food_not_title(self) -> None:
        """The trap: `title` is the slot, the meal is `food[0].name`."""
        meals = parse_plan(_payload(), BASE)
        dinner = next(m for m in meals if m.slot_id == 5)
        assert dinner.slot_name == "Dinner"
        assert dinner.name == "Chilli con carne"

    def test_reads_every_meal(self) -> None:
        assert len(parse_plan(_payload(), BASE)) == 3

    def test_recipe_urls_are_made_absolute(self) -> None:
        dinner = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 5)
        assert dinner.recipe_urls == [f"{BASE}/recipe/alice/chilli"]

    def test_component_without_a_recipe_has_no_url(self) -> None:
        dinner = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 5)
        rice = dinner.courses[0].components[1]
        assert rice.name == "Rice"
        assert rice.recipe_url is None

    def test_member_and_attendees_stay_distinct(self) -> None:
        meals = parse_plan(_payload(), BASE)
        breakfast = next(m for m in meals if m.slot_id == 4)
        dinner = next(m for m in meals if m.slot_id == 5)
        assert breakfast.member == "Bob" and breakfast.attendees == ()
        assert dinner.member is None and dinner.attendees == ("Alice", "Bob")

    def test_flags_and_times(self) -> None:
        meals = parse_plan(_payload(), BASE)
        dinner = next(m for m in meals if m.slot_id == 5)
        lunch = next(m for m in meals if m.slot_id == 6)
        assert dinner.locked is True and dinner.meal_time == time(18, 30)
        assert lunch.locked is False and lunch.meal_time is None
        assert lunch.leftover_of == 101

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"days": None}, {"days": []}, {"days": [None]}, "nonsense", []],
    )
    def test_unreadable_payloads_give_nothing_rather_than_raising(self, payload) -> None:
        assert parse_plan(payload, BASE) == []

    def test_one_bad_meal_does_not_lose_the_rest(self) -> None:
        """A single malformed entry should cost that meal, not the whole update."""
        payload = _payload()
        payload["days"][0]["meals"].insert(0, "not a meal")
        payload["days"].append({"date": "oops", "meals": []})
        assert len(parse_plan(payload, BASE)) == 3

    def test_missing_food_gives_no_name_not_an_empty_one(self) -> None:
        payload = {"days": [{"date": "2026-09-07", "meals": [{"title": "Dinner"}]}]}
        (meal,) = parse_plan(payload, BASE)
        assert meal.name is None
        assert meal.slot_name == "Dinner"


class TestSlots:
    def test_ordered_by_time_then_name(self) -> None:
        slots = slots_in(parse_plan(_payload(), BASE))
        assert [s.name for s in slots] == ["Breakfast", "Dinner", "Packed lunch"]

    def test_timeless_slots_sort_last(self) -> None:
        """A slot with no time has no place in the day, so it goes after those that do."""
        slots = slots_in(parse_plan(_payload(), BASE))
        assert slots[-1].name == "Packed lunch"
        assert slots[-1].meal_time is None

    def test_deduplicates_across_days(self) -> None:
        payload = _payload()
        payload["days"][1]["meals"].append(
            {
                "id": 104,
                "slotId": 5,
                "title": "Dinner",
                "food": [{"name": "Fish pie"}],
                "time": "18:30:00",
                "courses": [],
            }
        )
        assert len([s for s in slots_in(parse_plan(payload, BASE)) if s.slot_id == 5]) == 1


class TestMealFor:
    def test_finds_by_slot_id(self) -> None:
        meals = parse_plan(_payload(), BASE)
        slot = Slot(slot_id=5, name="Dinner", meal_time=time(18, 30))
        found = meal_for(meals, date(2026, 9, 7), slot)
        assert found is not None and found.name == "Chilli con carne"

    def test_nothing_planned_is_none(self) -> None:
        meals = parse_plan(_payload(), BASE)
        slot = Slot(slot_id=5, name="Dinner", meal_time=time(18, 30))
        assert meal_for(meals, date(2026, 9, 8), slot) is None

    def test_falls_back_to_name_when_the_slot_has_no_id(self) -> None:
        meals = parse_plan(
            {
                "days": [
                    {
                        "date": "2026-09-07",
                        "meals": [{"title": "Dinner", "food": [{"name": "Stew"}]}],
                    }
                ]
            },
            BASE,
        )
        found = meal_for(meals, date(2026, 9, 7), Slot(slot_id=None, name="Dinner"))
        assert found is not None and found.name == "Stew"


class TestEvents:
    def test_a_timed_meal_is_an_appointment(self) -> None:
        meal = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 5)
        timing = event_timing(meal, timedelta(hours=1))
        assert timing.all_day is False
        assert timing.start == datetime(2026, 9, 7, 18, 30)
        assert timing.end == datetime(2026, 9, 7, 19, 30)

    def test_a_timeless_meal_is_all_day_with_an_exclusive_end(self) -> None:
        """iCalendar and Home Assistant both want the day *after* as the end."""
        meal = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 6)
        timing = event_timing(meal, timedelta(hours=1))
        assert timing.all_day is True
        assert timing.start == date(2026, 9, 8)
        assert timing.end == date(2026, 9, 9)

    def test_timings_carry_no_timezone(self) -> None:
        """Localising is the caller's job, where Home Assistant's timezone is known."""
        meal = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 5)
        assert event_timing(meal, timedelta(hours=1)).start.tzinfo is None

    def test_summary_leads_with_the_slot(self) -> None:
        meals = parse_plan(_payload(), BASE)
        assert event_summary(next(m for m in meals if m.slot_id == 5)) == "Dinner: Chilli con carne"

    def test_summary_survives_an_unnamed_meal(self) -> None:
        meal = PlannedMeal(day=date(2026, 9, 7), slot_id=1, slot_name="Dinner", name=None)
        assert event_summary(meal) == "Dinner"
        assert event_summary(PlannedMeal(date(2026, 9, 7), None, "", None)) == "Meal"

    def test_description_lists_courses_and_diners(self) -> None:
        meals = parse_plan(_payload(), BASE)
        text = event_description(next(m for m in meals if m.slot_id == 5))
        assert f"Main: Chilli ({BASE}/recipe/alice/chilli), Rice" in text
        assert "Eating: Alice, Bob" in text

    def test_description_names_the_member_for_an_individual_meal(self) -> None:
        meals = parse_plan(_payload(), BASE)
        assert "For: Bob" in event_description(next(m for m in meals if m.slot_id == 4))


class TestAttributes:
    def test_exposes_the_useful_fields(self) -> None:
        meal = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 5)
        attrs = meal.as_attributes()
        assert attrs["date"] == "2026-09-07"
        assert attrs["slot"] == "Dinner"
        assert attrs["meal_time"] == "18:30:00"
        assert attrs["attendees"] == ["Alice", "Bob"]
        assert attrs["locked"] is True
        assert attrs["is_leftovers"] is False
        assert attrs["recipe_urls"] == [f"{BASE}/recipe/alice/chilli"]
        assert attrs["courses"][0]["components"][0]["recipe_title"] == "Chilli con carne"

    def test_leftovers_are_flagged(self) -> None:
        meal = next(m for m in parse_plan(_payload(), BASE) if m.slot_id == 6)
        assert meal.as_attributes()["is_leftovers"] is True
