# Aurora

Aurora is a daily operating system built to turn reflection, passive signals, and planned activity into a more useful picture of the day.

It combines:

- structured morning, midday, and evening inputs
- mirrored and derived telemetry
- explainable scoring
- adaptive daily prompts
- pattern selection
- execution planning

The aim is straightforward: help a person understand what kind of day they are having, what is shaping that state, and what the most appropriate next action is.

This directory contains a sanitized demo mirror of the Aurora application. Core implementation logic is preserved, while live identifiers, internal URLs, and host-specific paths are replaced with placeholders.

## Overview

Aurora is centered on one continuous daily loop rather than a collection of disconnected tools.

The loop works like this:

1. the day begins with a structured morning check-in
2. Aurora writes that state into a Notion-backed day graph
3. mirrored and derived signals feed the Pneuma scoring engine
4. the morning state unlocks adaptive Quest generation
5. the same context ranks and stores a daily Echoform
6. Focus Blocks turn that state into schedulable execution
7. midday and evening inputs close the loop and enrich future recommendations

The result is a system that does more than record a day. It interprets it, acts on it, and preserves it in a structured history.

## Problem

Most personal systems solve only one part of the problem:

- journaling systems capture reflection but rarely guide action
- dashboards show metrics but do not help with interpretation
- task tools organize commitments without enough sensitivity to real capacity
- habit systems reward consistency without much context

Aurora addresses those gaps by treating the day as a state model that can be updated, interpreted, and acted on as conditions change.

## Core Product Loop

## 1. Morning check-in

The day starts with the Morning Undercurrent flow. This captures the self-reported signals that most strongly shape the opening state of the day, including:

- energy
- clarity
- mood
- stress
- spiritual orientation
- wellness
- sleep score
- bedtime
- base heart rate
- state tags
- main drag
- daily intent

Aurora validates these inputs, finds or creates the current day page, and upserts the linked daily record in Notion.

This is also the gate for the higher-order system behavior. Until the morning state is present, Aurora intentionally withholds several adaptive features.

## 2. Day graph and persistence

Aurora uses Notion as a structured day graph rather than a loose note store.

At the center of the model is a single day page, with related records attached to it over time:

- the Undercurrent daily record
- Quest runs
- a selected Echoform
- Signal Field entries
- state shifts
- focus activity

This structure is what allows the system to connect reflection, execution, and history without losing continuity.

## 3. Scoring through Pneuma

Aurora computes a canonical scorecard called Pneuma. The score engine combines self-report and mirrored inputs into four dimensions:

- Capacity
- Alignment
- Load
- Steadiness

These scores are explicit rather than opaque. The system stores and surfaces:

- weighted inputs
- derived sub-scores
- confidence
- explanatory context

The scoring layer is designed to answer not only "what is the score" but also "why did the system arrive there."

## 4. Quest generation

Once the morning state exists, Aurora can generate the day's Quests.

Quest selection uses current and recent context, including:

- morning energy
- state tags
- main drag
- prior carryover
- tomorrow-need history
- neglected-domain history

Aurora typically creates three offers:

- `Best Fit`
- `Low-Friction`
- `Wild Card`

The design goal is to move the system from description into action. Rather than producing a score and stopping there, Aurora converts the state model into a small set of next-step options.

## 5. Echoform selection

Echoforms are recurring patterns, stances, or modes of response that Aurora can recommend for a given day.

Aurora ranks them from the same morning context used for Quests, drawing on:

- drag matches
- carryover matches
- state-tag matches
- need matches
- neglected-domain matches
- formation lineage
- accumulated level and XP

The selected Echoform is stored on the day page, and practice logging updates both daily and lifetime progress.

This gives the system a second layer of guidance: not only what to do next, but how to approach the day.

## 6. Focus Blocks

Focus Blocks extend Aurora from interpretation into execution.

They use Notion-backed Arc Nodes and Arc Engines to:

- structure planned work
- suggest working modes
- log real sessions
- connect those sessions back to the active day

This makes Aurora more than a check-in system. It becomes a lightweight operating interface for carrying the day forward.

## 7. Midday and evening closure

Aurora continues writing into the same day record with midday and evening inputs.

That allows the system to track:

- whether the morning held or degraded
- what became draining
- what proved restorative
- what remains unresolved
- what tomorrow now needs

