from __future__ import annotations

from typing import Any
import zlib

from pydantic import BaseModel, Field


MODE_LINES: dict[str, dict[str, Any]] = {
    "CLEAR_RESPONSIVE": {
        "sprite_id": 12,
        "tone": "gentle",
        "why": "Selected when capacity, alignment, and steadiness are all strong while load stays low.",
        "variants": [
            {
                "commentary": "The inner yes is online today. Use it on something real.",
                "next_step": "Press the clearest meaningful task while the signal is still clean.",
            },
            {
                "commentary": "You look open, steady, and alive to the day.",
                "next_step": "Choose the truest task in front of you and work it while the current is clean.",
            },
            {
                "commentary": "This is one of the days where signal and strength agree.",
                "next_step": "Protect the clean window and spend it on something worth remembering.",
            },
        ],
    },
    "CLEAR_ADVANCING": {
        "sprite_id": 8,
        "tone": "dry",
        "why": "Selected when your core scores point to solid movement with low enough drag to keep advancing.",
        "variants": [
            {
                "commentary": "You shipped something real. Mark it.",
                "next_step": "Protect the lane that worked and press one meaningful task.",
            },
            {
                "commentary": "Momentum is present. Do not waste it proving a point.",
                "next_step": "Stay in the lane that is already bearing fruit and keep the rest quiet.",
            },
            {
                "commentary": "The day is giving you enough runway to move.",
                "next_step": "Use the cleanest block on one meaningful task instead of spreading it thin.",
            },
        ],
    },
    "FOCUSED_OVERDRAWN": {
        "sprite_id": 10,
        "tone": "dry",
        "why": "Selected when alignment is holding, but capacity is lower and the cost of focus is rising.",
        "variants": [
            {
                "commentary": "Precision is expensive today. Spend it carefully.",
                "next_step": "Pick one important task, then defend your bedtime.",
            },
            {
                "commentary": "You can still focus, but it is coming out of a thinner account.",
                "next_step": "Use your sharpest minutes on one thing that matters and stop before you fray.",
            },
            {
                "commentary": "The aim is there. The reserves are not endless.",
                "next_step": "Make one deliberate push, then shift your energy toward protecting recovery.",
            },
        ],
    },
    "ABLE_MISALIGNED": {
        "sprite_id": 3,
        "tone": "dry",
        "why": "Selected when you still have workable strength, but Alignment is lagging behind what the day could actually carry.",
        "variants": [
            {
                "commentary": "You have enough engine for today. The issue is aim, not fuel.",
                "next_step": "Name the truest task, close one leak, and let the day get honest again.",
            },
            {
                "commentary": "There is usable strength here, but it is not lined up yet.",
                "next_step": "Stop proving motion and choose one thing that actually agrees with your deeper yes.",
            },
            {
                "commentary": "This is not collapse. It is drift with enough energy to matter.",
                "next_step": "Re-aim the next block around one honest priority instead of another reactive loop.",
            },
        ],
    },
    "NOISY_LEAKING": {
        "sprite_id": 1,
        "tone": "dry",
        "why": "Selected when attention fragmentation is starting to outweigh clarity and steady intent.",
        "variants": [
            {
                "commentary": "You're sampling life like a buffet. Pick a plate.",
                "next_step": "Silence one input stream and finish the smallest real thing.",
            },
            {
                "commentary": "Too many little bites. Not enough real chewing.",
                "next_step": "Close one stream, narrow the field, and complete one concrete thing.",
            },
            {
                "commentary": "The day is leaking out through too many open loops.",
                "next_step": "Choose one lane, mute the rest, and stay with it long enough to feel traction.",
            },
        ],
    },
    "STUCK_SEDENTARY": {
        "sprite_id": 9,
        "tone": "firm",
        "why": "Selected when stillness, low movement, and lower capacity combine into a stalled day shape.",
        "variants": [
            {
                "commentary": "Walk. You're not a brain in a jar.",
                "next_step": "Move for ten minutes, then restart the next obvious task.",
            },
            {
                "commentary": "Your body has been parked long enough for the day to start shrinking.",
                "next_step": "Break the stillness first, then ask your mind to rejoin the day.",
            },
            {
                "commentary": "This looks more stalled than thoughtful.",
                "next_step": "Stand up, go outside if you can, and let motion reopen the next step.",
            },
        ],
    },
    "OUT_ALL_DAY": {
        "sprite_id": 10,
        "tone": "gentle",
        "why": "Selected when the day has been spent mostly away from home with very little landing space.",
        "variants": [
            {
                "commentary": "This day has been lived in transit, not in rooted space.",
                "next_step": "Protect the landing tonight and do not demand home-grade depth from an away-shaped day.",
            },
            {
                "commentary": "You have spent more of today in motion and elsewhere than in settled ground.",
                "next_step": "Call the day what it is, and build a gentler landing instead of squeezing harder.",
            },
            {
                "commentary": "Rootedness has been scarce today.",
                "next_step": "Lower the expectation for deep output and prioritize getting home to yourself tonight.",
            },
        ],
    },
    "CONTEXT_SHREDDING": {
        "sprite_id": 7,
        "tone": "firm",
        "why": "Selected when switch density and fragmentation are severe enough to dominate the day's pattern.",
        "variants": [
            {
                "commentary": "Your attention is getting shredded by too many switches.",
                "next_step": "Collapse the tabs, mute one stream, and give one block to one thing.",
            },
            {
                "commentary": "You are not scattered by fate here. You are being sliced by switching.",
                "next_step": "Reduce the toggling surface and let one task have uninterrupted oxygen.",
            },
            {
                "commentary": "The cost is not just busyness. It is all the re-entry.",
                "next_step": "Shrink the number of contexts in play until your mind can stay somewhere on purpose.",
            },
        ],
    },
    "NIGHT_BLOWBACK": {
        "sprite_id": 10,
        "tone": "gentle",
        "why": "Selected when overnight disruption or late-night carryover is strongly shaping today's cost.",
        "variants": [
            {
                "commentary": "The night kept taking bites out of recovery.",
                "next_step": "Shorten the plan, lower the ask, and make tonight easier to land.",
            },
            {
                "commentary": "You are paying for the night, whether or not the day admits it yet.",
                "next_step": "Keep the day narrow and start setting up a gentler landing before evening gets away from you.",
            },
            {
                "commentary": "Recovery came in fragments, and the bill is due now.",
                "next_step": "Work smaller, move slower, and make tonight easier than last night.",
            },
        ],
    },
    "HEAVY_LOAD": {
        "sprite_id": 5,
        "tone": "gentle",
        "why": "Selected when pressure, stress, or accumulated load is the defining condition of the day.",
        "variants": [
            {
                "commentary": "Today is for faithfulness, not throughput.",
                "next_step": "Shrink the plan to what must be carried and let the rest wait.",
            },
            {
                "commentary": "This is a carrying day, not a proving day.",
                "next_step": "Name the non-negotiable, release the rest, and move with less self-pressure.",
            },
            {
                "commentary": "The weight is real. Pretending otherwise will only make it clumsier.",
                "next_step": "Reduce the ask to what matters most and practice clean mercy with everything else.",
            },
        ],
    },
    "AVOIDANCE_SPIRAL": {
        "sprite_id": 11,
        "tone": "firm",
        "why": "Selected when avoidance cues and low alignment are clustering into a self-protective loop.",
        "variants": [
            {
                "commentary": "What are you trying to get from the scroll?",
                "next_step": "Name the want, close the feed, and choose one honest substitute.",
            },
            {
                "commentary": "You are reaching for relief, but the method is making you hazier.",
                "next_step": "Say the actual ache out loud, then choose a response that tells the truth about it.",
            },
            {
                "commentary": "This looks less like rest and more like hiding in motion.",
                "next_step": "Interrupt the loop, name the hunger, and answer it with something that can actually nourish.",
            },
        ],
    },
    "RECOVERY_DAY": {
        "sprite_id": 5,
        "tone": "gentle",
        "why": "Selected when capacity is low enough that recovery should outrank ambition.",
        "variants": [
            {
                "commentary": "Small faithful things. No heroics.",
                "next_step": "Water, food, light, and an earlier landing tonight.",
            },
            {
                "commentary": "Nothing about today improves by pretending you have more than you do.",
                "next_step": "Take care of the body, do the smallest honest task, and end earlier than pride prefers.",
            },
            {
                "commentary": "Let the day be human-sized.",
                "next_step": "Lower the bar to what can be done cleanly, then pour the rest into restoration.",
            },
        ],
    },
    "RESPONSIVE_UNDER_LOAD": {
        "sprite_id": 8,
        "tone": "gentle",
        "why": "Selected when load is high, but steadiness is still meaningfully intact and available.",
        "variants": [
            {
                "commentary": "Load is real, but you are still reachable inside it.",
                "next_step": "Keep the lane narrow, honor the signal that is still alive, and do not overspend it.",
            },
            {
                "commentary": "The pressure is not small, but you have not gone numb inside it.",
                "next_step": "Use that remaining openness carefully and spend it where truth can actually land.",
            },
            {
                "commentary": "You are carrying weight without fully closing around it.",
                "next_step": "Protect the living center of the day and refuse tasks that would flatten it.",
            },
        ],
    },
    "RESTORATIVE_RECOVERY": {
        "sprite_id": 12,
        "tone": "gentle",
        "why": "Selected when a genuinely restorative block or place has altered the shape of the day.",
        "variants": [
            {
                "commentary": "A real restorative pocket showed up today. Let it count.",
                "next_step": "Do not spend the recovery twice. Keep the rest of the day simple.",
            },
            {
                "commentary": "Something in today actually gave back instead of only taking.",
                "next_step": "Hold the gain gently and avoid crowding it out with unnecessary demand.",
            },
            {
                "commentary": "The day found a pocket of oxygen.",
                "next_step": "Protect what restored you and let the rest of the day stay modest.",
            },
        ],
    },
    "EVENING_UNPROTECTED": {
        "sprite_id": 11,
        "tone": "firm",
        "why": "Selected when evening has too little protected home space to let the day settle properly.",
        "variants": [
            {
                "commentary": "The day is still leaking into the night.",
                "next_step": "End one demand, dim one screen, and create an actual landing window.",
            },
            {
                "commentary": "Night is here, but the day still has its hands on you.",
                "next_step": "Shut down one active stream and make room for an actual landing instead of a collapse.",
            },
            {
                "commentary": "You do not have an evening yet. You still have runoff.",
                "next_step": "Create a protected pocket at home before the night gets spent by momentum alone.",
            },
        ],
    },
    "CLOSED_UNDER_LOAD": {
        "sprite_id": 11,
        "tone": "firm",
        "why": "Selected when high load is pairing with low steadiness, suggesting bracing rather than simple fatigue.",
        "variants": [
            {
                "commentary": "This looks tighter than tired. You are bracing, not just low.",
                "next_step": "Reduce one pressure source and choose one small act that reopens you a notch.",
            },
            {
                "commentary": "The strain is not only energy loss. It is contraction.",
                "next_step": "Stop one pressure input and make one choice that softens your grip on the day.",
            },
            {
                "commentary": "You look armored, not merely depleted.",
                "next_step": "Name the pressure you are bracing against and answer it with one act of release.",
            },
        ],
    },
    "FOG_UNDEFINED": {
        "sprite_id": 2,
        "tone": "gentle",
        "why": "Selected when the signal is too blurred to support strong direction or settled intent.",
        "variants": [
            {
                "commentary": "Say the actual thing. What matters today?",
                "next_step": "Write one sentence of intent before the next distraction wins.",
            },
            {
                "commentary": "The day is asking for a real sentence, not another vague swirl.",
                "next_step": "Name the actual priority in plain language and let that become the next move.",
            },
            {
                "commentary": "This is fog, not mystery.",
                "next_step": "Reduce the blur by stating one honest aim and one thing you will not feed today.",
            },
        ],
    },
}

