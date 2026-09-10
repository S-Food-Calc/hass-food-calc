# Food Calc for Home Assistant

Brings a [Food Calc](https://github.com/S-Food-Calc/F-Sveletkit) household's meal
plan into Home Assistant as sensors and a calendar, so what's for dinner can
drive dashboards and automations.

Read-only. This integration never writes to your plan.

## What you get

For every meal slot your household has defined — Breakfast, Dinner, whatever you
have called them — you get two sensors:

| Entity | State |
| --- | --- |
| `sensor.food_calc_dinner_today` | `Chilli con carne` |
| `sensor.food_calc_dinner_tomorrow` | `Fish pie` |

The state is the meal. Everything else is attributes:

```yaml
planned: true
date: "2026-09-09"
slot: Dinner
meal_time: "18:30:00"
courses:
  - name: Main
    components:
      - name: Chilli
        recipe_url: https://food-calc.example/recipe/alice/chilli
        recipe_title: Chilli con carne
recipe_urls:
  - https://food-calc.example/recipe/alice/chilli
member: null
attendees: [Alice, Bob]
locked: true
is_leftovers: false
```

A slot with nothing planned reports `unknown` with `planned: false`, rather than
a magic string — so a template can tell "no dinner planned" from "this sensor is
broken".

You also get `calendar.food_calc_meal_plan`, with every planned meal as an event.
A slot with a time becomes an hour-long appointment; a slot without one becomes
an all-day event. Courses, recipe links and diners go in the description.

### Do you want the calendar entity?

Food Calc already publishes an ICS feed, and Home Assistant can subscribe to that
on its own with the built-in Remote Calendar integration — no custom component
required. The calendar here exists for what ICS cannot carry: it is built from
the same JSON as the sensors, so its events hold the courses and recipe links,
and it shares one poll with them instead of being a second thing to keep in step.

If all you want is meals in your calendar, the ICS feed is the simpler answer.

## Installing

### HACS

This is not in the HACS default store, so add it as a custom repository:

1. HACS → three-dot menu → **Custom repositories**
2. Repository: `https://github.com/S-Food-Calc/hass-food-calc`, category **Integration**
3. Install **Food Calc**, then restart Home Assistant

HACS reads the repository over the GitHub API using the token it gets from its
own device-flow login. That token is requested with **no OAuth scopes**, so it
can only see public repositories — there is no setting anywhere in HACS for
supplying your own token instead. A private repository simply cannot be
installed this way; use the manual install below if this one is ever made
private again.

### Manually

Copy `custom_components/food_calc` into your `config/custom_components/`
directory and restart Home Assistant.

## Setting up

**Settings → Devices & Services → Add Integration → Food Calc.**

You need three things:

| Field | Where it comes from |
| --- | --- |
| Base URL | Where Food Calc is hosted, e.g. `https://food-calc.example` |
| Household ID | The number in your household's URL — `12` in `/h/12/plan` |
| Plan API token | Household settings page, under **Plan API** |

The token *is* the credential — there is no separate password — so treat it like
one. It can be revoked from the same settings page, which is also where you can
see when it was last used.

Two things will make a working token stop working, and both send Home Assistant
into a re-authentication prompt rather than failing quietly:

- somebody revokes it from the settings page;
- **the person who created it leaves the household** — their tokens are revoked
  along with their membership.

## How often it polls

Every 15 minutes. A meal plan changes when somebody edits it, which is rarely and
never urgently, and this keeps a household's Home Assistant from being the
heaviest client its own app has.

The calendar fetches beyond that window on demand: scrolling to next month pulls
those weeks in rather than showing an empty month that only looks like an empty
plan.

## Example automations

Tell everyone what's for dinner, each morning:

```yaml
automation:
  - alias: Announce dinner
    triggers:
      - trigger: time
        at: "08:00:00"
    conditions:
      - condition: template
        value_template: "{{ has_value('sensor.food_calc_dinner_today') }}"
    actions:
      - action: notify.family
        data:
          message: "Tonight: {{ states('sensor.food_calc_dinner_today') }}"
```

Remind whoever is cooking to get tomorrow's out of the freezer:

```yaml
automation:
  - alias: Defrost reminder
    triggers:
      - trigger: time
        at: "20:00:00"
    conditions:
      - condition: template
        value_template: "{{ state_attr('sensor.food_calc_dinner_tomorrow', 'planned') }}"
    actions:
      - action: notify.family
        data:
          message: >-
            Tomorrow is {{ states('sensor.food_calc_dinner_tomorrow') }}.
            {% set urls = state_attr('sensor.food_calc_dinner_tomorrow', 'recipe_urls') %}
            {% if urls %}Recipe: {{ urls[0] }}{% endif %}
```

## Development

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pytest          # model, API client, config flow and entity tests
ruff check .
ruff format --check .
```

### Releasing

Bump `version` in `custom_components/food_calc/manifest.json` and merge to
`main`. The Release workflow reads that version, tags it `vX.Y.Z` and publishes
a GitHub release — HACS installs from releases, so a version that is never
released is a version nobody can install. A merge that does not touch the
manifest re-runs the workflow and does nothing, which is the usual case.

The manifest is the only place a version lives, so a tag and a manifest cannot
drift apart.

`custom_components/food_calc/model.py` deliberately imports no Home Assistant:
the week arithmetic and the plan-to-entity shaping are the parts most likely to
be quietly wrong, so they are kept testable on their own.

## Licence

MIT. See [LICENSE](LICENSE).