Over time, that creates a much richer history than a single daily score could provide.

## Key Concepts

## Undercurrent

Undercurrent is the main reflection flow. Morning, midday, and evening entries all update the same day-linked record.

It is the backbone of the day model and the primary source of explicit self-report.

## Pneuma

Pneuma is Aurora's explainable score system.

It translates the day state into four readable dimensions with weighted logic, derived support signals, and confidence.

## Quests

Quests are adaptive daily action prompts selected from a library based on the current state of the day.

They are meant to be small enough to act on immediately and contextual enough to feel relevant.

## Echoforms

Echoforms are pattern-based recommendations that shape how the day is approached.

They add a longer-term development layer to the product through selection history, practice logging, XP, and effective level.

## Focus Blocks

Focus Blocks provide the execution surface for planned work.

They connect day state to concrete sessions and allow execution data to flow back into interpretation.

## Utility Actions

Aurora also includes a small number of practical utilities such as:

- `Wake Atelier`
- download helpers
- rebuild helpers

These are supporting features rather than the main product story, but they show how Aurora can act as a control plane as well as an interpretation layer.

## Why The Design Matters

Aurora is notable less for any single feature than for how the features connect.

Several design choices are especially important:

- one day page anchors the system
- reflection and telemetry are treated as complementary, not competing, inputs
- scoring is explicit and explainable
- interpretation leads directly into action through Quests and Echoforms
- execution history can flow back into future scoring and planning

The overall effect is a system with memory. Each day contributes not only new data, but more context for how the next day should be understood.

## Notion As Application Substrate

Notion plays a structural role in Aurora rather than simply acting as content storage.

Aurora uses it for:

- day-level records
- relational linking across the loop
- Quest library and Quest runs
- Echoform codex storage
- Focus Block metadata
- event logging for signals and state shifts

This is one of the more distinctive implementation choices in the project: Aurora operates as a custom application layer on top of a structured Notion model.

For the schema companion, see [NOTION-TEMPLATE-SCHEMAS.md](/opt/home-stack/NOTION-TEMPLATE-SCHEMAS.md).

## Interface Surfaces

Aurora is presented as a working control plane, not only as an API.

Primary UI surfaces include:

- the main dashboard
- the Morning, Midday, and Evening Undercurrent forms
- Pneuma scorecards and breakdown views
- Quest selection and completion states
- the daily Echoform surface
- the Focus Blocks planning board
- state-shift and reflection tools

## Visual Placeholders

The following placeholders mark the most useful visuals for a walkthrough or presentation:

- `[Screenshot Placeholder: Aurora dashboard hero showing Pneuma cards, Daily Echoform, and quest state]`
- `[Screenshot Placeholder: Morning Undercurrent form with energy, clarity, drag, and intent inputs]`
- `[Screenshot Placeholder: Pneuma score breakdown dialog showing weighted inputs and confidence]`
- `[Screenshot Placeholder: Daily quest card with Best Fit, Low-Friction, and Wild Card offer states]`
- `[Screenshot Placeholder: Daily Echoform card showing why it was selected and current XP/level]`
- `[Screenshot Placeholder: Focus Blocks weekly board with scheduled sessions and Arc Nodes]`
- `[Screenshot Placeholder: State Shift form or daily notes panel showing end-of-day reflection tools]`

Suggested filenames live in [screenshots/README.md](/opt/home-stack/aurora/Demo/screenshots/README.md).

## Code Structure

## `app.py`

`app.py` is the main orchestration layer. It includes:

- FastAPI routes
- request models
- Notion helpers
- Undercurrent submit handlers
- Quest generation
- Echoform selection and practice logging
- Pneuma score generation
- Focus Block save logic

The file is intentionally broad in responsibility because it shows the end-to-end product loop in one place.

## `index_runtime.py`

`index_runtime.py` builds the runtime-facing interpretation layer for the score output.

It turns the scorecard into a UI-ready representation with more readable presentation logic.

## `templates/`

The templates render Aurora as an application surface rather than a pure backend.

Key files include:

- `index.html`
- `focus_blocks.html`
- `_undercurrent_forms.html`
- `_state_shift_form.html`
- `_daily_notes_form.html`
- `_book_reflection_form.html`

## Demo Mirror Notes