AVOIDANCE_VECTORS = {"escapism", "doomscroll", "numbness"}
PRESSURE_VECTORS = {"control", "irritability"}


class PneumaTelemetry(BaseModel):
    mood: int | None = Field(default=None, ge=1, le=5)
    clarity: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    vector: str = "other"
    note: str = ""
    ts: str | None = None


class BodyTelemetry(BaseModel):
    sleep_hours: float | None = Field(default=None, ge=0)
    sleep_regularity: float | None = Field(default=None, ge=0)
    resting_hr: float | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    sedentary_streak_min: int | None = Field(default=None, ge=0)


class AttentionTelemetry(BaseModel):
    screen_total_min: int | None = Field(default=None, ge=0)
    screen_work_min: int | None = Field(default=None, ge=0)
    screen_entertainment_min: int | None = Field(default=None, ge=0)
    screen_social_min: int | None = Field(default=None, ge=0)
    unlocks_per_hour: float | None = Field(default=None, ge=0)
    late_night_screen_min: int | None = Field(default=None, ge=0)
    active_notification_count: int | None = Field(default=None, ge=0)


class ContextTelemetry(BaseModel):
    meetings_count: int | None = Field(default=None, ge=0)
    busy_minutes: int | None = Field(default=None, ge=0)
    home_media_min: int | None = Field(default=None, ge=0)


