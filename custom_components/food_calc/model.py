"""Pure transformations over the Food Calc plan API payload.

Free of Home Assistant imports on purpose. The week arithmetic and the shaping
of a plan into meals are the parts most likely to be quietly wrong, and keeping
them here means they can be tested without a Home Assistant harness.

The payload parsed here is what ``GET /api/plans/{household_id}/{monday}``
returns. Three of its shapes are worth stating plainly, because two of them
look like they mean the opposite of what they do:

* a meal's ``title`` is the **slot** name ("Dinner"), not the meal;
* the meal itself is ``food[0].name`` ("Chilli con carne");
* ``recipe.url`` is **relative** ("/recipe/alice/chilli"), so it needs the
  configured base URL in front of it before it is a link anyone can follow.

``member`` and ``attendees`` are mutually exclusive in the payload: a meal row
belonging to one person carries ``member`` and no attendees, a shared one
carries ``attendees`` and no member. Both are surfaced as-is rather than
flattened into one "who is eating" field, because the distinction is the
difference between "Sam's dinner" and "dinner, which Sam is coming to".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urljoin

ISO_DAY_LENGTH = 10


def monday_of(day: date) -> date:
    """The Monday of the week ``day`` falls in.

    Plans are keyed by their starting Monday, so anything naming a week has to
    agree on which Monday that is. Mirrors ``mondayOf`` in the app's
    ``src/lib/dates.ts``, Sunday included: Python's ``weekday()`` calls Sunday
    6, which rounds back to the Monday that *started* the week Sunday ends,
    rather than forward to tomorrow's.
    """
    return day - timedelta(days=day.weekday())


def weeks_covering(start: date, end: date) -> list[date]:
    """Every plan week (as its Monday) overlapping the inclusive range.

    A range is not one fetch: Home Assistant asks a calendar for arbitrary
    spans, and even the sensors span two weeks whenever "tomorrow" is a Monday.
    An end before the start is an empty range, not an infinite loop.
    """
    if end < start:
        return []
    weeks: list[date] = []
    week = monday_of(start)
    last = monday_of(end)
    while week <= last:
        weeks.append(week)
        week += timedelta(days=7)
    return weeks


def parse_iso_day(value: Any) -> date | None:
    """An ISO day from the payload, or ``None`` for anything that is not one.

    Dates arrive as ``"2026-09-07"``, but the endpoint has carried a full
    timestamp before now, so only the first ten characters are trusted.
    """
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:ISO_DAY_LENGTH])
    except ValueError:
        return None


def parse_meal_time(value: Any) -> time | None:
    """A slot's time of day, or ``None`` for a slot that has none.

    Postgres hands back ``"18:30:00"``; ``"18:30"`` is accepted too so a slot
    time edited by hand does not silently turn every dinner into an all-day
    event.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def absolute_recipe_url(base_url: str, url: Any) -> str | None:
    """A recipe link the payload gives relatively, made absolute.

    ``urljoin`` rather than concatenation so a base URL with or without a
    trailing slash both land on the same place, and so an absolute URL — if the
    app ever starts sending one — is passed through rather than mangled.
    """
    if not isinstance(url, str) or not url:
        return None
    return urljoin(base_url if base_url.endswith("/") else base_url + "/", url.lstrip("/"))


@dataclass(frozen=True)
class Component:
    """One dish within a course, and the recipe behind it where there is one."""

    name: str
    recipe_url: str | None = None
    recipe_title: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "recipe_url": self.recipe_url,
            "recipe_title": self.recipe_title,
        }


@dataclass(frozen=True)
class Course:
    """A named course ("Main", "Pudding") and the components making it up."""

    name: str
    components: tuple[Component, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "components": [c.as_dict() for c in self.components]}


@dataclass(frozen=True)
class PlannedMeal:
    """One meal in one slot on one day."""

    day: date
    slot_id: int | None
    slot_name: str
    name: str | None
    meal_time: time | None = None
    courses: tuple[Course, ...] = ()
    member: str | None = None
    attendees: tuple[str, ...] = ()
    locked: bool = False
    leftover_of: int | None = None
    meal_id: int | None = None
    plan_day_meal_id: int | None = None

    @property
    def recipe_urls(self) -> list[str]:
        """Every recipe linked from this meal, in course then component order."""
        return [
            component.recipe_url
            for course in self.courses
            for component in course.components
            if component.recipe_url
        ]

    def as_attributes(self) -> dict[str, Any]:
        """The meal as Home Assistant state attributes."""
        return {
            "date": self.day.isoformat(),
            "slot": self.slot_name,
            "slot_id": self.slot_id,
            "meal_time": self.meal_time.isoformat() if self.meal_time else None,
            "courses": [c.as_dict() for c in self.courses],
            "recipe_urls": self.recipe_urls,
            "member": self.member,
            "attendees": list(self.attendees),
            "locked": self.locked,
            "is_leftovers": self.leftover_of is not None,
            "meal_id": self.meal_id,
            "plan_day_meal_id": self.plan_day_meal_id,
        }


@dataclass(frozen=True)
class Slot:
    """A meal slot a household has, as discovered from a plan."""

    slot_id: int | None
    name: str
    meal_time: time | None = None