This demo directory is generated from the live Aurora source and then sanitized.

Relevant files:

- [refresh-demo.sh](/opt/home-stack/aurora/Demo/refresh-demo.sh)
- [sanitize-app.sed](/opt/home-stack/aurora/Demo/sanitize-app.sed)
- [sanitize-templates.sed](/opt/home-stack/aurora/Demo/sanitize-templates.sed)

The demo mirror keeps the implementation close to the live project while replacing sensitive values with placeholders such as:

- `DEMO_DB_UNDERCURRENT`
- `DEMO_DB_SIGNAL_FIELD`
- `DEMO_ARC_NODE_MEETING`
- `DEMO_RITE_BREATH_ANCHOR`
- `DEMO_TARGET_MAC`
- `DEMO_BROADCAST_IP`

To refresh the mirror:

```bash
cd path/to/aurora/Demo
./refresh-demo.sh
```

## Roadmap

Aurora already functions as a coherent daily system, but several expansions would deepen the product significantly.

## 1. App-first interface

Aurora currently works well as a control-plane dashboard. A dedicated app interface would make it more ambient and accessible across the day.

Promising directions:

- mobile-first morning, midday, and evening flows
- lock-screen and widget surfaces
- faster transitions between state interpretation and action
- offline capture with later sync into the day graph

## 2. Watch complications and wearable surfaces

Wearables would make Aurora more glanceable and less dependent on opening the full interface.

Useful surfaces include:

- current Pneuma summary
- active Quest
- selected Echoform
- Focus Block start and stop
- quick state-shift logging
- regulation prompts when certain score conditions are triggered

## 3. Pico and watch-listening voice commands

Aurora would benefit from a lighter voice interface, especially for moments when opening the full application is too much friction.

Likely commands include:

- log a state shift
- start a focus block
- accept the current Quest
- log Echoform practice
- report the current state of the day

The broader opportunity is to make Aurora feel less like a dashboard and more like a live companion system.

## 4. RPG-style progression and boss mechanics

Aurora already contains the beginnings of a game layer through:

- Quests
- XP
- Echoform levels
- lingering bonuses
- day-state interpretation

That foundation could support richer mechanics such as:

- boss battles triggered by recurring low-score patterns
- arcs driven by repeated flag history
- seasonal campaigns organized around specific domains
- special encounter conditions tied to score combinations
- repair chains after clusters of disruption
- class-like specialization through Echoform lineage

The strongest version of this idea would ground the game layer in real score and flag history rather than decorative gamification.

Example:

- if Load remains elevated across several days
- if the same disruptor pattern keeps recurring
- if state-shift responses repeatedly fail

Aurora could surface a named "boss" pattern with suggested counters, conditions for resolution, and consequences for avoidance.

## 5. Broader configuration through environment variables and structured config

Aurora already uses environment variables in a few places. A fuller configuration pass would make the system easier to deploy, evolve, and share.

Strong candidates include:

- Notion database identifiers
- rite identifiers
- Arc Node mappings
- media targets
- playlist defaults
- local file paths
- feature flags
- experiment toggles
- device-integration settings

## 6. Event and automation layer

Aurora has a strong base for event-driven behavior.

Potential additions:

- score-threshold notifications
- Quest escalation or expiration rules
- Echoform reminders by day phase
- Focus Block suggestions triggered by state changes
- recovery nudges after clustered disruptions
- nightly wrap-up prompts when the evening loop is incomplete

## 7. Richer historical views

Aurora already stores meaningful history. The next step is making that history easier to read and act on.

Examples:

- weekly after-action reports
- streak and anti-streak views
- boss-history summaries
- domain heatmaps
- "what has helped lately?" summaries
- Echoform effectiveness over time
- Quest completion by energy state

## 8. Experiment surface

Aurora is well suited to controlled experimentation because the scoring and selection logic are already structured.

Good candidates:

- alternate score-weight sets
- multiple Quest selector modes
- different Echoform ranking models
- variable penalties for carryover or disruptors
- adaptive reminders based on historical responsiveness

An explicit experiment layer would make tuning faster and more evidence-based.

## Closing

Aurora is best understood as a daily operating system rather than a static dashboard.

It captures state, interprets state, suggests action, remembers what happened, and gradually becomes more informed about what the next day needs.