class CommitmentsTelemetry(BaseModel):
    top_tasks: list[str] = Field(default_factory=list)
    stop_doing: str = ""
    bedtime_target: str = ""


class BehavioralTelemetry(BaseModel):
    first_departure_time: str | None = None
    away_place_changes_today: int | None = Field(default=None, ge=0)
    evening_away_minutes: float | None = Field(default=None, ge=0)
    evening_home_minutes: float | None = Field(default=None, ge=0)
    evening_home_protection_minutes: float | None = Field(default=None, ge=0)
    out_of_house_fragmentation_load_score: float | None = Field(default=None, ge=0, le=100)
    evening_home_protection_score: float | None = Field(default=None, ge=0, le=100)
    app_switches_today: int | None = Field(default=None, ge=0)
    unique_apps_today: int | None = Field(default=None, ge=0)
    longest_single_app_streak_minutes: float | None = Field(default=None, ge=0)
    app_switches_per_hour: float | None = Field(default=None, ge=0)
    app_context_switch_load_score: float | None = Field(default=None, ge=0, le=100)
    wind_down_charge_consistency_score: float | None = Field(default=None, ge=0, le=100)
    longest_still_block_workday_minutes: float | None = Field(default=None, ge=0)
    post_midday_movement_minutes: float | None = Field(default=None, ge=0)
    driving_transit_minutes_today: float | None = Field(default=None, ge=0)
    activity_transitions_today: int | None = Field(default=None, ge=0)
    activity_pattern_load_score: float | None = Field(default=None, ge=0, le=100)
    music_supported_focus_minutes_today: float | None = Field(default=None, ge=0)
    longest_music_supported_focus_block_minutes: float | None = Field(default=None, ge=0)
    music_supported_focus_score: float | None = Field(default=None, ge=0, le=100)
    morning_pickup_delay_minutes: float | None = Field(default=None, ge=0)
    morning_pickup_delay_score: float | None = Field(default=None, ge=0, le=100)
    night_disruption_events: int | None = Field(default=None, ge=0)
    night_disruption_load_score: float | None = Field(default=None, ge=0, le=100)
    notification_spike_count: int | None = Field(default=None, ge=0)
    longest_notification_recovery_lag_minutes: float | None = Field(default=None, ge=0)
    notification_recovery_load_score: float | None = Field(default=None, ge=0, le=100)
    restorative_place_minutes_today: float | None = Field(default=None, ge=0)
    restorative_place_labels_today: str = ""
    restorative_place_score: float | None = Field(default=None, ge=0, le=100)
    hrv_relative_score: float | None = Field(default=None, ge=0, le=100)


