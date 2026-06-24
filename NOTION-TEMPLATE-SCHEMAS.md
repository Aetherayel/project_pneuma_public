# Notion Template Schemas

Last reviewed: 2026-06-24

This file is a public-safe schema blueprint derived from the live code contracts in `aurora/app.py` and the Home Assistant bridge. It is meant to help you publish the product model without exposing live Notion IDs or private data.

## Naming Strategy

| Live name | Public template name |
| --- | --- |
| The Undercurrent | Daily Check-ins |
| Resonance Index | Daily Summary |
| Signal Field | Presence Log |
| Rhythmic Rites | Ritual Library |
| State Shifts | Recovery Events |
| Quest Library | Adaptive Task Library |
| Quest Runs | Task Runs |
| The Echoform Codex | Pattern Library |

## Minimum Demo Set

If you want the smallest useful public template pack, start with these four databases:

1. `Daily Summary`
2. `Daily Check-ins`
3. `Presence Log`
4. `Recovery Events`

That is enough to show the core loop from input -> relation -> derived support -> score output.

## 1. Daily Summary

Purpose: the anchor page for each calendar day.

Required properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Name` | Title | Can default to the ISO date string |
| `Date` | Date | Queried directly by the app |

Recommended optional properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Echoform` | Relation -> `Pattern Library` | Selected pattern for the day |
| `Echoform Practiced` | Checkbox | Whether practice was logged |
| `Echoform XP` | Number | XP awarded that day |

Why it matters:

- `Daily Check-ins` relate to this page
- `Presence Log` entries relate to this page
- `Recovery Events` relate to this page
- `Task Runs` relate to this page

## 2. Daily Check-ins

Purpose: one daily page that accumulates morning, midday, and evening inputs.

Required properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Name` | Title | Can stay blank in the live flow, but a title property must exist |
| `Date` | Date | Primary lookup key |
| `Resonance` or `Daily Summary` | Relation -> `Daily Summary` | Day-level parent relation |
| `Version` | Number | Used for app-side versioning |

Morning properties:

| Property | Type |
| --- | --- |
| `Morning Energy` | Number |
| `Morning Clarity` | Number |
| `Morning Mood` | Number |
| `Morning Stress` | Number |
| `Morning Spiritual Orientation` | Number |
| `Morning Wellness` | Number |
| `Sleep Score` | Number |
| `Bedtime` | Rich text |
| `Base HR` | Number |
| `Morning State Tags` | Multi-select |
| `Main Drag` | Multi-select |
| `Daily Intent` | Rich text |
| `Morning Notes` | Rich text |

Midday properties:

| Property | Type |
| --- | --- |
| `Midday Energy` | Number |
| `Midday Focus` | Number |
| `Midday Wellness` | Number |
| `Midday Drift` | Select |
| `Midday Need` | Multi-select |
| `Midday Notes` | Rich text |

Evening properties:

| Property | Type |
| --- | --- |
| `Day Score` | Number |
| `Evening Wellness` | Number |
| `Evening Spiritual Orientation` | Number |
| `Alignment` | Select |
| `State Shift` | Select |
| `State Shift Intensity` | Select |
| `Regulation Response` | Select |
| `Primary Disruptor` | Multi-select |
| `Carryover` | Multi-select |
| `Most Draining` | Select |
| `Neglected Domain` | Multi-select |
| `Most Restorative` | Select |
| `Reflection Note` | Rich text |
| `Gratitude Note` | Rich text |
| `Lesson` | Rich text |
| `Tomorrow Need` | Multi-select |

Additional notes properties:

| Property | Type |
| --- | --- |
| `Daily Notes` | Rich text |
| `Abiding Notes` | Rich text |

Validated option families currently encoded in the app:

| Property | Suggested options |
| --- | --- |
| `Midday Drift` | `better`, `same`, `worse` |
| `Alignment` | `yes`, `no`, `partly` |
| `State Shift` | `more open`, `same`, `more closed` |
| `State Shift Intensity` | `None`, `Mild`, `Strong` |
| `Regulation Response` | `None`, `Avoided`, `Paused`, `Repaired`, `Recentered` |

Good public simplification:

- Keep the field structure
- Rename spiritually specific or very personal labels if needed
- Seed with synthetic sample days

## 3. Presence Log

Purpose: store lightweight timed entries that can represent ritual completion, focus blocks, presence windows, or related activity.

Required properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Signal` | Title | Entry name |
| `Date` | Date | Supports start and end timestamps |
| `Arc Node` | Relation | Optional for a minimal template, required for focus-block mode |
| `Mode` | Select | Examples: `Embodiment`, `Review`, `Creation`, `Learning`, `Problem Solving` |
| `Presence` | Number | Typically 1-5 |
| `Resonance Index` or `Daily Summary` | Relation -> `Daily Summary` | Day-level link |