@dataclass(frozen=True)
class EventTiming:
    """When a meal happens, in terms a calendar can use.

    Kept free of timezones deliberately: a plan day is a *calendar* day to the
    household that planned it, and a slot time is a wall-clock time. Attaching
    the Home Assistant timezone is the caller's job, where that timezone is
    actually known — doing it here in UTC would slide Sunday dinner into Monday
    for anyone east of Greenwich.
    """

    start: date | datetime
    end: date | datetime
    all_day: bool


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_components(raw: Any, base_url: str) -> tuple[Component, ...]:
    if not isinstance(raw, list):
        return ()
    components: list[Component] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        recipe = item.get("recipe")
        url = title = None
        if isinstance(recipe, dict):
            url = absolute_recipe_url(base_url, recipe.get("url"))
            raw_title = recipe.get("title")
            title = raw_title if isinstance(raw_title, str) else None
        components.append(Component(name=name, recipe_url=url, recipe_title=title))
    return tuple(components)


def _parse_courses(raw: Any, base_url: str) -> tuple[Course, ...]:
    if not isinstance(raw, list):
        return ()
    courses: list[Course] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        courses.append(
            Course(
                name=name if isinstance(name, str) else "",
                components=_parse_components(item.get("components"), base_url),
            )
        )
    return tuple(courses)


def _parse_names(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    names = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return tuple(names)


def _meal_name(raw: Any) -> str | None:
    """The meal itself, which the payload keeps in ``food[0].name``.

    Not ``title`` — that is the slot. A meal with no food entry has no name to
    show, which is different from having an empty one.
    """
    names = _parse_names(raw)
    return names[0] if names else None


def parse_plan(payload: Any, base_url: str = "") -> list[PlannedMeal]:
    """Every meal in one week's payload, in day then slot order.

    Anything unreadable is skipped rather than raised on: a single malformed
    meal should cost that meal, not the whole update and every sensor with it.
    """
    if not isinstance(payload, dict):
        return []
    days = payload.get("days")
    if not isinstance(days, list):
        return []

    meals: list[PlannedMeal] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        when = parse_iso_day(day.get("date"))
        if when is None:
            continue
        entries = day.get("meals")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            slot_name = entry.get("title")
            meals.append(
                PlannedMeal(
                    day=when,
                    slot_id=_int_or_none(entry.get("slotId")),
                    slot_name=slot_name if isinstance(slot_name, str) else "",
                    name=_meal_name(entry.get("food")),
                    meal_time=parse_meal_time(entry.get("time")),
                    courses=_parse_courses(entry.get("courses"), base_url),
                    member=(
                        entry["member"]["name"]
                        if isinstance(entry.get("member"), dict)
                        and isinstance(entry["member"].get("name"), str)
                        else None
                    ),
                    attendees=_parse_names(entry.get("attendees")),
                    locked=bool(entry.get("locked")),
                    leftover_of=_int_or_none(entry.get("leftoverOf")),
                    meal_id=_int_or_none(entry.get("mealId")),
                    plan_day_meal_id=_int_or_none(entry.get("id")),
                )
            )
    return meals


def slots_in(meals: list[PlannedMeal]) -> list[Slot]:
    """The distinct slots appearing across ``meals``, in the order a day runs.

    Slots are what the sensors are created from, so this drives how many
    entities exist. Ordered by time where a slot has one — a household reading
    its own entity list expects breakfast above dinner — and by name after, so
    the order does not shuffle between restarts.
    """
    seen: dict[Any, Slot] = {}
    for meal in meals:
        key = meal.slot_id if meal.slot_id is not None else meal.slot_name
        if key not in seen:
            seen[key] = Slot(slot_id=meal.slot_id, name=meal.slot_name, meal_time=meal.meal_time)
    return sorted(
        seen.values(),
        key=lambda s: (s.meal_time is None, s.meal_time or time.min, s.name),
    )


def meal_for(meals: list[PlannedMeal], day: date, slot: Slot) -> PlannedMeal | None:
    """The meal in one slot on one day, or ``None`` if nothing is planned.

    Matches on slot id where there is one and falls back to the name, so a
    household whose slots predate ids still gets its sensors.
    """
    for meal in meals:
        if meal.day != day:
            continue
        if slot.slot_id is not None:
            if meal.slot_id == slot.slot_id:
                return meal
        elif meal.slot_name == slot.name:
            return meal
    return None


def event_timing(meal: PlannedMeal, duration: timedelta) -> EventTiming:
    """When a meal sits on a calendar.

    A slot with a time becomes an appointment of ``duration``; a slot without
    one becomes an all-day event, since "some time on Wednesday" is exactly
    what an all-day event means. All-day ends are exclusive, per iCalendar and
    Home Assistant both, so a one-day event ends the following day.
    """
    if meal.meal_time is None:
        return EventTiming(start=meal.day, end=meal.day + timedelta(days=1), all_day=True)
    start = datetime.combine(meal.day, meal.meal_time)
    return EventTiming(start=start, end=start + duration, all_day=False)


def event_summary(meal: PlannedMeal) -> str:
    """The one line a calendar shows for a meal.

    The slot leads because a calendar is read by time of day, and an unplanned
    or unnamed meal still says which slot it is rather than showing blank.
    """
    if meal.name:
        return f"{meal.slot_name}: {meal.name}" if meal.slot_name else meal.name
    return meal.slot_name or "Meal"


def event_description(meal: PlannedMeal) -> str:
    """The courses, one per line, with recipe links where there are any."""
    lines: list[str] = []
    for course in meal.courses:
        parts = []
        for component in course.components:
            parts.append(
                f"{component.name} ({component.recipe_url})"
                if component.recipe_url
                else component.name
            )
        if parts:
            lines.append(f"{course.name}: {', '.join(parts)}" if course.name else ", ".join(parts))
    if meal.member:
        lines.append(f"For: {meal.member}")
    elif meal.attendees:
        lines.append(f"Eating: {', '.join(meal.attendees)}")
    return "\n".join(lines)