class TodayTelemetry(BaseModel):
    date: str
    time_of_day: str
    pneuma: PneumaTelemetry = Field(default_factory=PneumaTelemetry)
    body: BodyTelemetry = Field(default_factory=BodyTelemetry)
    attention: AttentionTelemetry = Field(default_factory=AttentionTelemetry)
    context: ContextTelemetry = Field(default_factory=ContextTelemetry)
    commitments: CommitmentsTelemetry = Field(default_factory=CommitmentsTelemetry)
    behavioral: BehavioralTelemetry = Field(default_factory=BehavioralTelemetry)


class IndexOutput(BaseModel):
    mode: str
    sprite_id: int
    tone: str
    commentary: str
    next_step: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    dialogue_variant: int = Field(default=1, ge=1)


def _parse_percentish(value: Any) -> int | None:
    try:
        if value in {None, "", "unknown", "unavailable", "none"}:
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score_1_to_5(value: float | None) -> float | None:
    if value is None:
        return None
    return _clamp(((value - 1) / 4) * 100)


def _inverse_1_to_5(value: float | None) -> float | None:
    score = _score_1_to_5(value)
    if score is None:
        return None
    return 100 - score


def _sleep_hours_score(hours: float | None) -> float | None:
    if hours is None:
        return None
    if hours < 5:
        return 10
    if hours < 6:
        return 30
    if hours < 7:
        return 55
    if hours < 8:
        return 80
    return 100


def _sleep_regularity_score(variance_minutes: float | None) -> float | None:
    if variance_minutes is None:
        return None
    if variance_minutes <= 20:
        return 92
    if variance_minutes <= 40:
        return 78
    if variance_minutes <= 75:
        return 58
    if variance_minutes <= 120:
        return 36
    return 18


def _resting_hr_score(resting_hr: float | None) -> float | None:
    if resting_hr is None:
        return None
    if resting_hr < 58:
        return 90
    if resting_hr < 64:
        return 75
    if resting_hr < 70:
        return 60
    if resting_hr < 76:
        return 40
    return 20


def _late_night_screen_score(minutes: int | None) -> float | None:
    if minutes is None:
        return None
    if minutes <= 15:
        return 92
    if minutes <= 45:
        return 72
    if minutes <= 90:
        return 46
    return 20


def _unlock_focus_score(unlocks_per_hour: float | None) -> float | None:
    if unlocks_per_hour is None:
        return None
    if unlocks_per_hour <= 2:
        return 92
    if unlocks_per_hour <= 5:
        return 72
    if unlocks_per_hour <= 9:
        return 48
    return 22


def _vector_focus_score(vector: str) -> float | None:
    if not vector:
        return None
    if vector in AVOIDANCE_VECTORS:
        return 22
    if vector in PRESSURE_VECTORS:
        return 42
    return 64


def _steps_momentum_score(steps: int | None) -> float | None:
    if steps is None:
        return None
    if steps < 1500:
        return 15
    if steps < 3500:
        return 35
    if steps < 6000:
        return 60
    if steps < 9000:
        return 80
    return 95


def _sedentary_momentum_score(minutes: int | None) -> float | None:
    if minutes is None:
        return None
    if minutes <= 45:
        return 92
    if minutes <= 90:
        return 72
    if minutes <= 150:
        return 44
    return 18


def _intent_presence_score(top_tasks: list[str], stop_doing: str) -> float | None:
    cleaned = [task.strip() for task in top_tasks if task and task.strip()]
    if cleaned:
        return 92 if len(cleaned) <= 3 else 70
    if stop_doing.strip():
        return 65
    return None


def _pressure_context_score(meetings: int | None, busy_minutes: int | None) -> float | None:
    values: list[float] = []
    if meetings is not None:
        if meetings <= 1:
            values.append(18)
        elif meetings <= 3:
            values.append(42)
        elif meetings <= 5:
            values.append(68)
        else:
            values.append(86)
    if busy_minutes is not None:
        if busy_minutes <= 60:
            values.append(18)
        elif busy_minutes <= 180:
            values.append(42)
        elif busy_minutes <= 300:
            values.append(66)
        else:
            values.append(84)
    if not values:
        return None
    return sum(values) / len(values)


def _weighted_average(components: list[tuple[str, float | None, float]]) -> tuple[int, float, dict[str, float]]:
    total = 0.0
    used_weight = 0.0
    used_components: dict[str, float] = {}
    possible_weight = sum(weight for _, _, weight in components)

    for name, score, weight in components:
        if score is None:
            continue
        total += score * weight
        used_weight += weight
        used_components[name] = round(score, 1)

    if used_weight <= 0 or possible_weight <= 0:
        return 50, 0.0, used_components

    score = round(total / used_weight)
    confidence = round(used_weight / possible_weight, 2)
    return int(score), confidence, used_components