Optional properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Rite` | Relation -> `Ritual Library` | Used for ritual completion tracking |
| `Book` | Relation -> `Library` | Used for reading/reflection logging |
| `Echoforms` | Relation -> `Pattern Library` | Optional advanced extension |

Why it matters:

- feeds daily presence summaries
- supports ritual completion history
- can also represent focus blocks or activity windows

## 4. Recovery Events

Purpose: capture in-the-moment disruptions and recovery responses during the day.

Required properties:

| Property | Type |
| --- | --- |
| `Shift` or `Name` | Title |
| `Timestamp` | Date |
| `Resonance` or `Daily Summary` | Relation -> `Daily Summary` |
| `Related Undercurrent Day` or `Daily Check-ins` | Relation -> `Daily Check-ins` |
| `Trigger` | Select |
| `Direction` | Select |
| `Response Chosen` | Select |
| `Effect` | Select |
| `Formation Candidate` | Select |
| `Intent Tested` | Select |
| `Intensity` | Number |
| `Need` | Multi-select |
| `Body Cue` | Multi-select |
| `Note` | Rich text |

This database is especially valuable in a public template because it demonstrates:

- event logging
- structured recovery analysis
- same-day aggregation into support scores

## Expansion Modules

Use these if you want the public template set to demonstrate more of the product.

## 5. Ritual Library

Purpose: a reusable catalog of recurring practices.

Required properties:

| Property | Type | Notes |
| --- | --- | --- |
| `Task Name` | Title | Queried directly by the app |
| `Active` | Checkbox | Used to filter active entries |
| `Cadence` | Number | Days between expected completions |
| `Description` | Rich text | UI helper copy |

Recommended derived property:

| Property | Type | Notes |
| --- | --- | --- |
| `Latest Complete Date` | Rollup | From related `Presence Log` entries |

## 6. Adaptive Task Library

Purpose: a catalog of tasks that can be selected based on the current day context.

Recommended properties:

| Property | Type |
| --- | --- |
| `Name` | Title |
| `Active` | Checkbox |
| `Weight` | Number |
| `Domain` | Select |
| `Difficulty` | Select |
| `Energy Required` | Select |
| `Time Cap` | Select |
| `Carryover Match` | Multi-select |
| `Need Match` | Multi-select |
| `Signal Tags` | Multi-select |
| `Drag Match` | Multi-select |
| `Formation Relevant` | Checkbox |
| `Success Condition` | Rich text |
| `Shrink Version` | Rich text |
| `Pneuma Target` | Select or Rich text |
| `Cooldown Days` | Number |

Why it matters:

- this is a strong example of contextual recommendation logic
- it shows how structured self-report can drive adaptive suggestions

## 7. Task Runs

Purpose: store daily offered, accepted, completed, or skipped task instances.

Required properties:

| Property | Type |
| --- | --- |
| `Name` | Title |
| `Date` | Date |
| `Source` | Select |
| `Why Offered` | Rich text |
| `Status` | Select |
| `Offer Slot` | Select |
| `Offer Score` | Number |
| `Selector Version` | Rich text |
| `Formation Candidate` | Checkbox |
| `Quest` or `Task` | Relation -> `Adaptive Task Library` |
| `Resonance Day` or `Daily Summary` | Relation -> `Daily Summary` |
| `XP` | Number |
| `Cost Felt` | Select |

## 8. Pattern Library

Purpose: a catalog of recurring patterns or modes that can be selected for a given day.

Recommended properties:

| Property | Type |
| --- | --- |
| `Name` | Title |
| `Domain Tags` | Multi-select |
| `Drag Match` | Multi-select |
| `Carryover Match` | Multi-select |
| `Need Match` | Multi-select |
| `Signal Tags` | Multi-select |
| `Formation Themes` | Multi-select |
| `Activation Phrase` | Rich text |
| `Shadow Drift` | Rich text |
| `Base Bonus` | Number |
| `Level` | Formula or Number |
| `Boost/Level` | Formula or Number |
| `XP` | Rollup or Number |
| `Legacy Signal XP` | Rollup or Number |
| `Total XP` | Formula or Number |

This is optional for a public release, but it is one of the most distinctive parts of the product model.

## 9. Library

Purpose: optional reading and reflection tracker tied back into the Presence Log.

Recommended properties:

| Property | Type |
| --- | --- |
| `Title` or `Name` | Title |
| `Chapters` | Number |
| `Chapters Complete` | Number |
| `Completion` | Formula |

## 10. Focus-Block Support Tables

Only include these if you want to demonstrate the focus-planning layer.

### Arc Engines

| Property | Type |
| --- | --- |
| `Engine` | Title |
| `Domain` | Select |
| `Line` | Select |
| `Score` | Number |

### Arc Nodes

| Property | Type |
| --- | --- |
| `Node` | Title |
| `Engine` | Relation -> `Arc Engines` |
| `Status` | Status or Select |
| `Novely` | Number |

## Public Demo Seed Suggestions

For a convincing public demo, seed:

1. Seven synthetic `Daily Summary` pages
2. Seven synthetic `Daily Check-ins` pages with morning/midday/evening data
3. Ten to fifteen `Presence Log` entries
4. Three to five `Recovery Events`
5. Five `Ritual Library` items
6. Eight to twelve `Adaptive Task Library` items
7. Three `Task Runs` for one day
8. Four to six `Pattern Library` entries if you want the adaptive-selection story

## Public Template Advice

- Prefer generic labels over deeply private vocabulary.
- Keep relations intact because the relations are part of the product story.
- Use fake but plausible examples.
- Document which fields are hand-entered versus derived.
- Export screenshots only after swapping in synthetic data.

## Best Short Version

If you only publish one schema screenshot or one template overview, make it this chain:

`Daily Check-ins` -> `Daily Summary` -> `Presence Log` + `Recovery Events` -> derived score output

That is the cleanest cross-platform proof of how the product works.