def _canonical_vector(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in {"escapism", "doomscroll", "control", "irritability", "numbness", "other"}:
        return value
    mapping = {
        "distraction": "doomscroll",
        "temptation": "escapism",
        "discouragement": "numbness",
        "conflict": "irritability",
        "uncertainty": "control",
        "overstimulation": "doomscroll",
        "work overload": "control",
        "poor sleep": "other",
        "no clear drag": "other",
    }
    return mapping.get(value, "other")


def _score_tone(value: int) -> str:
    if value >= 75:
        return "good"
    if value >= 50:
        return "warn"
    return "bad"


def _pneuma_score_payload(card: dict[str, Any], fallback: int) -> dict[str, Any]:
    value = _parse_percentish(card.get("value"))
    raw_value = _parse_percentish(card.get("raw_value"))
    confidence_raw = _parse_percentish(card.get("confidence"))
    confidence = round((confidence_raw or 0) / 100, 2)
    score = fallback if value is None else value
    tone = str(card.get("tone") or _score_tone(score))
    return {
        "value": score,
        "raw_value": raw_value if raw_value is not None else score,
        "known": value is not None,
        "confidence": confidence,
        "tone": tone,
        "components": card.get("breakdown") or [],
        "trend": card.get("trend"),
    }


def _capacity_phrase(score: int) -> str:
    if score >= 80:
        return "capacity is strong"
    if score >= 65:
        return "capacity is workable"
    if score >= 50:
        return "capacity is limited"
    return "capacity is thin"


def _alignment_phrase(score: int) -> str:
    if score >= 80:
        return "alignment is crisp"
    if score >= 65:
        return "alignment is steady"
    if score >= 50:
        return "alignment is mixed"
    return "alignment is blurred"


def _load_phrase(score: int) -> str:
    if score <= 35:
        return "load is light"
    if score <= 50:
        return "load is manageable"
    if score <= 68:
        return "load is elevated"
    return "load is heavy"


def _responsiveness_phrase(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 80:
        return "steadiness is gathered"
    if score >= 65:
        return "steadiness is intact"
    if score >= 50:
        return "steadiness is mixed"
    return "steadiness is scattered"


def _score_summary(
    capacity: int,
    alignment: int,
    load: int,
    responsiveness: int | None,
) -> str:
    parts = [
        _capacity_phrase(capacity),
        _alignment_phrase(alignment),
        _load_phrase(load),
    ]
    responsiveness_phrase = _responsiveness_phrase(responsiveness)
    if responsiveness_phrase:
        parts.append(responsiveness_phrase)

    if not parts:
        return ""
    if len(parts) == 1:
        sentence = parts[0]
    elif len(parts) == 2:
        sentence = f"{parts[0]} and {parts[1]}"
    else:
        sentence = f"{', '.join(parts[:-1])}, and {parts[-1]}"
    return sentence[:1].upper() + sentence[1:] + "."


def _mode_label(mode: str) -> str:
    return mode.replace("_", " ").title()


def _dialogue_variant_index(
    mode: str,
    telemetry: TodayTelemetry,
    flags: list[dict[str, Any]] | None,
    variants_count: int,
) -> int:
    if variants_count <= 1:
        return 0
    seed_parts = [telemetry.date, telemetry.time_of_day, mode]
    seed_parts.extend(flag["id"] for flag in (flags or [])[:2])
    if telemetry.commitments.top_tasks:
        seed_parts.append(telemetry.commitments.top_tasks[0].strip().lower())
    seed = "|".join(part for part in seed_parts if part)
    return zlib.adler32(seed.encode("utf-8")) % variants_count


def _selection_tags(mode: str, tone: str, flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    line = MODE_LINES[mode]
    tags = [
        {
            "label": _mode_label(mode),
            "tone": tone,
            "explanation": line.get("why") or "This is the main pattern Index matched for the current day shape.",
        }
    ]
    for flag in flags[:4]:
        tags.append(
            {
                "label": flag["label"],
                "tone": flag["tone"],
                "explanation": flag["detail"],
            }
        )
    return tags


def _flag(
    flag_id: str,
    label: str,
    tone: str,
    detail: str,
    priority: int,
) -> dict[str, Any]:
    return {
        "id": flag_id,
        "label": label,
        "tone": tone,
        "detail": detail,
        "priority": priority,
    }


def _behavioral_flags(
    telemetry: TodayTelemetry,
    capacity: int,
    alignment: int,
    load: int,
    responsiveness: int | None,
) -> list[dict[str, Any]]:
    behavior = telemetry.behavioral
    time_of_day = telemetry.time_of_day
    steps = telemetry.body.steps or 0
    late_night = telemetry.attention.late_night_screen_min or 0
    has_intent = bool([task for task in telemetry.commitments.top_tasks if task.strip()])
    flags: list[dict[str, Any]] = []

    if (
        time_of_day in {"evening", "night"}
        and (behavior.evening_away_minutes or 0) >= 300
        and (behavior.evening_home_minutes or 0) <= 45
    ):
        flags.append(
            _flag(
                "out_all_day",
                "Out all day",
                "warn",
                "You have been away most of the day with almost no home landing yet.",
                92,
            )
        )

    if (
        steps <= 1200
        and (behavior.post_midday_movement_minutes or 0) <= 10
        and (behavior.longest_still_block_workday_minutes or 0) >= 180
    ):
        flags.append(
            _flag(
                "no_real_movement",
                "Barely moved",
                "bad",
                "Movement has been close to zero and stillness has owned the day.",
                98,
            )
        )

    if (
        (behavior.app_context_switch_load_score or 0) >= 70
        or (behavior.app_switches_per_hour or 0) >= 8.5
    ):
        flags.append(
            _flag(
                "context_shredding",
                "Attention shredded",
                "bad",
                "App switching is high enough that your attention is getting chopped into fragments.",
                94,
            )
        )

    if (behavior.night_disruption_load_score or 0) >= 70 or late_night >= 75:
        flags.append(
            _flag(
                "night_blowback",
                "Night blowback",
                "warn",
                "The night carried enough disruption to make the day more expensive.",
                95,
            )
        )

    if time_of_day in {"evening", "night"} and (behavior.evening_home_protection_score or 100) <= 35:
        flags.append(
            _flag(
                "evening_unprotected",
                "No landing window",
                "warn",
                "There has not been a real protected stretch at home for the evening to settle.",
                85,
            )
        )

    if responsiveness is not None and responsiveness >= 70 and load >= 60:
        flags.append(
            _flag(
                "responsive_under_load",
                "Steady under load",
                "good",
                "Load is real, but the system is still returning toward baseline instead of locking up.",
                76,
            )
        )

    if responsiveness is not None and responsiveness <= 40 and load >= 60:
        flags.append(
            _flag(
                "closed_under_load",
                "Scattered under load",
                "bad",
                "Load is high and steadiness looks scattered, not just tired.",
                88,
            )
        )

    if (
        (behavior.restorative_place_score or 0) >= 80
        or (
            (behavior.music_supported_focus_score or 0) >= 75
            and (behavior.longest_music_supported_focus_block_minutes or 0) >= 40
        )
    ):
        flags.append(
            _flag(
                "restorative_block",
                "Restorative block",
                "good",
                "A real restorative or settled block showed up today. It is worth protecting.",
                68,
            )
        )

    if (
        (behavior.wind_down_charge_consistency_score or 100) <= 35
        and late_night >= 45
    ):
        flags.append(
            _flag(
                "wind_down_drift",
                "Late wind-down drift",
                "warn",
                "Your landing rhythm drifted late enough that tomorrow will probably feel it too.",
                70,
            )
        )

    if (
        capacity < 60
        and alignment >= 60
        and (behavior.morning_pickup_delay_score or 0) >= 80
    ):
        flags.append(
            _flag(
                "slow_start_protected",
                "Slow start protected",
                "good",
                "You gave the morning some space instead of grabbing the phone immediately.",
                62,
            )
        )

    if (
        capacity >= 60
        and alignment < 50
        and load <= 62
        and (responsiveness is None or responsiveness >= 50)
        and (
            not has_intent
            or (behavior.app_context_switch_load_score or 0) >= 58
        )
    ):
        flags.append(
            _flag(
                "able_but_misaligned",
                "Able but misaligned",
                "warn",
                "Capacity is workable, but your direction is lagging behind what the day could actually carry.",
                84,
            )
        )

    return sorted(flags, key=lambda item: item["priority"], reverse=True)


def _missing_inputs(telemetry: TodayTelemetry) -> list[str]:
    missing: list[str] = []
    checks = {
        "pneuma.mood": telemetry.pneuma.mood,
        "pneuma.clarity": telemetry.pneuma.clarity,
        "pneuma.stress": telemetry.pneuma.stress,
        "body.sleep_hours": telemetry.body.sleep_hours,
        "body.resting_hr": telemetry.body.resting_hr,
        "body.steps": telemetry.body.steps,
        "body.sedentary_streak_min": telemetry.body.sedentary_streak_min,
        "attention.unlocks_per_hour": telemetry.attention.unlocks_per_hour,
        "attention.late_night_screen_min": telemetry.attention.late_night_screen_min,
        "context.meetings_count": telemetry.context.meetings_count,
        "context.busy_minutes": telemetry.context.busy_minutes,
    }
    for label, value in checks.items():
        if value is None:
            missing.append(label)
    if not [task for task in telemetry.commitments.top_tasks if task.strip()] and not telemetry.commitments.stop_doing.strip():
        missing.append("commitments.top_tasks")
    return missing


def _index_output(
    mode: str,
    confidence: float,
    telemetry: TodayTelemetry,
    flags: list[dict[str, Any]] | None = None,
) -> IndexOutput:
    line = MODE_LINES[mode]
    variants = line.get("variants") or [
        {
            "commentary": line.get("commentary", ""),
            "next_step": line.get("next_step", ""),
        }
    ]
    variant_index = _dialogue_variant_index(mode, telemetry, flags, len(variants))
    variant = variants[variant_index]
    return IndexOutput(
        mode=mode,
        sprite_id=line["sprite_id"],
        tone=line["tone"],
        commentary=str(variant.get("commentary", ""))[:140],
        next_step=str(variant.get("next_step", ""))[:140],
        confidence=round(max(0.0, min(confidence, 1.0)), 2),
        dialogue_variant=variant_index + 1,
    )


def _select_mode(
    telemetry: TodayTelemetry,
    capacity: int,
    alignment: int,
    load: int,
    pressure: float | None,
    responsiveness: int | None = None,
    flags: list[dict[str, Any]] | None = None,
    status: str | None = None,
) -> tuple[str, list[str]]:
    vector = _canonical_vector(telemetry.pneuma.vector)
    clarity = telemetry.pneuma.clarity or 0
    stress = telemetry.pneuma.stress or 0
    steps = telemetry.body.steps or 0
    late_night = telemetry.attention.late_night_screen_min or 0
    sedentary = telemetry.body.sedentary_streak_min or 0
    meetings = telemetry.context.meetings_count or 0
    busy_minutes = telemetry.context.busy_minutes or 0
    has_intent = bool([task for task in telemetry.commitments.top_tasks if task.strip()])
    has_note = bool(telemetry.pneuma.note.strip())
    flag_ids = {flag["id"] for flag in (flags or [])}
    rules: list[str] = []

    if capacity >= 74 and alignment >= 74 and load <= 38 and responsiveness is not None and responsiveness >= 72:
        rules.append("scores_clear_responsive")
        return "CLEAR_RESPONSIVE", rules

    if "no_real_movement" in flag_ids:
        rules.append("behavior_no_real_movement")
        return "STUCK_SEDENTARY", rules

    if "night_blowback" in flag_ids and (capacity < 75 or load >= 52):
        rules.append("behavior_night_blowback")
        return "NIGHT_BLOWBACK", rules

    if "context_shredding" in flag_ids and (alignment < 72 or load >= 58):
        rules.append("behavior_context_shredding")
        return "CONTEXT_SHREDDING", rules

    if "out_all_day" in flag_ids:
        rules.append("behavior_out_all_day")
        return "OUT_ALL_DAY", rules

    if "closed_under_load" in flag_ids:
        rules.append("behavior_closed_under_load")
        return "CLOSED_UNDER_LOAD", rules

    if "responsive_under_load" in flag_ids:
        rules.append("behavior_responsive_under_load")
        return "RESPONSIVE_UNDER_LOAD", rules

    if "restorative_block" in flag_ids and (capacity < 68 or load >= 55):
        rules.append("behavior_restorative_block")
        return "RESTORATIVE_RECOVERY", rules

    if "evening_unprotected" in flag_ids:
        rules.append("behavior_evening_unprotected")
        return "EVENING_UNPROTECTED", rules

    if status == "Able but Misaligned" or "able_but_misaligned" in flag_ids:
        rules.append("pneuma_able_but_misaligned")
        return "ABLE_MISALIGNED", rules

    if capacity >= 74 and alignment >= 70 and load <= 42:
        rules.append("scores_clear_and_advancing")
        return "CLEAR_ADVANCING", rules

    if status == "Pressured but Holding" or (alignment >= 60 and capacity < 62 and load >= 58):
        rules.append("pneuma_pressured_but_holding")
        return "FOCUSED_OVERDRAWN", rules

    if alignment < 45 and vector in AVOIDANCE_VECTORS and late_night >= 45:
        rules.append("avoidance_vector_with_late_night")
        return "AVOIDANCE_SPIRAL", rules

    if alignment < 55 and load >= 52 and (late_night >= 60 or vector == "doomscroll"):
        rules.append("fragmented_attention_pattern")
        return "NOISY_LEAKING", rules

    if (steps < 2500 or sedentary >= 120) and capacity < 62 and load >= 50:
        rules.append("low_movement_low_capacity")
        return "STUCK_SEDENTARY", rules

    if (
        status == "Depleted / Under Pressure"
        or stress >= 4
        or meetings >= 5
        or busy_minutes >= 300
        or load >= 68
        or (pressure is not None and pressure >= 64)
    ) and capacity < 70:
        rules.append("pressure_context")
        return "HEAVY_LOAD", rules

    if capacity < 48:
        rules.append("capacity_below_threshold")
        return "RECOVERY_DAY", rules

    if alignment < 52 and clarity <= 2 and not has_intent and not has_note:
        rules.append("low_clarity_undefined_intent")
        return "FOG_UNDEFINED", rules

    if alignment < 57 and load >= 52:
        rules.append("blurred_default")
        return "FOG_UNDEFINED", rules

    rules.append("fallback_recovery_guard")
    return "RECOVERY_DAY", rules


def _estimated_pneuma_scores(telemetry: TodayTelemetry) -> dict[str, Any]:
    vector = _canonical_vector(telemetry.pneuma.vector)
    top_tasks = [task.strip() for task in telemetry.commitments.top_tasks if task and task.strip()]

    capacity, capacity_conf, capacity_components = _weighted_average(
        [
            ("sleep_hours", _sleep_hours_score(telemetry.body.sleep_hours), 0.34),
            ("sleep_regularity", _sleep_regularity_score(telemetry.body.sleep_regularity), 0.14),
            ("resting_hr", _resting_hr_score(telemetry.body.resting_hr), 0.14),
            ("stress_inverse", _inverse_1_to_5(telemetry.pneuma.stress), 0.18),
            ("mood", _score_1_to_5(telemetry.pneuma.mood), 0.10),
            ("bedtime_target", 78 if telemetry.commitments.bedtime_target.strip() else None, 0.10),
        ]
    )

    alignment, alignment_conf, alignment_components = _weighted_average(
        [
            ("clarity", _score_1_to_5(telemetry.pneuma.clarity), 0.30),
            ("stress_inverse", _inverse_1_to_5(telemetry.pneuma.stress), 0.14),
            ("vector", _vector_focus_score(vector), 0.16),
            ("late_night_screen", _late_night_screen_score(telemetry.attention.late_night_screen_min), 0.10),
            ("unlocks", _unlock_focus_score(telemetry.attention.unlocks_per_hour), 0.08),
            ("intent_presence", _intent_presence_score(top_tasks, telemetry.commitments.stop_doing), 0.06),
        ]
    )

    load_inverse, load_conf, load_components = _weighted_average(
        [
            ("stress_inverse", _inverse_1_to_5(telemetry.pneuma.stress), 0.20),
            ("late_night_screen", _late_night_screen_score(telemetry.attention.late_night_screen_min), 0.14),
            ("steps", _steps_momentum_score(telemetry.body.steps), 0.18),
            ("sedentary", _sedentary_momentum_score(telemetry.body.sedentary_streak_min), 0.14),
            ("resting_hr", _resting_hr_score(telemetry.body.resting_hr), 0.10),
            ("sleep_hours", _sleep_hours_score(telemetry.body.sleep_hours), 0.08),
        ]
    )
    load = max(0, min(100, 100 - load_inverse))
    load_components = {name: round(100 - score, 1) for name, score in load_components.items()}

    return {
        "capacity": {
            "value": capacity,
            "confidence": capacity_conf,
            "tone": _score_tone(capacity),
            "components": capacity_components,
            "trend": None,
        },
        "alignment": {
            "value": alignment,
            "confidence": alignment_conf,
            "tone": _score_tone(alignment),
            "components": alignment_components,
            "trend": None,
        },
        "load": {
            "value": load,
            "confidence": load_conf,
            "tone": _score_tone(100 - load),
            "components": load_components,
            "trend": None,
        },
        "status": None,
    }


def build_index_snapshot(
    telemetry: TodayTelemetry,
    pneuma_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pressure = _pressure_context_score(
        telemetry.context.meetings_count,
        telemetry.context.busy_minutes,
    )

    if pneuma_scores:
        capacity_data = _pneuma_score_payload(pneuma_scores.get("capacity") or {}, 50)
        alignment_data = _pneuma_score_payload(pneuma_scores.get("alignment") or {}, 50)
        load_data = _pneuma_score_payload(pneuma_scores.get("load") or {}, 50)
        steadiness_data = _pneuma_score_payload(
            (pneuma_scores.get("steadiness") or pneuma_scores.get("responsiveness") or pneuma_scores.get("resonance") or {}),
            50,
        )
        status = pneuma_scores.get("status")
    else:
        estimated = _estimated_pneuma_scores(telemetry)
        capacity_data = estimated["capacity"]
        alignment_data = estimated["alignment"]
        load_data = estimated["load"]
        steadiness_data = {
            "value": 50,
            "known": False,
            "confidence": 0.0,
            "tone": "warn",
            "components": [],
            "trend": None,
        }
        status = estimated["status"]

    if not steadiness_data.get("known"):
        steadiness_data["value"] = None

    capacity = capacity_data["value"]
    alignment = alignment_data["value"]
    load = load_data.get("raw_value", load_data["value"])
    responsiveness = steadiness_data["value"] if steadiness_data.get("known") else None
    flags = _behavioral_flags(telemetry, capacity, alignment, load, responsiveness)
    mode, rule_hits = _select_mode(
        telemetry,
        capacity,
        alignment,
        load,
        pressure,
        responsiveness,
        flags,
        status,
    )
    confidence_parts = [
        capacity_data["confidence"],
        alignment_data["confidence"],
        load_data["confidence"],
    ]
    if steadiness_data.get("known"):
        confidence_parts.append(steadiness_data["confidence"])
    confidence = round(sum(confidence_parts) / len(confidence_parts), 2)
    output = _index_output(mode, confidence, telemetry, flags)
    selection_tags = _selection_tags(mode, output.tone, flags)

    return {
        "available": confidence > 0,
        "date": telemetry.date,
        "time_of_day": telemetry.time_of_day,
        "mode": output.mode,
        "sprite_id": output.sprite_id,
        "tone": output.tone,
        "commentary": output.commentary,
        "next_step": output.next_step,
        "confidence": output.confidence,
        "dialogue_variant": output.dialogue_variant,
        "capacity_score": capacity,
        "alignment_score": alignment,
        "load_score": load,
        "steadiness_score": responsiveness,
        "responsiveness_score": responsiveness,
        "pneuma_status": status,
        "score_summary": _score_summary(capacity, alignment, load, responsiveness),
        "trigger_detail": flags[0]["detail"] if flags else None,
        "flags": [{key: flag[key] for key in ("id", "label", "tone", "detail")} for flag in flags[:4]],
        "selection_tags": selection_tags,
        "scores": {
            "capacity": capacity_data,
            "alignment": alignment_data,
            "load": load_data,
            "steadiness": steadiness_data,
            "responsiveness": steadiness_data,
        },
        "pressure_score": round(pressure, 1) if pressure is not None else None,
        "rule_hits": rule_hits,
        "missing_inputs": _missing_inputs(telemetry),
        "telemetry": telemetry.model_dump(mode="json"),
    }
