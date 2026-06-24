from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Header, HTTPException
import subprocess
from pathlib import Path
from datetime import date, datetime, timedelta
from urllib.parse import quote
import json
import sqlite3
import re
import random
import math
import shlex

import os
import requests
from zoneinfo import ZoneInfo
from functools import lru_cache
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from index_runtime import TodayTelemetry, build_index_snapshot


app = FastAPI()
templates = Jinja2Templates(directory="templates")

LOG_DIR = Path("/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
HA_DB_PATH = Path(
    os.getenv("HA_DB_PATH", "/demo/homeassistant/home-assistant_v2.db")
)
HA_RESTORE_STATE_PATH = Path(
    os.getenv("HA_RESTORE_STATE_PATH", "/demo/homeassistant/.storage/core.restore_state")
)

ATELIER_MAC = "DEMO_TARGET_MAC"

MUSIC_PLAYLIST = "{playlist_url}"
VIDEO_PLAYLIST = "{playlist_url2}"

MUSIC_OUT = "/demo/media/music/Abiding Moments/%(title)s.%(ext)s"
VIDEO_OUT = "/demo/media/inbox/%(title)s.%(ext)s"
MUSIC_TARGET_DIR = Path(MUSIC_OUT).parent
ABIDING_MOMENTS_TARGET_DIR = MUSIC_TARGET_DIR
ABIDING_MOMENTS_VIDEO_OUT = MUSIC_OUT
ABIDING_MOMENTS_SEARCH_SUFFIX = (os.getenv("ABIDING_MOMENTS_SEARCH_SUFFIX", "hymn") or "").strip() or "hymn"
ABIDING_MOMENTS_SEARCH_COUNT = 1

APERTURE_WIFI_ENTITY = "sensor.aperture_wi_fi_connection"
APERTURE_LOCATION_ENTITY = "sensor.aperture_geocoded_location"
APERTURE_LAST_USED_APP_ENTITY = "sensor.aperture_last_used_app"
APERTURE_ACTIVITY_ENTITY = "sensor.aperture_detected_activity"
APERTURE_NOTIFICATIONS_ENTITY = "sensor.aperture_active_notification_count"
APERTURE_INTERACTIVE_ENTITY = "binary_sensor.aperture_interactive"
APERTURE_MUSIC_ENTITY = "binary_sensor.aperture_music_active"
APERTURE_CHARGING_ENTITY = "binary_sensor.aperture_is_charging"
APERTURE_CHARGER_TYPE_ENTITY = "sensor.aperture_charger_type"
APERTURE_SLEEP_DURATION_ENTITY = "sensor.aperture_sleep_duration"
APERTURE_SLEEP_SEGMENT_ENTITY = "sensor.aperture_sleep_segment"
APERTURE_HRV_ENTITY = "sensor.aperture_heart_rate_variability"
UNDERCURRENT_BEDTIME_ENTITY = "sensor.undercurrent_bedtime"
UNDERCURRENT_BEDTIME_SHIFTED_ENTITY = "sensor.undercurrent_bedtime_shifted_minute"

APP_SWITCH_IGNORE = {
    "com.android.launcher",
    "com.google.android.apps.nexuslauncher",
    "com.android.systemui",
    "com.sec.android.app.launcher",
}

MOVING_ACTIVITY_STATES = {"walking", "running", "on_foot", "on_bicycle", "bicycle"}
TRANSIT_ACTIVITY_STATES = {"in_vehicle"}
STILL_ACTIVITY_STATES = {"still", "tilting"}

RESTORATIVE_WIFI_KEYWORDS = [
    "church",
    "chapel",
    "worship",
    "river_of_god",
    "ymca",
    "fitness",
    "gym",
]

RESTORATIVE_LOCATION_KEYWORDS = {
    "church": ["church", "chapel", "parish", "worship"],
    "gym": ["gym", "fitness", "ymca"],
    "outdoors": ["park", "trail", "lake", "river", "nature", "forest", "garden", "preserve"],
}

BEDTIME_24H_RE = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$")

REBUILD_TOKEN = os.getenv("AURORA_REBUILD_TOKEN", "").strip()
REBUILD_SCRIPT = os.getenv("REBUILD_SCRIPT", "").strip()

from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

def _normalize_ytdlp_input(value: str) -> str:
    return (
        (value or "")
        .strip()
        .strip("“”")
        .replace("“", "")
        .replace("”", "")
        .replace("’", "'")
    )


def _ytdlp_shell_prefix() -> str:
    return (
        "cp /demo/secrets/yt_cookies.txt /tmp/demo_yt_cookies.txt && "
        "yt-dlp --ignore-config "
        "--remote-components ejs:github "
        "--cookies /tmp/demo_yt_cookies.txt "
        '--extractor-args "youtube:player_client=mweb" '
    )


def build_ytdlp_shell_cmd(url: str, out_tmpl: str) -> str:
    url = _normalize_ytdlp_input(url)

# Single-line command:
# - copy RO secret cookies into writable /tmp
# - ignore user/global yt-dlp config to avoid conflicting cookies/settings
# - enable remote EJS components for current JS challenge solving
# - force mweb client so bgutil PO-token provider is used
# - run yt-dlp pointing at the writable cookie jar
# Notes:
# - quote -f and -o values to avoid shell globbing
# - quote URL
    return (
        f"{_ytdlp_shell_prefix()}"
        '-f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best" '
        "--merge-output-format mp4 "
        "--embed-metadata --embed-thumbnail "
        f"-o {shlex.quote(out_tmpl)} "
        f"{shlex.quote(url)}"
    )


def build_ytdlp_search_shell_cmd(query: str, out_tmpl: str, *, count: int) -> str:
    clean_query = _normalize_ytdlp_input(query)
    clean_count = max(1, min(int(count), 10))
    search_target = f"ytsearch{clean_count}:{clean_query}"

    return (
        f"{_ytdlp_shell_prefix()}"
        "--no-playlist "
        '-f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best" '
        "--merge-output-format mp4 "
        "--embed-metadata --embed-thumbnail "
        f"-o {shlex.quote(out_tmpl)} "
        f"{shlex.quote(search_target)}"
    )

from typing import Any, Union

def run_and_log(cmd: Union[list[str], str], log_name: str) -> tuple[int, str]:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = LOG_DIR / f"{log_name}_{ts}.log"

    with log_path.open("w", encoding="utf-8") as f:
        f.write("COMMAND:\n")
        if isinstance(cmd, list):
            f.write(" ".join(cmd) + "\n\n")
            p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
        else:
            f.write(cmd + "\n\n")
            # Run through sh -lc so we can use the single-line cp && yt-dlp flow
            p = subprocess.Popen(["sh", "-lc", cmd], stdout=f, stderr=subprocess.STDOUT, text=True)

        f.write("OUTPUT:\n")
        f.flush()
        p.wait()

    return p.returncode, log_path.name


def tail_log(filename: str, lines: int = 120) -> str:
    path = LOG_DIR / filename
    if not path.exists():
        return "(log not found)"
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


def _configured_rebuild_script() -> str:
    if not REBUILD_SCRIPT:
        raise HTTPException(
            status_code=503,
            detail="Aurora rebuild helper is disabled in this runtime.",
        )

    script_path = Path(REBUILD_SCRIPT)
    if not script_path.is_file():
        raise HTTPException(
            status_code=503,
            detail="Aurora rebuild helper is not available in this runtime.",
        )

    return str(script_path)


def _ha_states_from_restore() -> dict[str, dict[str, Any]]:
    if not HA_RESTORE_STATE_PATH.exists():
        return {}

    try:
        payload = json.loads(HA_RESTORE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    entities: dict[str, dict[str, Any]] = {}
    for item in payload.get("data", []):
        state = item.get("state") or {}
        entity_id = state.get("entity_id")
        if entity_id:
            entities[entity_id] = state
    return entities


def _ha_states_from_db(entity_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not HA_DB_PATH.exists():
        return {}

    try:
        conn = sqlite3.connect(f"file:{HA_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}

    try:
        cur = conn.cursor()
        entities: dict[str, dict[str, Any]] = {}
        query = """
            select sm.entity_id, s.state
            from states_meta sm
            join states s on s.metadata_id = sm.metadata_id
            where sm.entity_id = ?
            order by s.last_updated_ts desc
            limit 1
        """
        for entity_id in entity_ids:
            row = cur.execute(query, (entity_id,)).fetchone()
            if row:
                entities[row[0]] = {"entity_id": row[0], "state": row[1]}
        return entities
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _load_ha_entities(entity_ids: list[str]) -> dict[str, dict[str, Any]]:
    entities = _ha_states_from_db(entity_ids)
    if len(entities) >= len(entity_ids):
        return entities

    restore_entities = _ha_states_from_restore()
    for entity_id in entity_ids:
        if entity_id not in entities and entity_id in restore_entities:
            entities[entity_id] = restore_entities[entity_id]
    return entities


def _state_float(value: Any) -> float | None:
    try:
        if value in {"unknown", "unavailable", "none", "", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _known_state(value: Any) -> bool:
    return value not in {"unknown", "unavailable", "none", "", None}


def _score_tone(score: float | None, *, inverse: bool = False) -> str:
    if score is None:
        return "neutral"

    if inverse:
        if score <= 35:
            return "good"
        if score <= 65:
            return "warn"
        return "bad"

    if score >= 80:
        return "good"
    if score >= 60:
        return "warn"
    return "bad"


def _confidence_tone(confidence: float | None) -> str:
    if confidence is None:
        return "neutral"
    if confidence >= 80:
        return "good"
    if confidence >= 50:
        return "warn"
    return "bad"


def _status_tone(status: str, known: bool) -> str:
    if not known:
        return "neutral"

    good_states = {"Strong / Stable"}
    bad_states = {"Depleted / Under Pressure"}
    warn_states = {
        "Pressured but Holding",
        "Running Thin",
        "Drifting",
        "Able but Misaligned",
        "Mixed / Watch",
    }

    if status in good_states:
        return "good"
    if status in bad_states:
        return "bad"
    if status in warn_states:
        return "warn"
    return "neutral"


def _pneuma_card(
    entities: dict[str, dict[str, Any]],
    score_entity: str,
    confidence_entity: str | None = None,
    *,
    inverse: bool = False,
    display_transform: Any = None,
) -> dict[str, Any]:
    score_state = (entities.get(score_entity) or {}).get("state", "unknown")
    score_known = score_state not in {"unknown", "unavailable", "none", "", None}
    score_value = _state_float(score_state)
    display_value = display_transform(score_value) if display_transform else score_value
    if score_known and display_value is not None:
        display_state = score_state if display_transform is None else str(int(round(display_value)))
    else:
        display_state = "--"

    confidence_state = None
    confidence_known = False
    confidence_value = None
    if confidence_entity:
        confidence_state = (entities.get(confidence_entity) or {}).get("state", "unknown")
        confidence_known = confidence_state not in {"unknown", "unavailable", "none", "", None}
        confidence_value = _state_float(confidence_state)

    return {
        "value": display_state,
        "known": score_known and display_value is not None,
        "raw_value": score_value,
        "confidence": confidence_state if confidence_known else None,
        "tone": _score_tone(display_value, inverse=inverse),
        "confidence_tone": _confidence_tone(confidence_value),
    }


def _state_text(entities: dict[str, dict[str, Any]], entity_id: str) -> str:
    return str((entities.get(entity_id) or {}).get("state", "unknown"))


def _score_from_scale_1_to_5(value: float | None) -> float | None:
    if value is None:
        return None
    return (value - 1) / 4 * 100


def _capacity_sleep_hours_score(hours: float) -> float:
    if hours < 5:
        return 10
    if hours < 6:
        return 30
    if hours < 7:
        return 55
    if hours < 8:
        return 80
    return 100


def _capacity_resting_hr_score(resting: float, base: float | None) -> float:
    if base is not None and base > 0:
        delta = resting - base
        if delta <= -4:
            return 95
        if delta <= 0:
            return 85
        if delta <= 3:
            return 65
        if delta <= 6:
            return 45
        return 25
    if resting < 58:
        return 90
    if resting < 64:
        return 75
    if resting < 70:
        return 60
    if resting < 76:
        return 40
    return 20


def _load_sleep_hours_score(hours: float) -> float:
    if hours < 5:
        return 95
    if hours < 6:
        return 75
    if hours < 7:
        return 55
    if hours < 8:
        return 35
    return 20


def _load_resting_hr_score(resting: float, base: float | None) -> float:
    if base is not None and base > 0:
        delta = resting - base
        if delta <= 0:
            return 30
        if delta <= 3:
            return 55
        if delta <= 6:
            return 75
        return 90
    if resting < 58:
        return 25
    if resting < 64:
        return 40
    if resting < 70:
        return 60
    if resting < 76:
        return 78
    return 90


def _load_steps_score(steps: float) -> float:
    if steps < 1500:
        return 85
    if steps < 3500:
        return 65
    if steps < 6000:
        return 45
    if steps < 9000:
        return 30
    return 20


def _load_late_night_screen_score(minutes: float) -> float:
    if minutes <= 15:
        return 12
    if minutes <= 45:
        return 35
    if minutes <= 90:
        return 65
    return 88


def _load_busy_minutes_score(minutes: float) -> float:
    if minutes <= 60:
        return 20
    if minutes <= 180:
        return 45
    if minutes <= 300:
        return 70
    return 88


def _load_sedentary_streak_score(minutes: float) -> float:
    if minutes <= 45:
        return 18
    if minutes <= 90:
        return 40
    if minutes <= 150:
        return 68
    return 86


def _weighted_component(
    components: list[dict[str, Any]],
    *,
    label: str,
    raw: str,
    score: float | None,
    weight: float,
    trend: str = "Trend not available yet.",
    chart: dict[str, Any] | None = None,
    scoring: dict[str, Any] | None = None,
) -> None:
    if score is None:
        return
    components.append(
        {
            "label": label,
            "raw": raw,
            "score": score,
            "weight": weight,
            "weighted_score": score * weight,
            "trend": trend,
            "chart": chart,
            "scoring": scoring,
        }
    )


def _invert_chart_model(chart: dict[str, Any] | None) -> dict[str, Any] | None:
    if not chart:
        return None

    height = 56.0
    points = []
    for point in str(chart.get("points", "")).split():
        if "," not in point:
            continue
        x_text, y_text = point.split(",", 1)
        try:
            x = float(x_text)
            y = float(y_text)
        except ValueError:
            continue
        points.append(f"{round(x, 2)},{round(height - y, 2)}")

    latest_y = chart.get("latest_y")
    try:
        latest_y = round(height - float(latest_y), 2) if latest_y is not None else None
    except (TypeError, ValueError):
        latest_y = None

    oldest_value = _state_float(chart.get("oldest_display"))
    latest_value = _state_float(chart.get("latest_display"))
    inverted_oldest = _invert_percent_score(oldest_value)
    inverted_latest = _invert_percent_score(latest_value)
    min_value = _state_float(chart.get("min_display"))
    max_value = _state_float(chart.get("max_display"))
    inverted_min = _invert_percent_score(max_value)
    inverted_max = _invert_percent_score(min_value)

    out = dict(chart)
    out["points"] = " ".join(points)
    out["latest_y"] = latest_y
    if inverted_oldest is not None:
        out["oldest_display"] = round(inverted_oldest, 0)
    if inverted_latest is not None:
        out["latest_display"] = round(inverted_latest, 0)
    if inverted_min is not None:
        out["min_display"] = round(inverted_min, 0)
    if inverted_max is not None:
        out["max_display"] = round(inverted_max, 0)
    if inverted_oldest is not None and inverted_latest is not None:
        out["summary"] = _score_chart_summary(inverted_oldest, inverted_latest)
    return out


def _finalize_breakdown(
    components: list[dict[str, Any]],
    *,
    inverse: bool = False,
) -> list[dict[str, Any]]:
    total_weight = sum(item["weight"] for item in components)
    if total_weight <= 0:
        return []

    out: list[dict[str, Any]] = []
    for item in components:
        score = _invert_percent_score(item["score"]) if inverse else item["score"]
        if score is None:
            continue
        weighted_score = score * item["weight"]
        chart = _invert_chart_model(item.get("chart")) if inverse else item.get("chart")
        trend = chart["summary"] if inverse and chart else item["trend"]
        out.append(
            {
                "label": item["label"],
                "raw": item["raw"],
                "score_display": round(score, 0),
                "effective_weight": round((item["weight"] / total_weight) * 100, 0),
                "contribution": round(weighted_score / total_weight, 1),
                "trend": trend,
                "chart": chart,
                "scoring": item.get("scoring"),
            }
        )
    return out


def _history_hour_marks(hours: int = 24 * 7) -> list[datetime]:
    end = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours - 1)
    return [start + timedelta(hours=index) for index in range(hours)]


def _ha_raw_state_rows_from_db(
    entity_id: str,
    *,
    start_ts: float,
    end_ts: float | None = None,
) -> list[tuple[float, str]]:
    if not HA_DB_PATH.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{HA_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    try:
        cur = conn.cursor()
        rows: list[tuple[float, str]] = []

        before_row = cur.execute(
            """
            select s.last_updated_ts, s.state
            from states_meta sm
            join states s on s.metadata_id = sm.metadata_id
            where sm.entity_id = ?
              and s.last_updated_ts is not null
              and s.last_updated_ts < ?
            order by s.last_updated_ts desc
            limit 1
            """,
            (entity_id, start_ts),
        ).fetchone()
        if before_row:
            rows.append((float(before_row[0]), str(before_row[1])))

        upper_clause = ""
        params: list[Any] = [entity_id, start_ts]
        if end_ts is not None:
            upper_clause = "and s.last_updated_ts <= ?"
            params.append(end_ts)

        in_range_rows = cur.execute(
            f"""
            select s.last_updated_ts, s.state
            from states_meta sm
            join states s on s.metadata_id = sm.metadata_id
            where sm.entity_id = ?
              and s.last_updated_ts is not null
              and s.last_updated_ts >= ?
              {upper_clause}
            order by s.last_updated_ts asc
            """,
            tuple(params),
        ).fetchall()

        rows.extend((float(updated_ts), str(state)) for updated_ts, state in in_range_rows)
        return rows
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _ha_raw_state_history_from_db(entity_id: str, limit: int = 8) -> list[str]:
    if not HA_DB_PATH.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{HA_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            select s.state
            from states_meta sm
            join states s on s.metadata_id = sm.metadata_id
            where sm.entity_id = ?
            order by s.last_updated_ts desc
            limit ?
            """,
            (entity_id, limit),
        ).fetchall()
        values = []
        for (state,) in rows:
            if _known_state(state):
                values.append(str(state))
        return values
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _ha_state_history_from_db(entity_id: str, limit: int = 8) -> list[float]:
    values = []
    for state in _ha_raw_state_history_from_db(entity_id, limit=limit):
        parsed = _state_float(state)
        if parsed is not None:
            values.append(parsed)
    return values


def _format_numeric_value(value: float, *, decimals: int = 0, suffix: str = "") -> str:
    if decimals <= 0:
        body = f"{round(value, 0):.0f}"
    else:
        body = f"{value:.{decimals}f}"
    return f"{body}{suffix}"


def _numeric_trend_summary(
    entity_id: str,
    *,
    transform: Any = None,
    decimals: int = 0,
    suffix: str = "",
    limit: int = 8,
) -> str:
    raw_values = _ha_state_history_from_db(entity_id, limit=limit)
    values = [transform(value) if transform else value for value in raw_values]
    if len(values) < 2:
        return "Trend not available yet."

    latest = values[0]
    oldest = values[-1]
    delta = latest - oldest
    latest_text = _format_numeric_value(latest, decimals=decimals, suffix=suffix)
    oldest_text = _format_numeric_value(oldest, decimals=decimals, suffix=suffix)
    delta_text = _format_numeric_value(abs(delta), decimals=decimals, suffix=suffix)

    if abs(delta) < (0.5 if decimals <= 0 else 0.05):
        return f"Steady recently ({latest_text})."
    if delta > 0:
        return f"Up {delta_text} recently ({oldest_text} -> {latest_text})."
    return f"Down {delta_text} recently ({oldest_text} -> {latest_text})."


def _text_trend_summary(entity_id: str, limit: int = 8) -> str:
    values = _ha_raw_state_history_from_db(entity_id, limit=limit)
    if len(values) < 2:
        return "Trend not available yet."

    latest = values[0]
    oldest = values[-1]
    if latest == oldest:
        return f"Steady recently ({latest})."
    return f"Shifted recently ({oldest} -> {latest})."


def _trend_summary(entity_id: str) -> str:
    values = _ha_state_history_from_db(entity_id)
    if len(values) < 2:
        return "Trend not available yet."

    latest = values[0]
    oldest = values[-1]
    delta = latest - oldest
    if abs(delta) < 1:
        return f"Steady over recent updates ({round(latest, 0):.0f})."
    if delta > 0:
        return f"Up {round(delta, 0):.0f} over recent updates ({round(oldest, 0):.0f} -> {round(latest, 0):.0f})."
    return f"Down {round(abs(delta), 0):.0f} over recent updates ({round(oldest, 0):.0f} -> {round(latest, 0):.0f})."


def _identity_score(raw: str | None) -> float | None:
    return _state_float(raw)


def _invert_percent_score(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, 100 - value))


def _inverse_identity_score(raw: str | None) -> float | None:
    return _invert_percent_score(_state_float(raw))


def _scale_score(raw: str | None, *, inverse: bool = False) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    score = _score_from_scale_1_to_5(value)
    return (100 - score) if inverse else score


def _presence_score(raw: str | None) -> float | None:
    return 100 if _known_state(raw) else None


def _midday_drift_score(raw: str | None) -> float | None:
    if raw == "better":
        return 85
    if raw == "same":
        return 60
    if raw == "worse":
        return 30
    return None


def _load_midday_drift_score(raw: str | None) -> float | None:
    if raw == "better":
        return 20
    if raw == "same":
        return 50
    if raw == "worse":
        return 90
    return None


def _midday_need_score(raw: str | None) -> float | None:
    if not _known_state(raw):
        return None
    if "recommitment" in str(raw):
        return 55
    if any(part in str(raw) for part in ["prayer", "quiet", "conversation"]):
        return 70
    return 65


def _signal_presence_hours_score(raw: str | None) -> float | None:
    hours = _state_float(raw)
    if hours is None:
        return None
    if hours >= 2.5:
        return 100
    if hours >= 1.5:
        return 82
    if hours >= 0.75:
        return 65
    if hours > 0:
        return 45
    return 25


def _alignment_choice_score(raw: str | None) -> float | None:
    if raw == "yes":
        return 100
    if raw == "partly":
        return 60
    if raw == "no":
        return 20
    return None


def _abiding_completion_score(raw: str | None) -> float | None:
    if raw == "complete":
        return 100
    if raw == "incomplete":
        return 25
    return None


def _abiding_last_7_days_numeric_score(value: float | None) -> float | None:
    if value is None:
        return None
    days = max(0.0, float(value))
    if days >= 5.0:
        return 100.0
    return _clamp_score((days / 7.0) * 100.0)


def _abiding_last_7_days_score(raw: str | None) -> float | None:
    return _abiding_last_7_days_numeric_score(_state_float(raw))


def _main_drag_score(raw: str | None) -> float | None:
    if not _known_state(raw):
        return None
    if raw == "no clear drag":
        return 10
    if ", " in str(raw):
        return 85
    return 72


def _sleep_penalty_score(raw: str | None) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    return 100 - value


def _sleep_hours_capacity_score(raw: str | None) -> float | None:
    minutes = _state_float(raw)
    if minutes is None:
        return None
    return _capacity_sleep_hours_score(minutes / 60)


def _sleep_hours_load_score(raw: str | None) -> float | None:
    minutes = _state_float(raw)
    if minutes is None:
        return None
    return _load_sleep_hours_score(minutes / 60)


def _midday_energy_load_score(raw: str | None) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    return 100 - _score_from_scale_1_to_5(value)


def _steps_load_score(raw: str | None) -> float | None:
    steps = _state_float(raw)
    if steps is None:
        return None
    return _load_steps_score(steps)


def _late_night_screen_load_score(raw: str | None) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    return _load_late_night_screen_score(value)


def _busy_minutes_load_score(raw: str | None) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    return _load_busy_minutes_score(value)


def _work_meetings_count_load_score(raw: str | None) -> float | None:
    return _work_meetings_count_numeric_load_score(_state_float(raw))


def _work_meetings_count_numeric_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 1:
        return 12.0
    if value <= 3:
        return 38.0
    if value <= 5:
        return 68.0
    return 88.0


def _meeting_average_7d_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 1.5:
        return 18.0
    if value < 3.0:
        return 42.0
    if value < 4.5:
        return 68.0
    return 88.0


def _after_work_activity_load_score(raw: str | None) -> float | None:
    return _after_work_activity_numeric_load_score(_state_float(raw))


def _after_work_activity_numeric_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return 10.0
    if value < AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS:
        return 35.0
    if value < AFTER_WORK_BUSY_THRESHOLD_HOURS:
        return 62.0
    return 88.0


def _busy_evenings_7d_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return 15.0
    if value <= 1:
        return 35.0
    if value <= 3:
        return 68.0
    return 90.0


def _errands_appointments_load_score(raw: str | None) -> float | None:
    return _errands_appointments_numeric_load_score(_state_float(raw))


def _errands_appointments_numeric_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return 12.0
    if value <= 1:
        return 32.0
    if value <= 3:
        return 60.0
    return 82.0


def _social_commitments_load_score(raw: str | None) -> float | None:
    return _social_commitments_numeric_load_score(_state_float(raw))


def _social_commitments_numeric_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return 15.0
    if value <= 1:
        return 38.0
    if value <= 2:
        return 62.0
    return 85.0


def _sedentary_streak_load_score(raw: str | None) -> float | None:
    value = _state_float(raw)
    if value is None:
        return None
    return _load_sedentary_streak_score(value)


def _most_draining_score(raw: str | None) -> float | None:
    if raw in ["work pressure", "conflict", "fatigue", "overstimulation", "social depletion"]:
        return 85
    if raw in ["fragmented attention", "uncertainty", "lack of progress", "physical discomfort", "temptation"]:
        return 72
    if _known_state(raw):
        return 60
    return None


def _mapped_choice_score(raw: str | None, mapping: dict[str, float]) -> float | None:
    if not _known_state(raw):
        return None
    return mapping.get(str(raw))


def _undercurrent_state_shift_score(raw: str | None) -> float | None:
    return _mapped_choice_score(raw, UNDERCURRENT_STATE_SHIFT_SCORES)


def _state_shift_intensity_score(raw: str | None) -> float | None:
    return _mapped_choice_score(raw, STATE_SHIFT_INTENSITY_SCORES)


def _regulation_response_score(raw: str | None) -> float | None:
    return _mapped_choice_score(raw, REGULATION_RESPONSE_SCORES)


def _most_restorative_steadiness_score(raw: str | None) -> float | None:
    if raw in {"prayer", "scripture", "walking", "sunlight", "quiet", "rest", "worship", "journaling"}:
        return 90.0
    if raw in {"family time", "wife/family time", "music", "clean space", "meal"}:
        return 80.0
    if raw == "task completion":
        return 70.0
    if _known_state(raw):
        return 75.0
    return None


def _primary_disruptor_score(raw: str | None) -> float | None:
    if not _known_state(raw):
        return None

    values = [item.strip().lower() for item in str(raw).split(",") if item.strip()]
    if not values:
        return None

    score = 60.0
    if any(item in {"conflict", "screen", "spiritual drift"} for item in values):
        score = 35.0
    elif any(item in {"fatigue", "hurry", "uncertainty", "task load"} for item in values):
        score = 55.0
    elif any(item in {"noise", "appetite"} for item in values):
        score = 70.0

    if len(values) > 1:
        score -= min((len(values) - 1) * 10.0, 20.0)
    return max(score, 20.0)


def _primary_disruptor_load_score(raw: str | None) -> float | None:
    return _invert_percent_score(_primary_disruptor_score(raw))


def _resting_hr_capacity_score(resting_raw: str | None, base_raw: str | None) -> float | None:
    resting = _state_float(resting_raw)
    base = _state_float(base_raw)
    if resting is None:
        return None
    return _capacity_resting_hr_score(resting, base)


def _resting_hr_load_score(resting_raw: str | None, base_raw: str | None) -> float | None:
    resting = _state_float(resting_raw)
    base = _state_float(base_raw)
    if resting is None:
        return None
    return _load_resting_hr_score(resting, base)


def _score_chart_summary(first_value: float, last_value: float) -> str:
    delta = last_value - first_value
    if abs(delta) < 1:
        return f"Steady over the last 7 days ({round(last_value, 0):.0f})."
    if delta > 0:
        return (
            f"Up {round(delta, 0):.0f} over the last 7 days "
            f"({round(first_value, 0):.0f} -> {round(last_value, 0):.0f})."
        )
    return (
        f"Down {round(abs(delta), 0):.0f} over the last 7 days "
        f"({round(first_value, 0):.0f} -> {round(last_value, 0):.0f})."
    )


def _sparkline_model(series: list[float | None]) -> dict[str, Any] | None:
    known = [(index, max(0.0, min(100.0, float(value)))) for index, value in enumerate(series) if value is not None]
    if len(known) < 2:
        return None

    width = max(len(series) - 1, 1)
    height = 56

    def _point(index: int, value: float) -> tuple[float, float]:
        x = (index / width) * 100
        y = height - ((value / 100) * height)
        return round(x, 2), round(y, 2)

    points = " ".join(f"{x},{y}" for x, y in (_point(index, value) for index, value in known))
    latest_x, latest_y = _point(known[-1][0], known[-1][1])
    first_value = known[0][1]
    last_value = known[-1][1]

    return {
        "points": points,
        "latest_x": latest_x,
        "latest_y": latest_y,
        "latest_display": round(last_value, 0),
        "oldest_display": round(first_value, 0),
        "min_display": round(min(value for _, value in known), 0),
        "max_display": round(max(value for _, value in known), 0),
        "summary": _score_chart_summary(first_value, last_value),
        "window_label": "7d / hourly",
    }


def _component_score_chart(entity_id: str, mapper: Any, *, hours: int = 24 * 7) -> dict[str, Any] | None:
    marks = _history_hour_marks(hours=hours)
    start_ts = marks[0].timestamp()
    end_ts = marks[-1].timestamp()
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=start_ts, end_ts=end_ts)

    current_raw: str | None = None
    series: list[float | None] = []
    cursor = 0

    for mark in marks:
        mark_ts = mark.timestamp()
        while cursor < len(rows) and rows[cursor][0] <= mark_ts:
            raw_state = rows[cursor][1]
            if _known_state(raw_state):
                current_raw = raw_state
            cursor += 1
        series.append(mapper(current_raw))

    return _sparkline_model(series)


def _paired_component_score_chart(
    primary_entity_id: str,
    secondary_entity_id: str,
    mapper: Any,
    *,
    hours: int = 24 * 7,
) -> dict[str, Any] | None:
    marks = _history_hour_marks(hours=hours)
    start_ts = marks[0].timestamp()
    end_ts = marks[-1].timestamp()
    primary_rows = _ha_raw_state_rows_from_db(primary_entity_id, start_ts=start_ts, end_ts=end_ts)
    secondary_rows = _ha_raw_state_rows_from_db(secondary_entity_id, start_ts=start_ts, end_ts=end_ts)

    primary_raw: str | None = None
    secondary_raw: str | None = None
    primary_cursor = 0
    secondary_cursor = 0
    series: list[float | None] = []

    for mark in marks:
        mark_ts = mark.timestamp()
        while primary_cursor < len(primary_rows) and primary_rows[primary_cursor][0] <= mark_ts:
            state = primary_rows[primary_cursor][1]
            if _known_state(state):
                primary_raw = state
            primary_cursor += 1
        while secondary_cursor < len(secondary_rows) and secondary_rows[secondary_cursor][0] <= mark_ts:
            state = secondary_rows[secondary_cursor][1]
            if _known_state(state):
                secondary_raw = state
            secondary_cursor += 1
        series.append(mapper(primary_raw, secondary_raw))

    return _sparkline_model(series)


def _score_entity_chart(entity_id: str) -> dict[str, Any] | None:
    return _component_score_chart(entity_id, _identity_score)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _rubric_row(
    input_label: str,
    score_label: str,
    *,
    note: str | None = None,
    active: bool = False,
) -> dict[str, Any]:
    return {
        "input": input_label,
        "score": score_label,
        "note": note,
        "active": active,
    }


def _rubric_group(
    title: str,
    rows: list[dict[str, Any]],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "rows": rows,
        "note": note,
    }


def _component_rubric(
    score_key: str,
    label: str,
    summary: str,
    groups: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dialog_id": f"pneuma-{score_key}-{_slugify(label)}-rubric",
        "title": label,
        "summary": summary,
        "groups": groups,
        "footnote": "Missing or unknown values are skipped from the rolling score rather than forced to neutral.",
    }


def _five_point_scale_rubric(
    score_key: str,
    label: str,
    raw_value: float | None,
    *,
    inverse: bool = False,
    summary: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for value in range(1, 6):
        score = _score_from_scale_1_to_5(float(value))
        if inverse:
            score = 100 - score
        rows.append(
            _rubric_row(
                f"{value}/5",
                f"{round(score, 0):.0f}%",
                active=raw_value is not None and round(raw_value) == value,
            )
        )
    copy = summary or (
        "The 1-5 input is converted straight to a normalized 0-100 component score."
        if not inverse
        else "The 1-5 input is inverted before scoring, so lower values produce higher component scores."
    )
    return _component_rubric(score_key, label, copy, [_rubric_group("Score map", rows)])


def _passthrough_rubric(
    score_key: str,
    label: str,
    raw_value: float | None,
    *,
    summary: str,
) -> dict[str, Any]:
    note = None
    if raw_value is not None:
        note = f"Current input {round(raw_value, 0):.0f} becomes {round(raw_value, 0):.0f}%."
    return _component_rubric(
        score_key,
        label,
        summary,
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row(
                        "0-100 source value",
                        "same as input",
                        note=note,
                        active=raw_value is not None,
                    )
                ],
            )
        ],
    )


def _inverse_passthrough_rubric(
    score_key: str,
    label: str,
    raw_value: float | None,
    *,
    summary: str,
) -> dict[str, Any]:
    note = None
    if raw_value is not None:
        note = f"Current input {round(raw_value, 0):.0f} becomes {round(100 - raw_value, 0):.0f}%."
    return _formula_rubric(
        score_key,
        label,
        summary,
        "0-100 input value",
        note=note if note else "Score formula: 100 - input.",
    )


def _formula_rubric(
    score_key: str,
    label: str,
    summary: str,
    formula_label: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        summary,
        [_rubric_group("Score map", [_rubric_row(formula_label, "formula-based", note=note, active=True)])],
    )


def _choice_rubric(
    score_key: str,
    label: str,
    raw_value: str | None,
    mapping: list[tuple[str, str, str | None]],
    *,
    summary: str,
) -> dict[str, Any]:
    known = str(raw_value) if _known_state(raw_value) else None
    rows = [
        _rubric_row(
            input_label,
            score_label,
            note=note,
            active=known == input_label,
        )
        for input_label, score_label, note in mapping
    ]
    return _component_rubric(score_key, label, summary, [_rubric_group("Score map", rows)])


def _presence_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    is_set = _known_state(raw_value)
    return _component_rubric(
        score_key,
        label,
        "Any non-empty value counts as a present intent and yields a full component score.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row("Any filled value", "100%", active=is_set),
                    _rubric_row("Missing / unknown", "excluded", active=not is_set),
                ],
            )
        ],
    )


def _sleep_hours_capacity_rubric(score_key: str, label: str, hours: float | None) -> dict[str, Any]:
    rows = [
        _rubric_row("< 5h", "10%", active=hours is not None and hours < 5),
        _rubric_row("5h to < 6h", "30%", active=hours is not None and 5 <= hours < 6),
        _rubric_row("6h to < 7h", "55%", active=hours is not None and 6 <= hours < 7),
        _rubric_row("7h to < 8h", "80%", active=hours is not None and 7 <= hours < 8),
        _rubric_row("8h+", "100%", active=hours is not None and hours >= 8),
    ]
    return _component_rubric(
        score_key,
        label,
        "Capacity treats more sleep as more available fuel, using hour buckets rather than a linear formula.",
        [_rubric_group("Hour buckets", rows)],
    )


def _sleep_hours_load_rubric(score_key: str, label: str, hours: float | None) -> dict[str, Any]:
    rows = [
        _rubric_row("< 5h", "95%", active=hours is not None and hours < 5),
        _rubric_row("5h to < 6h", "75%", active=hours is not None and 5 <= hours < 6),
        _rubric_row("6h to < 7h", "55%", active=hours is not None and 6 <= hours < 7),
        _rubric_row("7h to < 8h", "35%", active=hours is not None and 7 <= hours < 8),
        _rubric_row("8h+", "20%", active=hours is not None and hours >= 8),
    ]
    return _component_rubric(
        score_key,
        label,
        "Load treats shorter sleep as more strain, so fewer hours map to higher load scores.",
        [_rubric_group("Hour buckets", rows)],
    )


def _resting_hr_capacity_rubric(
    score_key: str,
    label: str,
    resting: float | None,
    base: float | None,
) -> dict[str, Any]:
    use_base = resting is not None and base is not None and base > 0
    delta = (resting - base) if use_base else None
    base_rows = [
        _rubric_row("delta <= -4 bpm", "95%", active=delta is not None and delta <= -4),
        _rubric_row("-4 bpm < delta <= 0", "85%", active=delta is not None and -4 < delta <= 0),
        _rubric_row("0 < delta <= 3 bpm", "65%", active=delta is not None and 0 < delta <= 3),
        _rubric_row("3 < delta <= 6 bpm", "45%", active=delta is not None and 3 < delta <= 6),
        _rubric_row("delta > 6 bpm", "25%", active=delta is not None and delta > 6),
    ]
    fallback_rows = [
        _rubric_row("< 58 bpm", "90%", active=not use_base and resting is not None and resting < 58),
        _rubric_row("58 to < 64 bpm", "75%", active=not use_base and resting is not None and 58 <= resting < 64),
        _rubric_row("64 to < 70 bpm", "60%", active=not use_base and resting is not None and 64 <= resting < 70),
        _rubric_row("70 to < 76 bpm", "40%", active=not use_base and resting is not None and 70 <= resting < 76),
        _rubric_row("76 bpm+", "20%", active=not use_base and resting is not None and resting >= 76),
    ]
    return _component_rubric(
        score_key,
        label,
        "If base HR is available, capacity scores resting HR by how far it sits above or below base. Without a base HR, it falls back to absolute resting-HR buckets.",
        [
            _rubric_group("When base HR is present", base_rows),
            _rubric_group("Fallback without base HR", fallback_rows),
        ],
    )


def _resting_hr_load_rubric(
    score_key: str,
    label: str,
    resting: float | None,
    base: float | None,
) -> dict[str, Any]:
    use_base = resting is not None and base is not None and base > 0
    delta = (resting - base) if use_base else None
    base_rows = [
        _rubric_row("delta <= 0 bpm", "30%", active=delta is not None and delta <= 0),
        _rubric_row("0 < delta <= 3 bpm", "55%", active=delta is not None and 0 < delta <= 3),
        _rubric_row("3 < delta <= 6 bpm", "75%", active=delta is not None and 3 < delta <= 6),
        _rubric_row("delta > 6 bpm", "90%", active=delta is not None and delta > 6),
    ]
    fallback_rows = [
        _rubric_row("< 58 bpm", "25%", active=not use_base and resting is not None and resting < 58),
        _rubric_row("58 to < 64 bpm", "40%", active=not use_base and resting is not None and 58 <= resting < 64),
        _rubric_row("64 to < 70 bpm", "60%", active=not use_base and resting is not None and 64 <= resting < 70),
        _rubric_row("70 to < 76 bpm", "78%", active=not use_base and resting is not None and 70 <= resting < 76),
        _rubric_row("76 bpm+", "90%", active=not use_base and resting is not None and resting >= 76),
    ]
    return _component_rubric(
        score_key,
        label,
        "Load rises when resting HR runs above base. Without a base HR, the code falls back to absolute resting-HR buckets.",
        [
            _rubric_group("When base HR is present", base_rows),
            _rubric_group("Fallback without base HR", fallback_rows),
        ],
    )


def _main_drag_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    value = str(raw_value) if _known_state(raw_value) else ""
    return _component_rubric(
        score_key,
        label,
        "Load gives the lightest score when there is no clear drag, a heavier score for one selected drag, and the heaviest score when multiple drags are present.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row("no clear drag", "10%", active=value == "no clear drag"),
                    _rubric_row("one selected drag", "72%", active=bool(value) and value != "no clear drag" and ", " not in value),
                    _rubric_row("multiple selected drags", "85%", active=", " in value),
                ],
                note="Multiple selected drags are detected from a comma-separated value.",
            )
        ],
    )


def _midday_need_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    value = str(raw_value) if _known_state(raw_value) else ""
    return _component_rubric(
        score_key,
        label,
        "Midday Need is scored by matching the text to a few categories rather than by a strict numeric scale.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row("contains 'recommitment'", "55%", active="recommitment" in value),
                    _rubric_row(
                        "contains 'prayer', 'quiet', or 'conversation'",
                        "70%",
                        active=any(part in value for part in ["prayer", "quiet", "conversation"]),
                    ),
                    _rubric_row(
                        "any other filled value",
                        "65%",
                        active=bool(value)
                        and "recommitment" not in value
                        and not any(part in value for part in ["prayer", "quiet", "conversation"]),
                    ),
                ],
            )
        ],
    )


def _most_draining_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    value = str(raw_value) if _known_state(raw_value) else ""
    high = {"work pressure", "conflict", "fatigue", "overstimulation", "social depletion"}
    medium = {"fragmented attention", "uncertainty", "lack of progress", "physical discomfort", "temptation"}
    return _component_rubric(
        score_key,
        label,
        "Most Draining maps a few heavier pressure tags above the rest, with a middle band for moderate drains.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row(
                        ", ".join(sorted(high)),
                        "85%",
                        active=value in high,
                    ),
                    _rubric_row(
                        ", ".join(sorted(medium)),
                        "72%",
                        active=value in medium,
                    ),
                    _rubric_row(
                        "any other filled value",
                        "60%",
                        active=bool(value) and value not in high and value not in medium,
                    ),
                ],
            )
        ],
    )


def _late_night_screen_load_rubric(score_key: str, label: str, minutes: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Later screen time pushes Load upward because it usually borrows from recovery.",
        [
            _rubric_group(
                "Minute buckets",
                [
                    _rubric_row("0 to 15 min", "12%", active=minutes is not None and minutes <= 15),
                    _rubric_row("16 to 45 min", "35%", active=minutes is not None and 15 < minutes <= 45),
                    _rubric_row("46 to 90 min", "65%", active=minutes is not None and 45 < minutes <= 90),
                    _rubric_row("90+ min", "88%", active=minutes is not None and minutes > 90),
                ],
            )
        ],
    )


def _busy_minutes_load_rubric(score_key: str, label: str, minutes: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Calendar pressure increases Load in coarse busy-minute buckets.",
        [
            _rubric_group(
                "Busy-minute buckets",
                [
                    _rubric_row("0 to 60 min", "20%", active=minutes is not None and minutes <= 60),
                    _rubric_row("61 to 180 min", "45%", active=minutes is not None and 60 < minutes <= 180),
                    _rubric_row("181 to 300 min", "70%", active=minutes is not None and 180 < minutes <= 300),
                    _rubric_row("300+ min", "88%", active=minutes is not None and minutes > 300),
                ],
            )
        ],
    )


def _work_meetings_count_rubric(score_key: str, label: str, meetings: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Work meetings act as a manual pressure count so meeting-heavy days can raise Load even when calendar busy minutes miss the lived cost.",
        [
            _rubric_group(
                "Meeting-count buckets",
                [
                    _rubric_row("0 to 1 meetings", "12%", active=meetings is not None and meetings <= 1),
                    _rubric_row("2 to 3 meetings", "38%", active=meetings is not None and 1 < meetings <= 3),
                    _rubric_row("4 to 5 meetings", "68%", active=meetings is not None and 3 < meetings <= 5),
                    _rubric_row("6+ meetings", "88%", active=meetings is not None and meetings > 5),
                ],
            )
        ],
    )


def _meeting_average_7d_rubric(score_key: str, label: str, average: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "This weekly component remembers whether the last several days have been meeting-dense instead of reacting only to today's calendar.",
        [
            _rubric_group(
                "Average meetings per logged day",
                [
                    _rubric_row("< 1.5 meetings/day", "18%", active=average is not None and average < 1.5),
                    _rubric_row("1.5 to < 3.0/day", "42%", active=average is not None and 1.5 <= average < 3.0),
                    _rubric_row("3.0 to < 4.5/day", "68%", active=average is not None and 3.0 <= average < 4.5),
                    _rubric_row("4.5+/day", "88%", active=average is not None and average >= 4.5),
                ],
            )
        ],
    )


def _after_work_activity_rubric(score_key: str, label: str, hours: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "After-work hours capture how much of the evening stayed externally committed instead of settling into recovery.",
        [
            _rubric_group(
                "After-work hour buckets",
                [
                    _rubric_row("0h", "10%", active=hours is not None and hours <= 0),
                    _rubric_row(
                        f">0h to <{AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS:g}h",
                        "35%",
                        active=hours is not None and 0 < hours < AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS,
                    ),
                    _rubric_row(
                        f"{AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS:g}h to <{AFTER_WORK_BUSY_THRESHOLD_HOURS:g}h",
                        "62%",
                        active=hours is not None
                        and AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS <= hours < AFTER_WORK_BUSY_THRESHOLD_HOURS,
                    ),
                    _rubric_row(
                        f"{AFTER_WORK_BUSY_THRESHOLD_HOURS:g}h+",
                        "88%",
                        active=hours is not None and hours >= AFTER_WORK_BUSY_THRESHOLD_HOURS,
                    ),
                ],
            )
        ],
    )


def _busy_evenings_7d_rubric(score_key: str, label: str, days_busy: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Busy evenings persist across the week, so this score counts how many recent logged days had heavy after-work hours.",
        [
            _rubric_group(
                "Busy-evening day count",
                [
                    _rubric_row("0 busy evenings", "15%", active=days_busy is not None and days_busy <= 0),
                    _rubric_row("1 busy evening", "35%", active=days_busy is not None and 0 < days_busy <= 1),
                    _rubric_row("2 to 3 busy evenings", "68%", active=days_busy is not None and 1 < days_busy <= 3),
                    _rubric_row("4+ busy evenings", "90%", active=days_busy is not None and days_busy > 3),
                ],
                note=f"Busy means {AFTER_WORK_BUSY_THRESHOLD_HOURS:g}+ after-work hours on a day.",
            )
        ],
    )


def _errands_appointments_rubric(score_key: str, label: str, count: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Errands and appointments add practical fragmentation that often lands in the body as extra load.",
        [
            _rubric_group(
                "Errand-count buckets",
                [
                    _rubric_row("0 errands", "12%", active=count is not None and count <= 0),
                    _rubric_row("1 errand", "32%", active=count is not None and 0 < count <= 1),
                    _rubric_row("2 to 3 errands", "60%", active=count is not None and 1 < count <= 3),
                    _rubric_row("4+ errands", "82%", active=count is not None and count > 3),
                ],
            )
        ],
    )


def _social_commitments_rubric(score_key: str, label: str, count: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Social commitments are counted as obligation load here, not as a measure of relational nourishment.",
        [
            _rubric_group(
                "Commitment-count buckets",
                [
                    _rubric_row("0 commitments", "15%", active=count is not None and count <= 0),
                    _rubric_row("1 commitment", "38%", active=count is not None and 0 < count <= 1),
                    _rubric_row("2 commitments", "62%", active=count is not None and 1 < count <= 2),
                    _rubric_row("3+ commitments", "85%", active=count is not None and count > 2),
                ],
            )
        ],
    )


def _sedentary_streak_load_rubric(score_key: str, label: str, minutes: float | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Longer sedentary streaks gently raise Load because the day is getting physically static.",
        [
            _rubric_group(
                "Streak buckets",
                [
                    _rubric_row("0 to 45 min", "18%", active=minutes is not None and minutes <= 45),
                    _rubric_row("46 to 90 min", "40%", active=minutes is not None and 45 < minutes <= 90),
                    _rubric_row("91 to 150 min", "68%", active=minutes is not None and 90 < minutes <= 150),
                    _rubric_row("150+ min", "86%", active=minutes is not None and minutes > 150),
                ],
            )
        ],
    )


def _alignment_choice_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("yes", "100%", None),
            ("partly", "60%", None),
            ("no", "20%", None),
        ],
        summary="Evening Alignment is a direct categorical check on whether the day actually aligned.",
    )


def _midday_drift_alignment_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("better", "85%", None),
            ("same", "60%", None),
            ("worse", "30%", None),
        ],
        summary="Alignment treats improvement through the day as stronger alignment and worsening drift as weaker alignment.",
    )


def _midday_drift_load_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("better", "20%", None),
            ("same", "50%", None),
            ("worse", "90%", None),
        ],
        summary="Load uses Midday Drift as a strain signal, with worsening drift mapping to much higher load.",
    )


def _abiding_completion_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("complete", "100%", None),
            ("incomplete", "25%", None),
        ],
        summary="Abiding Completion boosts alignment strongly when the rite is complete and only lightly when it is incomplete.",
    )


def _abiding_last_7_days_rubric(score_key: str, label: str, raw_value: float | None) -> dict[str, Any]:
    rows = [
        _rubric_row(
            f"{days}/7",
            f"{round(_abiding_last_7_days_numeric_score(float(days)) or 0, 0):.0f}%",
            active=raw_value is not None and round(raw_value) == days,
        )
        for days in range(0, 8)
    ]
    return _component_rubric(
        score_key,
        label,
        "This component tracks cadence: how many of the last 7 days included Abiding.",
        [_rubric_group("Score map", rows, note="Score reaches 100% once Abiding lands on 5 of the last 7 days.")],
    )


def _sleep_penalty_rubric(score_key: str, label: str, raw_value: float | None) -> dict[str, Any]:
    note = None
    if raw_value is not None:
        note = f"Current input {round(raw_value, 0):.0f} becomes {round(100 - raw_value, 0):.0f}%."
    return _formula_rubric(
        score_key,
        label,
        "In Load, Sleep Score works as a penalty: stronger sleep lowers load.",
        "0-100 input value",
        note=note if note else "Score formula: 100 - input.",
    )


def _undercurrent_state_shift_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("more open", "90%", "The system opened back up under load."),
            ("same", "60%", "A neutral landing with little visible repair or collapse."),
            ("more closed", "25%", "The day ended more constricted than it began."),
        ],
        summary="Steadiness uses State Shift as a direction-of-recovery check: did the day leave you more open, unchanged, or more closed?",
    )


def _state_shift_intensity_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("None", "100%", "No notable volatility landed in the system."),
            ("Mild", "68%", "Some activation or disruption, but contained."),
            ("Strong", "28%", "A sharp shift that likely scattered regulation."),
        ],
        summary="Steadiness treats stronger state-shift intensity as higher volatility, so the score drops as intensity rises.",
    )


def _regulation_response_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("None", "35%", "No meaningful regulation response was logged."),
            ("Avoided", "15%", "Avoidance pulls the system further from baseline."),
            ("Paused", "60%", "A pause helped interrupt momentum."),
            ("Repaired", "82%", "A concrete repair action helped recovery."),
            ("Recentered", "100%", "The system visibly returned to baseline."),
        ],
        summary="Regulation Response is the main manual repair signal: did you avoid, pause, repair, or actually recenter?",
    )


def _most_restorative_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _choice_rubric(
        score_key,
        label,
        raw_value,
        [
            ("prayer", "90%", None),
            ("scripture", "90%", None),
            ("walking", "90%", None),
            ("sunlight", "90%", None),
            ("quiet", "90%", None),
            ("rest", "90%", None),
            ("worship", "90%", None),
            ("journaling", "90%", None),
            ("family time", "80%", None),
            ("wife/family time", "80%", None),
            ("music", "80%", None),
            ("clean space", "80%", None),
            ("meal", "80%", None),
            ("task completion", "70%", None),
        ],
        summary="Most Restorative gives a small repair boost, favoring embodied and settling practices over purely productive relief.",
    )


def _primary_disruptor_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Primary Disruptor estimates drift and destabilization from what pulled the system off-center. Multiple disruptors stack downward.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row("Noise / Appetite", "70%"),
                    _rubric_row("Fatigue / Hurry / Uncertainty / Task Load", "55%"),
                    _rubric_row("Conflict / Screen / Spiritual Drift", "35%"),
                    _rubric_row("Each extra disruptor", "-10% (up to -20%)"),
                ],
                note=f"Current input: {raw_value}" if _known_state(raw_value) else None,
            )
        ],
    )


def _primary_disruptor_load_rubric(score_key: str, label: str, raw_value: str | None) -> dict[str, Any]:
    return _component_rubric(
        score_key,
        label,
        "Load treats heavier disruptors as extra strain, and multiple disruptors stack upward instead of canceling out.",
        [
            _rubric_group(
                "Score map",
                [
                    _rubric_row("Noise / Appetite", "30%"),
                    _rubric_row("Fatigue / Hurry / Uncertainty / Task Load", "45%"),
                    _rubric_row("Conflict / Screen / Spiritual Drift", "65%"),
                    _rubric_row("Each extra disruptor", "+10% (up to +20%)"),
                ],
                note=f"Current input: {raw_value}" if _known_state(raw_value) else None,
            )
        ],
    )


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _weighted_average_score(parts: list[tuple[float | None, float]]) -> float | None:
    total = 0.0
    weight = 0.0
    for score, part_weight in parts:
        if score is None:
            continue
        total += score * part_weight
        weight += part_weight
    if weight <= 0:
        return None
    return total / weight


def _daily_numeric_rows(entity_id: str, *, days: int = 30) -> list[tuple[datetime, float]]:
    end = datetime.now(TZ)
    start_ts = (end - timedelta(days=days)).timestamp()
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=start_ts, end_ts=end.timestamp())
    by_day: dict[str, tuple[datetime, float]] = {}
    for updated_ts, state in rows:
        value = _state_float(state)
        if value is None:
            continue
        dt = datetime.fromtimestamp(updated_ts, tz=TZ)
        by_day[dt.date().isoformat()] = (dt, value)
    return [by_day[key] for key in sorted(by_day)]


def _average_daily_numeric_value(entity_id: str, *, days: int = 7) -> float | None:
    rows = _daily_numeric_rows(entity_id, days=days)
    if not rows:
        return None
    return sum(value for _, value in rows) / len(rows)


def _count_daily_values_at_or_above(entity_id: str, threshold: float, *, days: int = 7) -> int | None:
    rows = _daily_numeric_rows(entity_id, days=days)
    if not rows:
        return None
    return sum(1 for _, value in rows if value >= threshold)


def _recent_average_summary(entity_id: str, *, days: int = 7, decimals: int = 1, suffix: str = "") -> str:
    rows = _daily_numeric_rows(entity_id, days=days)
    if not rows:
        return f"No {days}-day history yet."
    average = sum(value for _, value in rows) / len(rows)
    return f"{average:.{decimals}f}{suffix} across {len(rows)} logged days."


def _recent_threshold_day_summary(entity_id: str, threshold: float, *, days: int = 7, label: str) -> str:
    rows = _daily_numeric_rows(entity_id, days=days)
    if not rows:
        return f"No {days}-day history yet."
    count = sum(1 for _, value in rows if value >= threshold)
    return f"{count}/{len(rows)} logged days at {threshold:g}+ {label}."


def _average_excluding_single_extremes(values: list[float]) -> float:
    if not values:
        raise ValueError("values must not be empty")

    averaged_values = list(values)
    if len(averaged_values) > 2:
        averaged_values.remove(min(averaged_values))
        averaged_values.remove(max(averaged_values))
    return sum(averaged_values) / len(averaged_values)


def _profile_from_values(
    values: list[float],
    *,
    trim_extremes_for_mean: bool = False,
) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "mean": (
            _average_excluding_single_extremes(values)
            if trim_extremes_for_mean
            else (sum(values) / len(values))
        ),
        "min": min(values),
        "max": max(values),
    }


def _monthly_numeric_profile(
    entity_id: str,
    *,
    days: int = 30,
    trim_extremes_for_mean: bool = False,
) -> dict[str, float] | None:
    return _profile_from_values(
        [value for _, value in _daily_numeric_rows(entity_id, days=days)],
        trim_extremes_for_mean=trim_extremes_for_mean,
    )


def _monthly_delta_profile(
    earlier_entity_id: str,
    later_entity_id: str,
    *,
    days: int = 30,
    trim_extremes_for_mean: bool = False,
) -> dict[str, float] | None:
    earlier = {dt.date().isoformat(): value for dt, value in _daily_numeric_rows(earlier_entity_id, days=days)}
    later = {dt.date().isoformat(): value for dt, value in _daily_numeric_rows(later_entity_id, days=days)}
    values = [earlier[key] - later[key] for key in sorted(earlier.keys() & later.keys())]
    return _profile_from_values(values, trim_extremes_for_mean=trim_extremes_for_mean)


def _bedtime_parts(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = BEDTIME_24H_RE.fullmatch(value.strip())
    if not match:
        return None
    return int(match.group("hour")), int(match.group("minute"))


def _shifted_bedtime_minutes(hour: int, minute: int) -> float:
    return float((((hour * 60) + minute) - 720) % 1440)


def _bedtime_display_from_text(value: str | None) -> str | None:
    parts = _bedtime_parts(value)
    if parts is None:
        return None
    hour, minute = parts
    return datetime(2000, 1, 1, hour, minute).strftime("%I:%M %p").lstrip("0")


def _monthly_undercurrent_bedtime_profile(
    *,
    days: int = 30,
    trim_extremes_for_mean: bool = False,
) -> dict[str, float] | None:
    return _monthly_numeric_profile(
        UNDERCURRENT_BEDTIME_SHIFTED_ENTITY,
        days=days,
        trim_extremes_for_mean=trim_extremes_for_mean,
    )


def _latest_undercurrent_bedtime_context(entities: dict[str, dict[str, Any]]) -> tuple[float | None, str | None]:
    raw_bedtime = _state_text(entities, UNDERCURRENT_BEDTIME_ENTITY)
    return (
        _state_float(_state_text(entities, UNDERCURRENT_BEDTIME_SHIFTED_ENTITY)),
        _bedtime_display_from_text(raw_bedtime),
    )


PROFILE_RELATIVE_BASELINE_SCORE = 60.0


def _profile_relative_score(
    value: float | None,
    profile: dict[str, float] | None,
    *,
    inverse: bool = False,
    min_span: float,
    fallback: Any = None,
) -> float | None:
    if value is None:
        return None
    if not profile:
        return fallback(value) if callable(fallback) else fallback

    mean = profile["mean"]
    low = profile["min"]
    high = profile["max"]

    if inverse:
        if value >= mean:
            span = max(high - mean, min_span)
            score = PROFILE_RELATIVE_BASELINE_SCORE - (((value - mean) / span) * PROFILE_RELATIVE_BASELINE_SCORE)
        else:
            span = max(mean - low, min_span)
            score = PROFILE_RELATIVE_BASELINE_SCORE + (
                ((mean - value) / span) * (100.0 - PROFILE_RELATIVE_BASELINE_SCORE)
            )
        return _clamp_score(score)

    if value >= mean:
        span = max(high - mean, min_span)
        score = PROFILE_RELATIVE_BASELINE_SCORE + (
            ((value - mean) / span) * (100.0 - PROFILE_RELATIVE_BASELINE_SCORE)
        )
    else:
        span = max(mean - low, min_span)
        score = PROFILE_RELATIVE_BASELINE_SCORE - (((mean - value) / span) * PROFILE_RELATIVE_BASELINE_SCORE)
    return _clamp_score(score)


def _fallback_wellness_score(value: float) -> float:
    return _clamp_score(value)


def _fallback_drop_score(value: float) -> float:
    if value <= 0:
        return 100
    if value <= 5:
        return 80
    if value <= 10:
        return 60
    if value <= 15:
        return 40
    return 20


def _fallback_bedtime_score(value: float) -> float:
    if value <= 660:
        return 100
    if value <= 750:
        return 80
    if value <= 840:
        return 55
    return 30


def _base_hr_capacity_score(value: float | None, profile: dict[str, float] | None) -> float | None:
    return _profile_relative_score(
        value,
        profile,
        inverse=True,
        min_span=4,
        fallback=lambda raw: _capacity_resting_hr_score(raw, None),
    )


def _morning_wellness_score(value: float | None, profile: dict[str, float] | None) -> float | None:
    return _profile_relative_score(
        value,
        profile,
        min_span=10,
        fallback=_fallback_wellness_score,
    )


def _phase_drop_score(value: float | None, profile: dict[str, float] | None) -> float | None:
    return _profile_relative_score(
        value,
        profile,
        inverse=True,
        min_span=5,
        fallback=_fallback_drop_score,
    )


def _format_profile_value(value: float | None, *, decimals: int = 0, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return _format_numeric_value(value, decimals=decimals, suffix=suffix)


def _monthly_baseline_rubric(
    score_key: str,
    label: str,
    summary: str,
    *,
    profile: dict[str, float] | None,
    current_value: float | None,
    inverse: bool = False,
    decimals: int = 0,
    suffix: str = "",
    extra_note: str | None = None,
) -> dict[str, Any]:
    note_parts: list[str] = []
    if profile:
        note_parts.append(
            "30d low "
            f"{_format_profile_value(profile['min'], decimals=decimals, suffix=suffix)}, "
            f"trimmed avg {_format_profile_value(profile['mean'], decimals=decimals, suffix=suffix)}, "
            f"high {_format_profile_value(profile['max'], decimals=decimals, suffix=suffix)}."
        )
        note_parts.append(
            f"Matching that 30-day trimmed average lands at {PROFILE_RELATIVE_BASELINE_SCORE:.0f}; "
            "moving in the better direction rises toward 100, and moving in the worse direction falls toward 0."
        )
    else:
        note_parts.append("30-day baseline is still thin, so this falls back to a simpler score.")
    if current_value is not None:
        direction = "lower" if inverse else "higher"
        note_parts.append(
            f"Current {_format_profile_value(current_value, decimals=decimals, suffix=suffix)} "
            f"scores better when it trends {direction} than your recent norm."
        )
    if extra_note:
        note_parts.append(extra_note)
    return _formula_rubric(
        score_key,
        label,
        summary,
        "30-day personal baseline",
        note=" ".join(note_parts),
    )


def _build_capacity_breakdown(entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    morning_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_morning_wellness",
        trim_extremes_for_mean=True,
    )
    midday_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_midday_wellness",
        trim_extremes_for_mean=True,
    )
    evening_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_evening_wellness",
        trim_extremes_for_mean=True,
    )
    morning_midday_drop_profile = _monthly_delta_profile(
        "sensor.undercurrent_morning_wellness",
        "sensor.undercurrent_midday_wellness",
        trim_extremes_for_mean=True,
    )
    midday_evening_drop_profile = _monthly_delta_profile(
        "sensor.undercurrent_midday_wellness",
        "sensor.undercurrent_evening_wellness",
        trim_extremes_for_mean=True,
    )
    sleep_score_profile = _monthly_numeric_profile(
        "sensor.undercurrent_sleep_score",
        trim_extremes_for_mean=True,
    )
    base_hr_profile = _monthly_numeric_profile(
        "sensor.undercurrent_base_hr",
        trim_extremes_for_mean=True,
    )
    bedtime_profile = _monthly_undercurrent_bedtime_profile(trim_extremes_for_mean=True)

    v = _state_float(_state_text(entities, "sensor.undercurrent_morning_energy"))
    chart = _component_score_chart("sensor.undercurrent_morning_energy", _scale_score)
    _weighted_component(
        components,
        label="Morning Energy",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.17,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_energy", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("capacity", "Morning Energy", v),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_morning_clarity"))
    chart = _component_score_chart("sensor.undercurrent_morning_clarity", _scale_score)
    _weighted_component(
        components,
        label="Morning Clarity",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.17,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_clarity", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("capacity", "Morning Clarity", v),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_morning_mood"))
    chart = _component_score_chart("sensor.undercurrent_morning_mood", _scale_score)
    _weighted_component(
        components,
        label="Morning Mood",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_mood", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("capacity", "Morning Mood", v),
    )

    morning_wellness = _state_float(_state_text(entities, "sensor.undercurrent_morning_wellness"))
    chart = _component_score_chart(
        "sensor.undercurrent_morning_wellness",
        lambda raw, profile=morning_wellness_profile: _morning_wellness_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Morning Wellness",
        raw=f"{morning_wellness:.0f}" if morning_wellness is not None else "missing",
        score=_morning_wellness_score(morning_wellness, morning_wellness_profile),
        weight=0.14,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_wellness"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Morning Wellness",
            "Morning Wellness is now scored against your last 30 days, so higher-than-normal mornings feel better than merely average ones.",
            profile=morning_wellness_profile,
            current_value=morning_wellness,
        ),
    )

    sleep_score = _state_float(_state_text(entities, "sensor.undercurrent_sleep_score"))
    minutes = _state_float(_state_text(entities, "sensor.aperture_sleep_duration"))
    hours = (minutes / 60) if minutes is not None else None
    bedtime_shifted, bedtime_display = _latest_undercurrent_bedtime_context(entities)
    personal_sleep_score = _profile_relative_score(
        sleep_score,
        sleep_score_profile,
        min_span=8,
        fallback=_fallback_wellness_score,
    )
    sleep_hours_score = _capacity_sleep_hours_score(hours) if hours is not None else None
    bedtime_score = _profile_relative_score(
        bedtime_shifted,
        bedtime_profile,
        inverse=True,
        min_span=90,
        fallback=_fallback_bedtime_score,
    )
    chart = _component_score_chart(
        "sensor.undercurrent_sleep_score",
        lambda raw, profile=sleep_score_profile: _profile_relative_score(
            _state_float(raw),
            profile,
            min_span=8,
            fallback=_fallback_wellness_score,
        ),
    )
    _weighted_component(
        components,
        label="Sleep Score",
        raw=f"{sleep_score:.0f}" if sleep_score is not None else "missing",
        score=personal_sleep_score,
        weight=0.11,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_sleep_score"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Sleep Score",
            "Sleep Score now stands on its own, comparing your sleep score to your recent personal range without blending in hours or bedtime.",
            profile=sleep_score_profile,
            current_value=sleep_score,
        ),
    )
    chart = _component_score_chart(
        "sensor.aperture_sleep_hours",
        lambda raw: _capacity_sleep_hours_score(hours_raw) if (hours_raw := _state_float(raw)) is not None else None,
    )
    _weighted_component(
        components,
        label="Sleep Hours",
        raw=f"{hours:.2f}h" if hours is not None else "missing",
        score=sleep_hours_score,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.aperture_sleep_hours", suffix="h", decimals=2),
        chart=chart,
        scoring=_formula_rubric(
            "capacity",
            "Sleep Hours",
            "Sleep Hours now contribute as their own bucketed capacity signal instead of being folded into a blended sleep score.",
            "Sleep duration buckets",
            note=(
                f"Current sleep duration is {hours:.2f}h. <5h scores 10, 5-6h scores 30, 6-7h scores 55, 7-8h scores 80, and 8h+ scores 100."
                if hours is not None
                else "Sleep duration is missing."
            ),
        ),
    )
    chart = _component_score_chart(
        UNDERCURRENT_BEDTIME_SHIFTED_ENTITY,
        lambda raw, profile=bedtime_profile: _profile_relative_score(
            _state_float(raw),
            profile,
            inverse=True,
            min_span=90,
            fallback=_fallback_bedtime_score,
        ),
    )
    _weighted_component(
        components,
        label="Bedtime",
        raw=bedtime_display or "missing",
        score=bedtime_score,
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary(UNDERCURRENT_BEDTIME_SHIFTED_ENTITY, suffix=" min"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Bedtime",
            "Bedtime now contributes separately, rewarding an earlier or more settled bedtime relative to your recent norm.",
            profile=bedtime_profile,
            current_value=bedtime_shifted,
            inverse=True,
            suffix=" min",
            extra_note=f"Latest logged bedtime is {bedtime_display}." if bedtime_display else None,
        ),
    )

    base_hr = _state_float(_state_text(entities, "sensor.undercurrent_base_hr"))
    chart = _component_score_chart(
        "sensor.undercurrent_base_hr",
        lambda raw, profile=base_hr_profile: _base_hr_capacity_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Base Heart Rate",
        raw=f"{base_hr:.0f} bpm" if base_hr is not None else "missing",
        score=_base_hr_capacity_score(base_hr, base_hr_profile),
        weight=0.06,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_base_hr", suffix=" bpm"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Base Heart Rate",
            "Base Heart Rate now compares your sleeping resting heart rate to your own 30-day pattern, so a higher-than-normal baseline costs capacity before the day starts.",
            profile=base_hr_profile,
            current_value=base_hr,
            inverse=True,
            suffix=" bpm",
        ),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_midday_energy"))
    chart = _component_score_chart("sensor.undercurrent_midday_energy", _scale_score)
    _weighted_component(
        components,
        label="Midday Energy",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_midday_energy", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("capacity", "Midday Energy", v),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_midday_focus"))
    chart = _component_score_chart("sensor.undercurrent_midday_focus", _scale_score)
    _weighted_component(
        components,
        label="Midday Focus",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.04,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_midday_focus", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("capacity", "Midday Focus", v),
    )

    midday_wellness = _state_float(_state_text(entities, "sensor.undercurrent_midday_wellness"))
    morning_midday_drop = (
        morning_wellness - midday_wellness
        if midday_wellness is not None and morning_wellness is not None
        else None
    )
    chart = _component_score_chart(
        "sensor.undercurrent_midday_wellness",
        lambda raw, profile=midday_wellness_profile: _morning_wellness_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Midday Wellness",
        raw=f"{midday_wellness:.0f}" if midday_wellness is not None else "missing",
        score=_morning_wellness_score(midday_wellness, midday_wellness_profile),
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_midday_wellness"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Midday Wellness",
            "Midday Wellness now scores the midday value against your recent norm without blending in the morning-to-midday drop.",
            profile=midday_wellness_profile,
            current_value=midday_wellness,
        ),
    )
    chart = _component_score_chart(
        "sensor.undercurrent_morning_midday_wellness_drop",
        lambda raw, profile=morning_midday_drop_profile: _phase_drop_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Morning to Midday Delta",
        raw=f"{morning_midday_drop:.0f}" if morning_midday_drop is not None else "missing",
        score=_phase_drop_score(morning_midday_drop, morning_midday_drop_profile),
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_midday_wellness_drop"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Morning to Midday Delta",
            "Morning to Midday Delta now stands alone, so a smaller-than-usual drop scores better without being mixed into the raw midday wellness level.",
            profile=morning_midday_drop_profile,
            current_value=morning_midday_drop,
            inverse=True,
            extra_note="Lower drop values score better here because they reflect steadier energy through midday.",
        ),
    )

    evening_wellness = _state_float(_state_text(entities, "sensor.undercurrent_evening_wellness"))
    midday_evening_drop = (
        midday_wellness - evening_wellness
        if evening_wellness is not None and midday_wellness is not None
        else None
    )
    chart = _component_score_chart(
        "sensor.undercurrent_evening_wellness",
        lambda raw, profile=evening_wellness_profile: _morning_wellness_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Evening Wellness",
        raw=f"{evening_wellness:.0f}" if evening_wellness is not None else "missing",
        score=_morning_wellness_score(evening_wellness, evening_wellness_profile),
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_evening_wellness"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Evening Wellness",
            "Evening Wellness now scores the evening value against your usual range without blending in the midday-to-evening drop.",
            profile=evening_wellness_profile,
            current_value=evening_wellness,
        ),
    )
    chart = _component_score_chart(
        "sensor.undercurrent_midday_evening_wellness_drop",
        lambda raw, profile=midday_evening_drop_profile: _phase_drop_score(_state_float(raw), profile),
    )
    _weighted_component(
        components,
        label="Midday to Evening Delta",
        raw=f"{midday_evening_drop:.0f}" if midday_evening_drop is not None else "missing",
        score=_phase_drop_score(midday_evening_drop, midday_evening_drop_profile),
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_midday_evening_wellness_drop"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "capacity",
            "Midday to Evening Delta",
            "Midday to Evening Delta now stands alone, so a smaller-than-usual evening drop scores better without being mixed into the raw evening wellness level.",
            profile=midday_evening_drop_profile,
            current_value=midday_evening_drop,
            inverse=True,
            extra_note="Lower drop values score better here because they reflect steadier capacity into the evening.",
        ),
    )

    morning_state = _state_text(entities, "sensor.undercurrent_morning_state_tags")
    morning_state_score = _state_float(_state_text(entities, "sensor.undercurrent_morning_state_capacity_score"))
    chart = _score_entity_chart("sensor.undercurrent_morning_state_capacity_score")
    _weighted_component(
        components,
        label="Morning State Tags",
        raw=morning_state if _known_state(morning_state) else "missing",
        score=morning_state_score,
        weight=0.03,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_morning_state_capacity_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "capacity",
            "Morning State Tags",
            morning_state_score,
            summary="Morning state tags now add a small felt-state check, so grounded or calm starts help capacity while foggy or burdened starts cost it.",
        ),
    )

    hrv = _state_float(_state_text(entities, "sensor.aperture_hrv_relative_score"))
    chart = _score_entity_chart("sensor.aperture_hrv_relative_score")
    _weighted_component(
        components,
        label="HRV Relative",
        raw=f"{hrv:.0f}%" if hrv is not None else "missing",
        score=hrv,
        weight=0.01,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_hrv_relative_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "capacity",
            "HRV Relative",
            hrv,
            summary="HRV now contributes a light recovery check, giving a small boost when your nervous system looks more resourced than usual.",
        ),
    )

    return _finalize_breakdown(components)


def _build_alignment_breakdown(entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []

    v = _state_float(_state_text(entities, "sensor.undercurrent_morning_spiritual_orientation"))
    chart = _component_score_chart("sensor.undercurrent_morning_spiritual_orientation", _scale_score)
    _weighted_component(
        components,
        label="Morning Spiritual Orientation",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.22,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.undercurrent_morning_spiritual_orientation",
            suffix="/5",
        ),
        chart=chart,
        scoring=_five_point_scale_rubric("alignment", "Morning Spiritual Orientation", v),
    )

    intent = _state_text(entities, "sensor.undercurrent_daily_intent")
    chart = _component_score_chart("sensor.undercurrent_daily_intent", _presence_score)
    _weighted_component(
        components,
        label="Daily Intent",
        raw=intent if intent not in {"unknown", "unavailable", "none", ""} else "missing",
        score=100 if intent not in {"unknown", "unavailable", "none", ""} else None,
        weight=0.09,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_daily_intent"),
        chart=chart,
        scoring=_presence_rubric("alignment", "Daily Intent", intent),
    )

    drift = _state_text(entities, "sensor.undercurrent_midday_drift")
    drift_score = None
    if drift == "better":
        drift_score = 85
    elif drift == "same":
        drift_score = 60
    elif drift == "worse":
        drift_score = 30
    chart = _component_score_chart("sensor.undercurrent_midday_drift", _midday_drift_score)
    _weighted_component(
        components,
        label="Midday Drift",
        raw=drift if drift not in {"unknown", "unavailable", "none", ""} else "missing",
        score=drift_score,
        weight=0.08,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_midday_drift"),
        chart=chart,
        scoring=_midday_drift_alignment_rubric("alignment", "Midday Drift", drift),
    )

    need = _state_text(entities, "sensor.undercurrent_midday_need")
    need_score = None
    if need not in {"unknown", "unavailable", "none", ""}:
        if "recommitment" in need:
            need_score = 55
        elif any(part in need for part in ["prayer", "quiet", "conversation"]):
            need_score = 70
        else:
            need_score = 65
    chart = _component_score_chart("sensor.undercurrent_midday_need", _midday_need_score)
    _weighted_component(
        components,
        label="Midday Need",
        raw=need if need not in {"unknown", "unavailable", "none", ""} else "missing",
        score=need_score,
        weight=0.04,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_midday_need"),
        chart=chart,
        scoring=_midday_need_rubric("alignment", "Midday Need", need),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_evening_spiritual_orientation"))
    chart = _component_score_chart("sensor.undercurrent_evening_spiritual_orientation", _scale_score)
    _weighted_component(
        components,
        label="Evening Spiritual Orientation",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.undercurrent_evening_spiritual_orientation",
            suffix="/5",
        ),
        chart=chart,
        scoring=_five_point_scale_rubric("alignment", "Evening Spiritual Orientation", v),
    )

    alignment = _state_text(entities, "sensor.undercurrent_alignment")
    alignment_score = None
    if alignment == "yes":
        alignment_score = 100
    elif alignment == "partly":
        alignment_score = 60
    elif alignment == "no":
        alignment_score = 20
    chart = _component_score_chart("sensor.undercurrent_alignment", _alignment_choice_score)
    _weighted_component(
        components,
        label="Evening Alignment",
        raw=alignment if alignment not in {"unknown", "unavailable", "none", ""} else "missing",
        score=alignment_score,
        weight=0.11,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_alignment"),
        chart=chart,
        scoring=_alignment_choice_rubric("alignment", "Evening Alignment", alignment),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_day_score"))
    chart = _component_score_chart("sensor.undercurrent_day_score", _scale_score)
    _weighted_component(
        components,
        label="Day Score",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_day_score", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric("alignment", "Day Score", v),
    )

    abiding = _state_text(entities, "sensor.rhythmic_rite_abiding_complete")
    abiding_score = None
    if abiding == "complete":
        abiding_score = 100
    elif abiding == "incomplete":
        abiding_score = 25
    chart = _component_score_chart("sensor.rhythmic_rite_abiding_complete", _abiding_completion_score)
    _weighted_component(
        components,
        label="Abiding Completion",
        raw=abiding if abiding not in {"unknown", "unavailable", "none", ""} else "missing",
        score=abiding_score,
        weight=0.09,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.rhythmic_rite_abiding_complete"),
        chart=chart,
        scoring=_abiding_completion_rubric("alignment", "Abiding Completion", abiding),
    )

    abiding_days = _state_float(_state_text(entities, "sensor.rhythmic_rite_abiding_last_7_days"))
    chart = _component_score_chart("sensor.rhythmic_rite_abiding_last_7_days", _abiding_last_7_days_score)
    _weighted_component(
        components,
        label="Abiding Last 7 Days",
        raw=f"{abiding_days:.0f}/7" if abiding_days is not None else "missing",
        score=_abiding_last_7_days_numeric_score(abiding_days),
        weight=0.07,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.rhythmic_rite_abiding_last_7_days",
            transform=_abiding_last_7_days_numeric_score,
        ),
        chart=chart,
        scoring=_abiding_last_7_days_rubric("alignment", "Abiding Last 7 Days", abiding_days),
    )

    signal_presence = _state_float(_state_text(entities, "sensor.signal_field_weighted_presence_today"))
    chart = _component_score_chart("sensor.signal_field_weighted_presence_today", _scale_score)
    _weighted_component(
        components,
        label="Signal Field Presence",
        raw=f"{signal_presence:.2f}/5" if signal_presence is not None else "missing",
        score=_score_from_scale_1_to_5(signal_presence) if signal_presence is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.signal_field_weighted_presence_today",
            suffix="/5",
            decimals=2,
        ),
        chart=chart,
        scoring=_five_point_scale_rubric("alignment", "Signal Field Presence", signal_presence),
    )

    signal_hours = _state_float(_state_text(entities, "sensor.signal_field_presence_hours_today"))
    chart = _component_score_chart("sensor.signal_field_presence_hours_today", _signal_presence_hours_score)
    _weighted_component(
        components,
        label="Signal Field Hours",
        raw=f"{signal_hours:.2f}h" if signal_hours is not None else "missing",
        score=_signal_presence_hours_score(_state_text(entities, "sensor.signal_field_presence_hours_today")),
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.signal_field_presence_hours_today", suffix="h", decimals=2),
        chart=chart,
        scoring=_formula_rubric(
            "alignment",
            "Signal Field Hours",
            "Signal Field hours now help Alignment differentiate between a brief presence blip and a day with real staying time in attentive practices.",
            "Presence-hours buckets",
            note=(
                f"Current presence time is {signal_hours:.2f}h. 0h scores 25, >0h scores 45, 0.75h+ scores 65, 1.5h+ scores 82, and 2.5h+ scores 100."
                if signal_hours is not None
                else "Signal Field hours are missing."
            ),
        ),
    )

    carryover = _state_text(entities, "sensor.undercurrent_carryover")
    carryover_score = _state_float(_state_text(entities, "sensor.undercurrent_carryover_repair_score"))
    chart = _score_entity_chart("sensor.undercurrent_carryover_repair_score")
    _weighted_component(
        components,
        label="Carryover",
        raw=carryover if _known_state(carryover) else "missing",
        score=carryover_score,
        weight=0.05,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_carryover_repair_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "alignment",
            "Carryover",
            carryover_score,
            summary="Carryover now informs Alignment directly, so less residue from yesterday leaves more of today available for clean intent.",
        ),
    )

    neglected = _state_text(entities, "sensor.undercurrent_neglected_domain")
    neglected_score = _state_float(_state_text(entities, "sensor.undercurrent_neglected_domain_support_score"))
    chart = _score_entity_chart("sensor.undercurrent_neglected_domain_support_score")
    _weighted_component(
        components,
        label="Neglected Domain",
        raw=neglected if _known_state(neglected) else "missing",
        score=neglected_score,
        weight=0.04,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_neglected_domain_support_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "alignment",
            "Neglected Domain",
            neglected_score,
            summary="Neglected domains now cost Alignment, especially when Anchor, Recovery, or Bond are the places falling out of the day.",
        ),
    )

    tomorrow_need = _state_text(entities, "sensor.undercurrent_tomorrow_need")
    tomorrow_need_score = _state_float(_state_text(entities, "sensor.undercurrent_tomorrow_need_repair_score"))
    chart = _score_entity_chart("sensor.undercurrent_tomorrow_need_repair_score")
    _weighted_component(
        components,
        label="Tomorrow Need",
        raw=tomorrow_need if _known_state(tomorrow_need) else "missing",
        score=tomorrow_need_score,
        weight=0.03,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_tomorrow_need_repair_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "alignment",
            "Tomorrow Need",
            tomorrow_need_score,
            summary="Tomorrow Need now adds a small repair-planning signal, rewarding clearer, more restorative naming of what tomorrow actually needs.",
        ),
    )

    state_shift_intent = _state_float(_state_text(entities, "sensor.index_state_shift_intent_test_score"))
    chart = _score_entity_chart("sensor.index_state_shift_intent_test_score")
    _weighted_component(
        components,
        label="Intent Tested",
        raw=f"{state_shift_intent:.0f}%" if state_shift_intent is not None else "missing",
        score=state_shift_intent,
        weight=0.02,
        trend=chart["summary"] if chart else _trend_summary("sensor.index_state_shift_intent_test_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "alignment",
            "Intent Tested",
            state_shift_intent,
            summary="Logged state shifts now contribute a light Alignment signal by showing whether intent was actually tested and held under pressure.",
        ),
    )

    state_shift_response = _state_float(_state_text(entities, "sensor.index_state_shift_response_score"))
    chart = _score_entity_chart("sensor.index_state_shift_response_score")
    _weighted_component(
        components,
        label="State Shift Response",
        raw=f"{state_shift_response:.0f}%" if state_shift_response is not None else "missing",
        score=state_shift_response,
        weight=0.02,
        trend=chart["summary"] if chart else _trend_summary("sensor.index_state_shift_response_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "alignment",
            "State Shift Response",
            state_shift_response,
            summary="State shift responses now lightly support Alignment, rewarding responses that move back toward truth rather than reflexive escape.",
        ),
    )

    return _finalize_breakdown(components)


def _build_load_breakdown(entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    sleep_score_profile = _monthly_numeric_profile(
        "sensor.undercurrent_sleep_score",
        trim_extremes_for_mean=True,
    )
    base_hr_profile = _monthly_numeric_profile(
        "sensor.undercurrent_base_hr",
        trim_extremes_for_mean=True,
    )
    bedtime_profile = _monthly_undercurrent_bedtime_profile(trim_extremes_for_mean=True)

    v = _state_float(_state_text(entities, "sensor.undercurrent_morning_stress"))
    chart = _component_score_chart("sensor.undercurrent_morning_stress", _scale_score)
    _weighted_component(
        components,
        label="Morning Stress",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=_score_from_scale_1_to_5(v) if v is not None else None,
        weight=0.14,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_morning_stress", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric(
            "load",
            "Morning Stress",
            v,
            summary="Load treats higher morning stress as higher strain, so the 1-5 score rises directly with stress.",
        ),
    )

    drag = _state_text(entities, "sensor.undercurrent_main_drag")
    drag_score = _state_float(_state_text(entities, "sensor.undercurrent_main_drag_strain_score"))
    chart = _score_entity_chart("sensor.undercurrent_main_drag_strain_score")
    _weighted_component(
        components,
        label="Main Drag",
        raw=drag if drag not in {"unknown", "unavailable", "none", ""} else "missing",
        score=drag_score,
        weight=0.06,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_main_drag_strain_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "load",
            "Main Drag",
            drag_score,
            summary="Main Drag now scores the actual drag mix instead of mostly treating any single drag the same as any other.",
        ),
    )

    carryover = _state_text(entities, "sensor.undercurrent_carryover")
    carryover_repair = _state_float(_state_text(entities, "sensor.undercurrent_carryover_repair_score"))
    chart = _component_score_chart("sensor.undercurrent_carryover_repair_score", _inverse_identity_score)
    _weighted_component(
        components,
        label="Carryover",
        raw=carryover if _known_state(carryover) else "missing",
        score=(100 - carryover_repair) if carryover_repair is not None else None,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.undercurrent_carryover_repair_score",
            transform=lambda value: 100 - value,
        ),
        chart=chart,
        scoring=_inverse_passthrough_rubric(
            "load",
            "Carryover",
            carryover_repair,
            summary="Carryover now adds strain directly, so more residue from yesterday raises today's load instead of hiding behind broader categories.",
        ),
    )

    sleep_score = _state_float(_state_text(entities, "sensor.undercurrent_sleep_score"))
    minutes = _state_float(_state_text(entities, "sensor.aperture_sleep_duration"))
    hours = (minutes / 60) if minutes is not None else None
    bedtime_shifted, bedtime_display = _latest_undercurrent_bedtime_context(entities)
    personal_sleep_score = _profile_relative_score(
        sleep_score,
        sleep_score_profile,
        min_span=8,
        fallback=_fallback_wellness_score,
    )
    sleep_hours_score = _capacity_sleep_hours_score(hours) if hours is not None else None
    bedtime_score = _profile_relative_score(
        bedtime_shifted,
        bedtime_profile,
        inverse=True,
        min_span=90,
        fallback=_fallback_bedtime_score,
    )
    chart = _component_score_chart(
        "sensor.undercurrent_sleep_score",
        lambda raw, profile=sleep_score_profile: (
            100
            - _profile_relative_score(
                _state_float(raw),
                profile,
                min_span=8,
                fallback=_fallback_wellness_score,
            )
        )
        if _profile_relative_score(
            _state_float(raw),
            profile,
            min_span=8,
            fallback=_fallback_wellness_score,
        )
        is not None
        else None,
    )
    _weighted_component(
        components,
        label="Sleep Score Strain",
        raw=f"{sleep_score:.0f}" if sleep_score is not None else "missing",
        score=(100 - personal_sleep_score) if personal_sleep_score is not None else None,
        weight=0.04,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_sleep_score"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "load",
            "Sleep Score Strain",
            "Load now treats your sleep score as its own strain signal by inverting the personalized sleep-score component without blending in hours or bedtime.",
            profile=sleep_score_profile,
            current_value=sleep_score,
        ),
    )
    chart = _component_score_chart(
        "sensor.aperture_sleep_hours",
        lambda raw: _capacity_sleep_hours_score(hours_raw) if (hours_raw := _state_float(raw)) is not None else None,
    )
    _weighted_component(
        components,
        label="Sleep Hours Strain",
        raw=f"{hours:.2f}h" if hours is not None else "missing",
        score=(100 - sleep_hours_score) if sleep_hours_score is not None else None,
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.aperture_sleep_hours", suffix="h", decimals=2),
        chart=chart,
        scoring=_formula_rubric(
            "load",
            "Sleep Hours Strain",
            "Load now inverts the sleep-hours bucket directly, so shorter nights carry strain without being blended into another sleep metric.",
            "Inverse sleep duration buckets",
            note=(
                f"Current sleep duration is {hours:.2f}h. <5h scores 90 strain, 5-6h scores 70, 6-7h scores 45, 7-8h scores 20, and 8h+ scores 0."
                if hours is not None
                else "Sleep duration is missing."
            ),
        ),
    )
    chart = _component_score_chart(
        UNDERCURRENT_BEDTIME_SHIFTED_ENTITY,
        lambda raw, profile=bedtime_profile: (
            100
            - _profile_relative_score(
                _state_float(raw),
                profile,
                inverse=True,
                min_span=90,
                fallback=_fallback_bedtime_score,
            )
        )
        if _profile_relative_score(
            _state_float(raw),
            profile,
            inverse=True,
            min_span=90,
            fallback=_fallback_bedtime_score,
        )
        is not None
        else None,
    )
    _weighted_component(
        components,
        label="Bedtime Strain",
        raw=bedtime_display or "missing",
        score=(100 - bedtime_score) if bedtime_score is not None else None,
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary(UNDERCURRENT_BEDTIME_SHIFTED_ENTITY, suffix=" min"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "load",
            "Bedtime Strain",
            "Load now treats bedtime as its own strain signal by inverting how your latest bedtime compares to your recent norm.",
            profile=bedtime_profile,
            current_value=bedtime_shifted,
            inverse=True,
            suffix=" min",
            extra_note=f"Latest logged bedtime is {bedtime_display}." if bedtime_display else None,
        ),
    )

    base_hr = _state_float(_state_text(entities, "sensor.undercurrent_base_hr"))
    chart = _component_score_chart(
        "sensor.undercurrent_base_hr",
        lambda raw, profile=base_hr_profile: (
            100 - _base_hr_capacity_score(_state_float(raw), profile)
        )
        if _base_hr_capacity_score(_state_float(raw), profile) is not None
        else None,
    )
    _weighted_component(
        components,
        label="Base Heart Rate",
        raw=f"{base_hr:.0f} bpm" if base_hr is not None else "missing",
        score=(100 - _base_hr_capacity_score(base_hr, base_hr_profile)) if base_hr is not None else None,
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_base_hr", suffix=" bpm"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "load",
            "Base Heart Rate",
            "Load now looks at how elevated your sleeping base heart rate is versus your own last month, since a higher baseline means more bodily load before waking.",
            profile=base_hr_profile,
            current_value=base_hr,
            inverse=True,
            suffix=" bpm",
        ),
    )

    drift = _state_text(entities, "sensor.undercurrent_midday_drift")
    drift_score = None
    if drift == "better":
        drift_score = 20
    elif drift == "same":
        drift_score = 50
    elif drift == "worse":
        drift_score = 90
    chart = _component_score_chart("sensor.undercurrent_midday_drift", _load_midday_drift_score)
    _weighted_component(
        components,
        label="Midday Drift",
        raw=drift if drift not in {"unknown", "unavailable", "none", ""} else "missing",
        score=drift_score,
        weight=0.04,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_midday_drift"),
        chart=chart,
        scoring=_midday_drift_load_rubric("load", "Midday Drift", drift),
    )

    v = _state_float(_state_text(entities, "sensor.undercurrent_midday_energy"))
    chart = _component_score_chart("sensor.undercurrent_midday_energy", _midday_energy_load_score)
    _weighted_component(
        components,
        label="Midday Energy",
        raw=f"{v:.0f}/5" if v is not None else "missing",
        score=(100 - _score_from_scale_1_to_5(v)) if v is not None else None,
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_midday_energy", suffix="/5"),
        chart=chart,
        scoring=_five_point_scale_rubric(
            "load",
            "Midday Energy",
            v,
            inverse=True,
            summary="Lower midday energy raises Load, so the 1-5 scale is inverted before scoring.",
        ),
    )

    draining = _state_text(entities, "sensor.undercurrent_most_draining")
    draining_score = None
    if draining in ["work pressure", "conflict", "fatigue", "overstimulation", "social depletion"]:
        draining_score = 85
    elif draining in ["fragmented attention", "uncertainty", "lack of progress", "physical discomfort", "temptation"]:
        draining_score = 72
    elif draining not in {"unknown", "unavailable", "none", ""}:
        draining_score = 60
    chart = _component_score_chart("sensor.undercurrent_most_draining", _most_draining_score)
    _weighted_component(
        components,
        label="Most Draining",
        raw=draining if draining not in {"unknown", "unavailable", "none", ""} else "missing",
        score=draining_score,
        weight=0.04,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_most_draining"),
        chart=chart,
        scoring=_most_draining_rubric("load", "Most Draining", draining),
    )

    out_of_house = _state_float(_state_text(entities, "sensor.aperture_out_of_house_fragmentation_load"))
    chart = _score_entity_chart("sensor.aperture_out_of_house_fragmentation_load")
    _weighted_component(
        components,
        label="Out-of-House Fragmentation",
        raw=f"{out_of_house:.0f}%" if out_of_house is not None else "missing",
        score=out_of_house,
        weight=0.08,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_out_of_house_fragmentation_load"),
        chart=chart,
        scoring=_passthrough_rubric(
            "load",
            "Out-of-House Fragmentation",
            out_of_house,
            summary="Out-of-house fragmentation now contributes directly, capturing how much transit and place-switching are raising the day's cost.",
        ),
    )

    app_context = _state_float(_state_text(entities, "sensor.aperture_app_context_switch_load"))
    chart = _score_entity_chart("sensor.aperture_app_context_switch_load")
    _weighted_component(
        components,
        label="App Context Switch Load",
        raw=f"{app_context:.0f}%" if app_context is not None else "missing",
        score=app_context,
        weight=0.12,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_app_context_switch_load"),
        chart=chart,
        scoring=_passthrough_rubric(
            "load",
            "App Context Switch Load",
            app_context,
            summary="Load now treats context switching as a first-class strain source instead of a minor side modifier.",
        ),
    )

    night_disruption = _state_float(_state_text(entities, "sensor.aperture_night_disruption_load"))
    chart = _score_entity_chart("sensor.aperture_night_disruption_load")
    _weighted_component(
        components,
        label="Night Disruption Load",
        raw=f"{night_disruption:.0f}%" if night_disruption is not None else "missing",
        score=night_disruption,
        weight=0.08,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_night_disruption_load"),
        chart=chart,
        scoring=_passthrough_rubric(
            "load",
            "Night Disruption Load",
            night_disruption,
            summary="Night disruption now lands in Load directly, since interrupted recovery makes the whole day costlier.",
        ),
    )

    state_shift_intensity = _state_float(_state_text(entities, "sensor.index_state_shift_intensity_load_score"))
    avg_state_shift_intensity = _state_float(_state_text(entities, "sensor.index_state_shift_avg_intensity"))
    chart = _score_entity_chart("sensor.index_state_shift_intensity_load_score")
    _weighted_component(
        components,
        label="State Shift Intensity",
        raw=f"{avg_state_shift_intensity:.2f}" if avg_state_shift_intensity is not None else "missing",
        score=state_shift_intensity,
        weight=0.04,
        trend=chart["summary"] if chart else _trend_summary("sensor.index_state_shift_intensity_load_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "load",
            "State Shift Intensity",
            state_shift_intensity,
            summary="State Shift intensity now adds a live regulation-cost signal, so sharper internal swings contribute to Load instead of living only in notes.",
        ),
    )

    primary_disruptor = _state_text(entities, "sensor.undercurrent_primary_disruptor")
    chart = _component_score_chart("sensor.undercurrent_primary_disruptor", _primary_disruptor_load_score)
    _weighted_component(
        components,
        label="Primary Disruptor",
        raw=primary_disruptor if _known_state(primary_disruptor) else "missing",
        score=_primary_disruptor_load_score(primary_disruptor),
        weight=0.02,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_primary_disruptor"),
        chart=chart,
        scoring=_primary_disruptor_load_rubric("load", "Primary Disruptor", primary_disruptor),
    )

    meetings = _state_float(_state_text(entities, "sensor.undercurrent_work_meetings_count"))
    chart = _component_score_chart("sensor.undercurrent_work_meetings_count", _work_meetings_count_load_score)
    _weighted_component(
        components,
        label="Work Meetings",
        raw=f"{meetings:.0f}" if meetings is not None else "missing",
        score=_work_meetings_count_numeric_load_score(meetings),
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_work_meetings_count"),
        chart=chart,
        scoring=_work_meetings_count_rubric("load", "Work Meetings", meetings),
    )

    meeting_average_7d = _average_daily_numeric_value("sensor.undercurrent_work_meetings_count", days=7)
    _weighted_component(
        components,
        label="Meetings Last 7 Days",
        raw=f"{meeting_average_7d:.1f}/day" if meeting_average_7d is not None else "missing",
        score=_meeting_average_7d_load_score(meeting_average_7d),
        weight=0.02,
        trend=_recent_average_summary("sensor.undercurrent_work_meetings_count", days=7, decimals=1, suffix="/day"),
        chart=None,
        scoring=_meeting_average_7d_rubric("load", "Meetings Last 7 Days", meeting_average_7d),
    )

    after_work_hours = _state_float(_state_text(entities, "sensor.undercurrent_after_work_activity_count"))
    chart = _component_score_chart("sensor.undercurrent_after_work_activity_count", _after_work_activity_load_score)
    _weighted_component(
        components,
        label="After-Work Hours",
        raw=f"{after_work_hours:.2f}h" if after_work_hours is not None else "missing",
        score=_after_work_activity_numeric_load_score(after_work_hours),
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.undercurrent_after_work_activity_count",
            decimals=2,
            suffix="h",
        ),
        chart=chart,
        scoring=_after_work_activity_rubric("load", "After-Work Hours", after_work_hours),
    )

    busy_evenings_7d = _count_daily_values_at_or_above(
        "sensor.undercurrent_after_work_activity_count",
        AFTER_WORK_BUSY_THRESHOLD_HOURS,
        days=7,
    )
    _weighted_component(
        components,
        label="Busy Evenings Last 7 Days",
        raw=f"{busy_evenings_7d}/7 days" if busy_evenings_7d is not None else "missing",
        score=_busy_evenings_7d_load_score(float(busy_evenings_7d)) if busy_evenings_7d is not None else None,
        weight=0.03,
        trend=_recent_threshold_day_summary(
            "sensor.undercurrent_after_work_activity_count",
            AFTER_WORK_BUSY_THRESHOLD_HOURS,
            days=7,
            label="after-work hours",
        ),
        chart=None,
        scoring=_busy_evenings_7d_rubric(
            "load",
            "Busy Evenings Last 7 Days",
            float(busy_evenings_7d) if busy_evenings_7d is not None else None,
        ),
    )

    errands = _state_float(_state_text(entities, "sensor.undercurrent_errands_appointments_count"))
    chart = _component_score_chart("sensor.undercurrent_errands_appointments_count", _errands_appointments_load_score)
    _weighted_component(
        components,
        label="Errands / Appointments",
        raw=f"{errands:.0f}" if errands is not None else "missing",
        score=_errands_appointments_numeric_load_score(errands),
        weight=0.01,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_errands_appointments_count"),
        chart=chart,
        scoring=_errands_appointments_rubric("load", "Errands / Appointments", errands),
    )

    social_commitments = _state_float(_state_text(entities, "sensor.undercurrent_social_commitments_count"))
    chart = _component_score_chart("sensor.undercurrent_social_commitments_count", _social_commitments_load_score)
    _weighted_component(
        components,
        label="Social Commitments",
        raw=f"{social_commitments:.0f}" if social_commitments is not None else "missing",
        score=_social_commitments_numeric_load_score(social_commitments),
        weight=0.01,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_social_commitments_count"),
        chart=chart,
        scoring=_social_commitments_rubric("load", "Social Commitments", social_commitments),
    )

    busy_minutes = _state_float(_state_text(entities, "sensor.index_calendar_busy_minutes"))
    chart = _component_score_chart("sensor.index_calendar_busy_minutes", _busy_minutes_load_score)
    _weighted_component(
        components,
        label="Calendar Busy Minutes",
        raw=f"{busy_minutes:.0f} min" if busy_minutes is not None else "missing",
        score=_load_busy_minutes_score(busy_minutes) if busy_minutes is not None else None,
        weight=0.02,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.index_calendar_busy_minutes", suffix=" min"),
        chart=chart,
        scoring=_busy_minutes_load_rubric("load", "Calendar Busy Minutes", busy_minutes),
    )

    sedentary = _state_float(_state_text(entities, "sensor.index_sedentary_streak_min"))
    chart = _component_score_chart("sensor.index_sedentary_streak_min", _sedentary_streak_load_score)
    _weighted_component(
        components,
        label="Sedentary Streak",
        raw=f"{sedentary:.0f} min" if sedentary is not None else "missing",
        score=_load_sedentary_streak_score(sedentary) if sedentary is not None else None,
        weight=0.01,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.index_sedentary_streak_min", suffix=" min"),
        chart=chart,
        scoring=_sedentary_streak_load_rubric("load", "Sedentary Streak", sedentary),
    )

    return _finalize_breakdown(components, inverse=True)


def _build_steadiness_breakdown(entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    sleep_score_profile = _monthly_numeric_profile(
        "sensor.undercurrent_sleep_score",
        trim_extremes_for_mean=True,
    )
    bedtime_profile = _monthly_undercurrent_bedtime_profile(trim_extremes_for_mean=True)
    sleep_score = _state_float(_state_text(entities, "sensor.undercurrent_sleep_score"))
    sleep_hours = _first_known_float(entities, ["sensor.aperture_sleep_hours"])
    bedtime_shifted, bedtime_display = _latest_undercurrent_bedtime_context(entities)
    personal_sleep_score = _profile_relative_score(
        sleep_score,
        sleep_score_profile,
        min_span=8,
        fallback=_fallback_wellness_score,
    )
    sleep_hours_score = _capacity_sleep_hours_score(sleep_hours) if sleep_hours is not None else None
    bedtime_score = _profile_relative_score(
        bedtime_shifted,
        bedtime_profile,
        inverse=True,
        min_span=90,
        fallback=_fallback_bedtime_score,
    )

    chart = _component_score_chart(
        "sensor.undercurrent_sleep_score",
        lambda raw, profile=sleep_score_profile: _profile_relative_score(
            _state_float(raw),
            profile,
            min_span=8,
            fallback=_fallback_wellness_score,
        ),
    )
    _weighted_component(
        components,
        label="Sleep Score",
        raw=f"{sleep_score:.0f}" if sleep_score is not None else "missing",
        score=personal_sleep_score,
        weight=0.08,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.undercurrent_sleep_score"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "steadiness",
            "Sleep Score",
            "Steadiness uses your sleep score as its own recovery signal instead of folding it into a combined sleep metric.",
            profile=sleep_score_profile,
            current_value=sleep_score,
        ),
    )
    chart = _component_score_chart(
        "sensor.aperture_sleep_hours",
        lambda raw: _capacity_sleep_hours_score(hours_raw) if (hours_raw := _state_float(raw)) is not None else None,
    )
    _weighted_component(
        components,
        label="Sleep Hours",
        raw=f"{sleep_hours:.2f}h" if sleep_hours is not None else "missing",
        score=sleep_hours_score,
        weight=0.05,
        trend=chart["summary"] if chart else _numeric_trend_summary("sensor.aperture_sleep_hours", suffix="h", decimals=2),
        chart=chart,
        scoring=_formula_rubric(
            "steadiness",
            "Sleep Hours",
            "Steadiness treats sleep duration as its own recovery signal instead of hiding it inside a combined sleep score.",
            "Sleep duration buckets",
            note=(
                f"Current sleep duration is {sleep_hours:.2f}h. <5h scores 10, 5-6h scores 30, 6-7h scores 55, 7-8h scores 80, and 8h+ scores 100."
                if sleep_hours is not None
                else "Sleep duration is missing."
            ),
        ),
    )
    chart = _component_score_chart(
        UNDERCURRENT_BEDTIME_SHIFTED_ENTITY,
        lambda raw, profile=bedtime_profile: _profile_relative_score(
            _state_float(raw),
            profile,
            inverse=True,
            min_span=90,
            fallback=_fallback_bedtime_score,
        ),
    )
    _weighted_component(
        components,
        label="Bedtime",
        raw=bedtime_display or "missing",
        score=bedtime_score,
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary(UNDERCURRENT_BEDTIME_SHIFTED_ENTITY, suffix=" min"),
        chart=chart,
        scoring=_monthly_baseline_rubric(
            "steadiness",
            "Bedtime",
            "Steadiness treats bedtime separately, so a more settled bedtime supports recovery without being blended into the sleep score.",
            profile=bedtime_profile,
            current_value=bedtime_shifted,
            inverse=True,
            suffix=" min",
            extra_note=f"Latest logged bedtime is {bedtime_display}." if bedtime_display else None,
        ),
    )

    hrv = _state_float(_state_text(entities, "sensor.aperture_hrv_relative_score"))
    chart = _score_entity_chart("sensor.aperture_hrv_relative_score")
    _weighted_component(
        components,
        label="HRV Relative",
        raw=f"{hrv:.0f}%" if hrv is not None else "missing",
        score=hrv,
        weight=0.10,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_hrv_relative_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "HRV Relative",
            hrv,
            summary="HRV acts as a mostly passive regulation signal: better relative variability supports steadier recovery under load.",
        ),
    )

    base_hr = _state_float(_state_text(entities, "sensor.pneuma_personalized_base_hr_score"))
    chart = _score_entity_chart("sensor.pneuma_personalized_base_hr_score")
    _weighted_component(
        components,
        label="Base HR Recovery",
        raw=f"{base_hr:.0f}%" if base_hr is not None else "missing",
        score=base_hr,
        weight=0.05,
        trend=chart["summary"] if chart else _trend_summary("sensor.pneuma_personalized_base_hr_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "Base HR Recovery",
            base_hr,
            summary="A stronger base heart-rate recovery score suggests the body is returning closer to baseline.",
        ),
    )

    wind_down = _state_float(_state_text(entities, "sensor.aperture_wind_down_charge_consistency_score"))
    chart = _score_entity_chart("sensor.aperture_wind_down_charge_consistency_score")
    _weighted_component(
        components,
        label="Wind-Down Rhythm",
        raw=f"{wind_down:.0f}%" if wind_down is not None else "missing",
        score=wind_down,
        weight=0.09,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_wind_down_charge_consistency_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "Wind-Down Rhythm",
            wind_down,
            summary="Consistent wind-down behavior supports steadiness by lowering nighttime overactivation.",
        ),
    )

    home_protection = _state_float(_state_text(entities, "sensor.aperture_evening_home_protection_score"))
    chart = _score_entity_chart("sensor.aperture_evening_home_protection_score")
    _weighted_component(
        components,
        label="Evening Home Protection",
        raw=f"{home_protection:.0f}%" if home_protection is not None else "missing",
        score=home_protection,
        weight=0.05,
        trend=chart["summary"] if chart else _trend_summary("sensor.aperture_evening_home_protection_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "Evening Home Protection",
            home_protection,
            summary="Protected time at home gives the day room to settle instead of staying activated.",
        ),
    )

    regulation = _state_text(entities, "sensor.undercurrent_regulation_response")
    chart = _component_score_chart("sensor.undercurrent_regulation_response", _regulation_response_score)
    _weighted_component(
        components,
        label="Regulation Response",
        raw=regulation if _known_state(regulation) else "missing",
        score=_regulation_response_score(regulation),
        weight=0.07,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_regulation_response"),
        chart=chart,
        scoring=_regulation_response_rubric("steadiness", "Regulation Response", regulation),
    )

    most_restorative = _state_text(entities, "sensor.undercurrent_most_restorative")
    chart = _component_score_chart("sensor.undercurrent_most_restorative", _most_restorative_steadiness_score)
    _weighted_component(
        components,
        label="Most Restorative",
        raw=most_restorative if _known_state(most_restorative) else "missing",
        score=_most_restorative_steadiness_score(most_restorative),
        weight=0.03,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_most_restorative"),
        chart=chart,
        scoring=_most_restorative_rubric("steadiness", "Most Restorative", most_restorative),
    )

    state_shift = _state_text(entities, "sensor.undercurrent_state_shift")
    chart = _component_score_chart("sensor.undercurrent_state_shift", _undercurrent_state_shift_score)
    _weighted_component(
        components,
        label="State Shift",
        raw=state_shift if _known_state(state_shift) else "missing",
        score=_undercurrent_state_shift_score(state_shift),
        weight=0.05,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_state_shift"),
        chart=chart,
        scoring=_undercurrent_state_shift_rubric("steadiness", "State Shift", state_shift),
    )

    state_shift_intensity = _state_text(entities, "sensor.undercurrent_state_shift_intensity")
    chart = _component_score_chart("sensor.undercurrent_state_shift_intensity", _state_shift_intensity_score)
    _weighted_component(
        components,
        label="State Shift Intensity",
        raw=state_shift_intensity if _known_state(state_shift_intensity) else "missing",
        score=_state_shift_intensity_score(state_shift_intensity),
        weight=0.04,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_state_shift_intensity"),
        chart=chart,
        scoring=_state_shift_intensity_rubric("steadiness", "State Shift Intensity", state_shift_intensity),
    )

    state_shift_response = _state_float(_state_text(entities, "sensor.index_state_shift_response_score"))
    chart = _score_entity_chart("sensor.index_state_shift_response_score")
    _weighted_component(
        components,
        label="State Shift Response",
        raw=f"{state_shift_response:.0f}%" if state_shift_response is not None else "missing",
        score=state_shift_response,
        weight=0.05,
        trend=chart["summary"] if chart else _trend_summary("sensor.index_state_shift_response_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "State Shift Response",
            state_shift_response,
            summary="Logged state shift responses now support Steadiness directly, rewarding moves that actually re-center instead of escalating reactivity.",
        ),
    )

    state_shift_effect = _state_float(_state_text(entities, "sensor.index_state_shift_effect_score"))
    chart = _score_entity_chart("sensor.index_state_shift_effect_score")
    _weighted_component(
        components,
        label="State Shift Effect",
        raw=f"{state_shift_effect:.0f}%" if state_shift_effect is not None else "missing",
        score=state_shift_effect,
        weight=0.04,
        trend=chart["summary"] if chart else _trend_summary("sensor.index_state_shift_effect_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "State Shift Effect",
            state_shift_effect,
            summary="State shift effect now contributes directly, so shifts that genuinely move toward repair count more than shifts that only get logged.",
        ),
    )

    app_context = _state_float(_state_text(entities, "sensor.aperture_app_context_switch_load"))
    chart = _component_score_chart("sensor.aperture_app_context_switch_load", _inverse_identity_score)
    _weighted_component(
        components,
        label="App Context Switch Load",
        raw=f"{app_context:.0f}%" if app_context is not None else "missing",
        score=(100 - app_context) if app_context is not None else None,
        weight=0.04,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.aperture_app_context_switch_load",
            transform=lambda value: 100 - value,
        ),
        chart=chart,
        scoring=_inverse_passthrough_rubric(
            "steadiness",
            "App Context Switch Load",
            app_context,
            summary="Higher context-switch load signals overactivation, so it is inverted before contributing to Steadiness.",
        ),
    )

    notification_recovery = _state_float(_state_text(entities, "sensor.aperture_notification_recovery_load"))
    chart = _component_score_chart("sensor.aperture_notification_recovery_load", _inverse_identity_score)
    _weighted_component(
        components,
        label="Notification Recovery Load",
        raw=f"{notification_recovery:.0f}%" if notification_recovery is not None else "missing",
        score=(100 - notification_recovery) if notification_recovery is not None else None,
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.aperture_notification_recovery_load",
            transform=lambda value: 100 - value,
        ),
        chart=chart,
        scoring=_inverse_passthrough_rubric(
            "steadiness",
            "Notification Recovery Load",
            notification_recovery,
            summary="Notification recovery load is inverted before contributing, so quicker recovery from spikes helps Steadiness.",
        ),
    )

    night_disruption = _state_float(_state_text(entities, "sensor.aperture_night_disruption_load"))
    chart = _component_score_chart("sensor.aperture_night_disruption_load", _inverse_identity_score)
    _weighted_component(
        components,
        label="Night Disruption Load",
        raw=f"{night_disruption:.0f}%" if night_disruption is not None else "missing",
        score=(100 - night_disruption) if night_disruption is not None else None,
        weight=0.03,
        trend=chart["summary"] if chart else _numeric_trend_summary(
            "sensor.aperture_night_disruption_load",
            transform=lambda value: 100 - value,
        ),
        chart=chart,
        scoring=_inverse_passthrough_rubric(
            "steadiness",
            "Night Disruption Load",
            night_disruption,
            summary="Night disruptions raise overactivation, so this component uses the inverse of the load score.",
        ),
    )

    carryover = _state_text(entities, "sensor.undercurrent_carryover")
    carryover_repair = _state_float(_state_text(entities, "sensor.undercurrent_carryover_repair_score"))
    chart = _score_entity_chart("sensor.undercurrent_carryover_repair_score")
    _weighted_component(
        components,
        label="Carryover Repair",
        raw=carryover if _known_state(carryover) else "missing",
        score=carryover_repair,
        weight=0.03,
        trend=chart["summary"] if chart else _trend_summary("sensor.undercurrent_carryover_repair_score"),
        chart=chart,
        scoring=_passthrough_rubric(
            "steadiness",
            "Carryover Repair",
            carryover_repair,
            summary="Carryover repair now helps Steadiness directly, since less residue from yesterday leaves the system easier to settle today.",
        ),
    )

    primary_disruptor = _state_text(entities, "sensor.undercurrent_primary_disruptor")
    chart = _component_score_chart("sensor.undercurrent_primary_disruptor", _primary_disruptor_score)
    _weighted_component(
        components,
        label="Primary Disruptor",
        raw=primary_disruptor if _known_state(primary_disruptor) else "missing",
        score=_primary_disruptor_score(primary_disruptor),
        weight=0.02,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_primary_disruptor"),
        chart=chart,
        scoring=_primary_disruptor_rubric("steadiness", "Primary Disruptor", primary_disruptor),
    )

    midday_drift = _state_text(entities, "sensor.undercurrent_midday_drift")
    chart = _component_score_chart("sensor.undercurrent_midday_drift", _midday_drift_score)
    _weighted_component(
        components,
        label="Midday Drift",
        raw=midday_drift if _known_state(midday_drift) else "missing",
        score=_midday_drift_score(midday_drift),
        weight=0.02,
        trend=chart["summary"] if chart else _text_trend_summary("sensor.undercurrent_midday_drift"),
        chart=chart,
        scoring=_midday_drift_alignment_rubric("steadiness", "Midday Drift", midday_drift),
    )

    return _finalize_breakdown(components)


PNEUMA_SOURCE_ENTITY_IDS = [
    "sensor.undercurrent_morning_energy",
    "sensor.undercurrent_morning_clarity",
    "sensor.undercurrent_morning_mood",
    "sensor.undercurrent_morning_wellness",
    "sensor.undercurrent_morning_state_tags",
    "sensor.undercurrent_morning_state_capacity_score",
    "sensor.undercurrent_sleep_score",
    UNDERCURRENT_BEDTIME_ENTITY,
    UNDERCURRENT_BEDTIME_SHIFTED_ENTITY,
    "sensor.aperture_sleep_hours",
    "sensor.aperture_sleep_duration",
    "sensor.aperture_resting_heart_rate",
    "sensor.undercurrent_base_hr",
    "sensor.undercurrent_midday_energy",
    "sensor.undercurrent_midday_focus",
    "sensor.undercurrent_midday_wellness",
    "sensor.undercurrent_morning_midday_wellness_drop",
    "sensor.undercurrent_evening_wellness",
    "sensor.undercurrent_midday_evening_wellness_drop",
    "sensor.undercurrent_morning_spiritual_orientation",
    "sensor.undercurrent_daily_intent",
    "sensor.undercurrent_midday_drift",
    "sensor.undercurrent_midday_need",
    "sensor.undercurrent_evening_spiritual_orientation",
    "sensor.undercurrent_alignment",
    "sensor.undercurrent_day_score",
    "sensor.undercurrent_state_shift",
    "sensor.undercurrent_state_shift_intensity",
    "sensor.undercurrent_regulation_response",
    "sensor.undercurrent_primary_disruptor",
    "sensor.undercurrent_most_restorative",
    "sensor.rhythmic_rite_abiding_complete",
    "sensor.rhythmic_rite_abiding_last_7_days",
    "sensor.signal_field_weighted_presence_today",
    "sensor.signal_field_presence_hours_today",
    "sensor.undercurrent_carryover",
    "sensor.undercurrent_carryover_repair_score",
    "sensor.undercurrent_neglected_domain",
    "sensor.undercurrent_neglected_domain_support_score",
    "sensor.undercurrent_tomorrow_need",
    "sensor.undercurrent_tomorrow_need_repair_score",
    "sensor.undercurrent_morning_stress",
    "sensor.undercurrent_main_drag",
    "sensor.undercurrent_main_drag_strain_score",
    "sensor.undercurrent_most_draining",
    "sensor.undercurrent_work_meetings_count",
    "sensor.undercurrent_after_work_activity_count",
    "sensor.undercurrent_errands_appointments_count",
    "sensor.undercurrent_social_commitments_count",
    "sensor.index_calendar_busy_minutes",
    "sensor.index_sedentary_streak_min",
    "sensor.index_state_shift_intensity_load_score",
    "sensor.index_state_shift_response_score",
    "sensor.index_state_shift_effect_score",
    "sensor.index_state_shift_intent_test_score",
    "sensor.aperture_hrv_relative_score",
    "sensor.aperture_wind_down_charge_consistency_score",
    "sensor.aperture_morning_pickup_delay_score",
    "sensor.aperture_evening_home_protection_score",
    "sensor.aperture_restorative_place_score",
    "sensor.aperture_out_of_house_fragmentation_load",
    "sensor.aperture_app_context_switch_load",
    "sensor.aperture_activity_pattern_load",
    "sensor.aperture_night_disruption_load",
    "sensor.aperture_notification_recovery_load",
]

PNEUMA_SCORECARD_ENTITY_MAP = {
    "personalized_base_hr_score": "sensor.pneuma_personalized_base_hr_score",
    "personalized_morning_wellness_score": "sensor.pneuma_personalized_morning_wellness_score",
    "personalized_midday_wellness_raw_score": "sensor.pneuma_personalized_midday_wellness_raw_score",
    "personalized_midday_wellness_delta_score": "sensor.pneuma_personalized_midday_wellness_delta_score",
    "personalized_midday_wellness_score": "sensor.pneuma_personalized_midday_wellness_score",
    "personalized_evening_wellness_raw_score": "sensor.pneuma_personalized_evening_wellness_raw_score",
    "personalized_evening_wellness_delta_score": "sensor.pneuma_personalized_evening_wellness_delta_score",
    "personalized_evening_wellness_score": "sensor.pneuma_personalized_evening_wellness_score",
    "personalized_sleep_score": "sensor.pneuma_personalized_sleep_score",
    "personalized_sleep_hours_score": "sensor.pneuma_personalized_sleep_hours_score",
    "personalized_bedtime_score": "sensor.pneuma_personalized_bedtime_score",
    "personalized_sleep_recovery_score": "sensor.pneuma_personalized_sleep_recovery_score",
    "capacity_score": "sensor.pneuma_capacity_score",
    "capacity_confidence": "sensor.pneuma_capacity_confidence",
    "alignment_score": "sensor.pneuma_alignment_score",
    "alignment_confidence": "sensor.pneuma_alignment_confidence",
    "load_score": "sensor.pneuma_load_score",
    "load_confidence": "sensor.pneuma_load_confidence",
    "steadiness_score": "sensor.pneuma_steadiness_score",
    "steadiness_confidence": "sensor.pneuma_steadiness_confidence",
    "resonance_score": "sensor.pneuma_resonance_score",
    "resonance_confidence": "sensor.pneuma_resonance_confidence",
    "daily_status": "sensor.pneuma_daily_status",
}


def _round_score(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value))


def _apply_score_delta(value: int | None, delta: int) -> int | None:
    if value is None:
        return None
    return _round_score(_clamp_score(float(value) + float(delta)))


def _quest_bonus_label(value: int | None) -> str | None:
    amount = int(round(float(value or 0)))
    if amount <= 0:
        return None
    return f"+{amount}%"


def _score_confidence(parts: list[tuple[float | None, float]]) -> int:
    return int(round(sum(weight for score, weight in parts if score is not None) * 100))


def _weighted_score_value(parts: list[tuple[float | None, float]], *, default: int | None = None) -> int | None:
    score = _weighted_average_score(parts)
    if score is None:
        return default
    return _round_score(score)


def _pneuma_daily_status_label(capacity: int, alignment: int, load: int, steadiness: int) -> str:
    if capacity >= 78 and alignment >= 76 and load <= 40 and steadiness >= 70:
        return "Strong / Stable"
    if alignment >= 65 and load >= 60 and steadiness >= 65:
        return "Pressured but Holding"
    if capacity < 45 and (load >= 68 or steadiness < 45):
        return "Depleted / Under Pressure"
    if capacity < 50 and steadiness >= 55:
        return "Running Thin"
    if capacity >= 60 and alignment < 50:
        return "Able but Misaligned"
    if alignment < 45 or (alignment < 55 and steadiness < 55):
        return "Drifting"
    return "Mixed / Watch"


def _scorecard_entities(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for key, entity_id in PNEUMA_SCORECARD_ENTITY_MAP.items():
        value = payload.get(key)
        entities[entity_id] = {
            "entity_id": entity_id,
            "state": "unknown" if value is None else str(value),
        }
    return entities


def get_pneuma_scorecard(
    entities: dict[str, dict[str, Any]] | None = None,
    behavioral: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entities = _merge_behavioral_signal_entities(dict(entities or _load_ha_entities(PNEUMA_SOURCE_ENTITY_IDS)), behavioral)

    base_hr = _state_float(_state_text(entities, "sensor.undercurrent_base_hr"))
    morning_wellness = _state_float(_state_text(entities, "sensor.undercurrent_morning_wellness"))
    midday_wellness = _state_float(_state_text(entities, "sensor.undercurrent_midday_wellness"))
    evening_wellness = _state_float(_state_text(entities, "sensor.undercurrent_evening_wellness"))
    sleep_score = _state_float(_state_text(entities, "sensor.undercurrent_sleep_score"))
    sleep_hours = _state_float(_state_text(entities, "sensor.aperture_sleep_hours"))
    if sleep_hours is None:
        sleep_minutes = _state_float(_state_text(entities, "sensor.aperture_sleep_duration"))
        sleep_hours = round(sleep_minutes / 60.0, 2) if sleep_minutes is not None else None

    bedtime_shifted = _state_float(_state_text(entities, UNDERCURRENT_BEDTIME_SHIFTED_ENTITY))
    if bedtime_shifted is None:
        bedtime_parts = _bedtime_parts(_state_text(entities, UNDERCURRENT_BEDTIME_ENTITY))
        if bedtime_parts is not None:
            bedtime_shifted = _shifted_bedtime_minutes(*bedtime_parts)

    morning_midday_drop = _state_float(_state_text(entities, "sensor.undercurrent_morning_midday_wellness_drop"))
    if morning_midday_drop is None and morning_wellness is not None and midday_wellness is not None:
        morning_midday_drop = round(morning_wellness - midday_wellness, 1)

    midday_evening_drop = _state_float(_state_text(entities, "sensor.undercurrent_midday_evening_wellness_drop"))
    if midday_evening_drop is None and midday_wellness is not None and evening_wellness is not None:
        midday_evening_drop = round(midday_wellness - evening_wellness, 1)

    base_hr_profile = _monthly_numeric_profile(
        "sensor.undercurrent_base_hr",
        trim_extremes_for_mean=True,
    )
    morning_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_morning_wellness",
        trim_extremes_for_mean=True,
    )
    midday_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_midday_wellness",
        trim_extremes_for_mean=True,
    )
    evening_wellness_profile = _monthly_numeric_profile(
        "sensor.undercurrent_evening_wellness",
        trim_extremes_for_mean=True,
    )
    sleep_score_profile = _monthly_numeric_profile(
        "sensor.undercurrent_sleep_score",
        trim_extremes_for_mean=True,
    )
    bedtime_profile = _monthly_undercurrent_bedtime_profile(trim_extremes_for_mean=True)
    morning_midday_drop_profile = _monthly_numeric_profile(
        "sensor.undercurrent_morning_midday_wellness_drop",
        trim_extremes_for_mean=True,
    )
    midday_evening_drop_profile = _monthly_numeric_profile(
        "sensor.undercurrent_midday_evening_wellness_drop",
        trim_extremes_for_mean=True,
    )
    meeting_average_7d = _average_daily_numeric_value("sensor.undercurrent_work_meetings_count", days=7)
    busy_evenings_7d = _count_daily_values_at_or_above(
        "sensor.undercurrent_after_work_activity_count",
        AFTER_WORK_BUSY_THRESHOLD_HOURS,
        days=7,
    )

    personalized_base_hr_score = _round_score(_base_hr_capacity_score(base_hr, base_hr_profile))
    personalized_morning_wellness_score = _round_score(_morning_wellness_score(morning_wellness, morning_wellness_profile))
    personalized_midday_wellness_raw_score = _round_score(_morning_wellness_score(midday_wellness, midday_wellness_profile))
    personalized_midday_wellness_delta_score = _round_score(_phase_drop_score(morning_midday_drop, morning_midday_drop_profile))
    personalized_midday_wellness_score = _weighted_score_value(
        [
            (None if personalized_midday_wellness_raw_score is None else float(personalized_midday_wellness_raw_score), 0.6),
            (None if personalized_midday_wellness_delta_score is None else float(personalized_midday_wellness_delta_score), 0.4),
        ]
    )
    personalized_evening_wellness_raw_score = _round_score(_morning_wellness_score(evening_wellness, evening_wellness_profile))
    personalized_evening_wellness_delta_score = _round_score(_phase_drop_score(midday_evening_drop, midday_evening_drop_profile))
    personalized_evening_wellness_score = _weighted_score_value(
        [
            (None if personalized_evening_wellness_raw_score is None else float(personalized_evening_wellness_raw_score), 0.6),
            (None if personalized_evening_wellness_delta_score is None else float(personalized_evening_wellness_delta_score), 0.4),
        ]
    )
    personalized_sleep_score = _round_score(
        _profile_relative_score(
            sleep_score,
            sleep_score_profile,
            min_span=8,
            fallback=_fallback_wellness_score,
        )
    )
    personalized_sleep_hours_score = _round_score(_capacity_sleep_hours_score(sleep_hours) if sleep_hours is not None else None)
    personalized_bedtime_score = _round_score(
        _profile_relative_score(
            bedtime_shifted,
            bedtime_profile,
            inverse=True,
            min_span=90,
            fallback=_fallback_bedtime_score,
        )
    )
    personalized_sleep_recovery_score = _weighted_score_value(
        [
            (None if personalized_sleep_score is None else float(personalized_sleep_score), 0.55),
            (None if personalized_sleep_hours_score is None else float(personalized_sleep_hours_score), 0.30),
            (None if personalized_bedtime_score is None else float(personalized_bedtime_score), 0.15),
        ]
    )

    capacity_parts = [
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_morning_energy"))), 0.17),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_morning_clarity"))), 0.17),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_morning_mood"))), 0.05),
        (None if personalized_morning_wellness_score is None else float(personalized_morning_wellness_score), 0.14),
        (None if personalized_sleep_score is None else float(personalized_sleep_score), 0.11),
        (None if personalized_sleep_hours_score is None else float(personalized_sleep_hours_score), 0.05),
        (None if personalized_bedtime_score is None else float(personalized_bedtime_score), 0.03),
        (None if personalized_base_hr_score is None else float(personalized_base_hr_score), 0.06),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_midday_energy"))), 0.05),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_midday_focus"))), 0.04),
        (None if personalized_midday_wellness_raw_score is None else float(personalized_midday_wellness_raw_score), 0.03),
        (None if personalized_midday_wellness_delta_score is None else float(personalized_midday_wellness_delta_score), 0.02),
        (None if personalized_evening_wellness_raw_score is None else float(personalized_evening_wellness_raw_score), 0.02),
        (None if personalized_evening_wellness_delta_score is None else float(personalized_evening_wellness_delta_score), 0.02),
        (_state_float(_state_text(entities, "sensor.undercurrent_morning_state_capacity_score")), 0.03),
        (_state_float(_state_text(entities, "sensor.aperture_hrv_relative_score")), 0.01),
    ]
    alignment_parts = [
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_morning_spiritual_orientation"))), 0.22),
        (100.0 if _known_state(_state_text(entities, "sensor.undercurrent_daily_intent")) else None, 0.09),
        (_midday_drift_score(_state_text(entities, "sensor.undercurrent_midday_drift")), 0.08),
        (_midday_need_score(_state_text(entities, "sensor.undercurrent_midday_need")), 0.04),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_evening_spiritual_orientation"))), 0.05),
        (_alignment_choice_score(_state_text(entities, "sensor.undercurrent_alignment")), 0.11),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.undercurrent_day_score"))), 0.05),
        (_abiding_completion_score(_state_text(entities, "sensor.rhythmic_rite_abiding_complete")), 0.09),
        (_abiding_last_7_days_numeric_score(_state_float(_state_text(entities, "sensor.rhythmic_rite_abiding_last_7_days"))), 0.07),
        (_score_from_scale_1_to_5(_state_float(_state_text(entities, "sensor.signal_field_weighted_presence_today"))), 0.05),
        (_signal_presence_hours_score(_state_text(entities, "sensor.signal_field_presence_hours_today")), 0.03),
        (_state_float(_state_text(entities, "sensor.undercurrent_carryover_repair_score")), 0.05),
        (_state_float(_state_text(entities, "sensor.undercurrent_neglected_domain_support_score")), 0.04),
        (_state_float(_state_text(entities, "sensor.undercurrent_tomorrow_need_repair_score")), 0.03),
        (_state_float(_state_text(entities, "sensor.index_state_shift_intent_test_score")), 0.02),
        (_state_float(_state_text(entities, "sensor.index_state_shift_response_score")), 0.02),
    ]
    load_parts = [
        (_scale_score(_state_text(entities, "sensor.undercurrent_morning_stress")), 0.14),
        (_state_float(_state_text(entities, "sensor.undercurrent_main_drag_strain_score")), 0.06),
        (_inverse_identity_score(_state_text(entities, "sensor.undercurrent_carryover_repair_score")), 0.05),
        (_sleep_penalty_score(None if personalized_sleep_score is None else str(personalized_sleep_score)), 0.04),
        (_sleep_penalty_score(None if personalized_sleep_hours_score is None else str(personalized_sleep_hours_score)), 0.02),
        (_sleep_penalty_score(None if personalized_bedtime_score is None else str(personalized_bedtime_score)), 0.02),
        (_sleep_penalty_score(None if personalized_base_hr_score is None else str(personalized_base_hr_score)), 0.03),
        (_load_midday_drift_score(_state_text(entities, "sensor.undercurrent_midday_drift")), 0.04),
        (_midday_energy_load_score(_state_text(entities, "sensor.undercurrent_midday_energy")), 0.02),
        (_most_draining_score(_state_text(entities, "sensor.undercurrent_most_draining")), 0.04),
        (_state_float(_state_text(entities, "sensor.aperture_out_of_house_fragmentation_load")), 0.08),
        (_state_float(_state_text(entities, "sensor.aperture_app_context_switch_load")), 0.12),
        (_state_float(_state_text(entities, "sensor.aperture_night_disruption_load")), 0.08),
        (_state_float(_state_text(entities, "sensor.aperture_notification_recovery_load")), 0.08),
        (_state_float(_state_text(entities, "sensor.index_state_shift_intensity_load_score")), 0.04),
        (_primary_disruptor_load_score(_state_text(entities, "sensor.undercurrent_primary_disruptor")), 0.02),
        (_work_meetings_count_numeric_load_score(_state_float(_state_text(entities, "sensor.undercurrent_work_meetings_count"))), 0.02),
        (_meeting_average_7d_load_score(meeting_average_7d), 0.02),
        (_after_work_activity_numeric_load_score(_state_float(_state_text(entities, "sensor.undercurrent_after_work_activity_count"))), 0.02),
        (_busy_evenings_7d_load_score(float(busy_evenings_7d)) if busy_evenings_7d is not None else None, 0.03),
        (_errands_appointments_numeric_load_score(_state_float(_state_text(entities, "sensor.undercurrent_errands_appointments_count"))), 0.01),
        (_social_commitments_numeric_load_score(_state_float(_state_text(entities, "sensor.undercurrent_social_commitments_count"))), 0.01),
        (_busy_minutes_load_score(_state_text(entities, "sensor.index_calendar_busy_minutes")), 0.02),
        (_sedentary_streak_load_score(_state_text(entities, "sensor.index_sedentary_streak_min")), 0.01),
    ]
    steadiness_parts = [
        (None if personalized_sleep_score is None else float(personalized_sleep_score), 0.08),
        (None if personalized_sleep_hours_score is None else float(personalized_sleep_hours_score), 0.05),
        (None if personalized_bedtime_score is None else float(personalized_bedtime_score), 0.03),
        (_state_float(_state_text(entities, "sensor.aperture_hrv_relative_score")), 0.10),
        (None if personalized_base_hr_score is None else float(personalized_base_hr_score), 0.05),
        (_state_float(_state_text(entities, "sensor.aperture_wind_down_charge_consistency_score")), 0.09),
        (_state_float(_state_text(entities, "sensor.aperture_evening_home_protection_score")), 0.05),
        (_regulation_response_score(_state_text(entities, "sensor.undercurrent_regulation_response")), 0.07),
        (_undercurrent_state_shift_score(_state_text(entities, "sensor.undercurrent_state_shift")), 0.05),
        (_state_shift_intensity_score(_state_text(entities, "sensor.undercurrent_state_shift_intensity")), 0.04),
        (_state_float(_state_text(entities, "sensor.index_state_shift_response_score")), 0.05),
        (_state_float(_state_text(entities, "sensor.index_state_shift_effect_score")), 0.04),
        (_inverse_identity_score(_state_text(entities, "sensor.aperture_app_context_switch_load")), 0.04),
        (_inverse_identity_score(_state_text(entities, "sensor.aperture_notification_recovery_load")), 0.03),
        (_inverse_identity_score(_state_text(entities, "sensor.aperture_night_disruption_load")), 0.03),
        (_most_restorative_steadiness_score(_state_text(entities, "sensor.undercurrent_most_restorative")), 0.03),
        (_state_float(_state_text(entities, "sensor.undercurrent_carryover_repair_score")), 0.03),
        (_primary_disruptor_score(_state_text(entities, "sensor.undercurrent_primary_disruptor")), 0.02),
        (_midday_drift_score(_state_text(entities, "sensor.undercurrent_midday_drift")), 0.02),
    ]

    capacity_score = _weighted_score_value(capacity_parts, default=50)
    alignment_score = _weighted_score_value(alignment_parts, default=50)
    load_score = _weighted_score_value(load_parts, default=50)
    steadiness_score = _weighted_score_value(steadiness_parts, default=50)

    quest_linger = get_quest_linger_bonus()
    capacity_score = _apply_score_delta(capacity_score, quest_linger["capacity_bonus"])
    alignment_score = _apply_score_delta(alignment_score, quest_linger["alignment_bonus"])
    load_score = _apply_score_delta(load_score, -quest_linger["headroom_bonus"])
    steadiness_score = _apply_score_delta(steadiness_score, quest_linger["steadiness_bonus"])

    capacity_confidence = _score_confidence(capacity_parts)
    alignment_confidence = _score_confidence(alignment_parts)
    load_confidence = _score_confidence(load_parts)
    steadiness_confidence = _score_confidence(steadiness_parts)

    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "personalized_base_hr_score": personalized_base_hr_score,
        "personalized_morning_wellness_score": personalized_morning_wellness_score,
        "personalized_midday_wellness_raw_score": personalized_midday_wellness_raw_score,
        "personalized_midday_wellness_delta_score": personalized_midday_wellness_delta_score,
        "personalized_midday_wellness_score": personalized_midday_wellness_score,
        "personalized_evening_wellness_raw_score": personalized_evening_wellness_raw_score,
        "personalized_evening_wellness_delta_score": personalized_evening_wellness_delta_score,
        "personalized_evening_wellness_score": personalized_evening_wellness_score,
        "personalized_sleep_score": personalized_sleep_score,
        "personalized_sleep_hours_score": personalized_sleep_hours_score,
        "personalized_bedtime_score": personalized_bedtime_score,
        "personalized_sleep_recovery_score": personalized_sleep_recovery_score,
        "capacity_score": capacity_score,
        "capacity_confidence": capacity_confidence,
        "quest_capacity_bonus": quest_linger["capacity_bonus"],
        "alignment_score": alignment_score,
        "alignment_confidence": alignment_confidence,
        "quest_alignment_bonus": quest_linger["alignment_bonus"],
        "load_score": load_score,
        "load_confidence": load_confidence,
        "quest_headroom_bonus": quest_linger["headroom_bonus"],
        "steadiness_score": steadiness_score,
        "steadiness_confidence": steadiness_confidence,
        "quest_steadiness_bonus": quest_linger["steadiness_bonus"],
        "quest_linger_count": len(quest_linger["details"]),
        "quest_linger_details": quest_linger["details"],
        "resonance_score": steadiness_score,
        "resonance_confidence": steadiness_confidence,
        "daily_status": _pneuma_daily_status_label(capacity_score or 50, alignment_score or 50, load_score or 50, steadiness_score or 50),
    }


def get_pneuma_scores() -> dict[str, Any]:
    try:
        behavioral = _behavioral_signal_suite()
    except Exception:
        behavioral = {}

    entities = _merge_behavioral_signal_entities(_load_ha_entities(PNEUMA_SOURCE_ENTITY_IDS), behavioral)
    scorecard = get_pneuma_scorecard(entities, behavioral=behavioral)
    entities.update(_scorecard_entities(scorecard))

    capacity = _pneuma_card(
        entities,
        "sensor.pneuma_capacity_score",
        "sensor.pneuma_capacity_confidence",
    )
    capacity["breakdown"] = _build_capacity_breakdown(entities)
    capacity["chart"] = _score_entity_chart("sensor.pneuma_capacity_score")
    capacity["trend"] = capacity["chart"]["summary"] if capacity["chart"] else _trend_summary("sensor.pneuma_capacity_score")
    capacity["details_id"] = "pneuma-capacity-dialog"
    capacity["display_name"] = "Capacity"
    alignment = _pneuma_card(
        entities,
        "sensor.pneuma_alignment_score",
        "sensor.pneuma_alignment_confidence",
    )
    alignment["breakdown"] = _build_alignment_breakdown(entities)
    alignment["chart"] = _score_entity_chart("sensor.pneuma_alignment_score")
    alignment["trend"] = alignment["chart"]["summary"] if alignment["chart"] else _trend_summary("sensor.pneuma_alignment_score")
    alignment["details_id"] = "pneuma-alignment-dialog"
    alignment["display_name"] = "Alignment"
    load = _pneuma_card(
        entities,
        "sensor.pneuma_load_score",
        "sensor.pneuma_load_confidence",
        display_transform=_invert_percent_score,
    )
    load["breakdown"] = _build_load_breakdown(entities)
    load["chart"] = _component_score_chart("sensor.pneuma_load_score", _inverse_identity_score)
    load["trend"] = (
        load["chart"]["summary"]
        if load["chart"]
        else _numeric_trend_summary("sensor.pneuma_load_score", transform=_invert_percent_score)
    )
    load["details_id"] = "pneuma-load-dialog"
    load["display_name"] = "Headroom"
    load["breakdown_note"] = (
        "Headroom is the inverse of the underlying Load model. Higher is better: "
        "the same signals that raise load will lower headroom. The rubric popovers "
        "still describe the underlying load mapping."
    )

    resonance = _pneuma_card(
        entities,
        "sensor.pneuma_steadiness_score",
        "sensor.pneuma_steadiness_confidence",
    )
    resonance["breakdown"] = _build_steadiness_breakdown(entities)
    resonance["chart"] = _score_entity_chart("sensor.pneuma_steadiness_score")
    resonance["trend"] = (
        resonance["chart"]["summary"]
        if resonance["chart"]
        else _trend_summary("sensor.pneuma_steadiness_score")
    )
    resonance["details_id"] = "pneuma-steadiness-dialog"
    resonance["display_name"] = "Steadiness"

    for card, bonus_key in (
        (capacity, "quest_capacity_bonus"),
        (alignment, "quest_alignment_bonus"),
        (load, "quest_headroom_bonus"),
        (resonance, "quest_steadiness_bonus"),
    ):
        bonus_value = int(scorecard.get(bonus_key) or 0)
        card["quest_bonus"] = bonus_value
        card["quest_bonus_label"] = _quest_bonus_label(bonus_value)

    status_state = (entities.get("sensor.pneuma_daily_status") or {}).get("state", "unknown")
    status_known = status_state not in {"unknown", "unavailable", "none", "", None}

    return {
        "available": capacity["known"] or alignment["known"] or load["known"] or resonance["known"] or status_known,
        "capacity": capacity,
        "alignment": alignment,
        "load": load,
        "steadiness": resonance,
        "resonance": resonance,
        "status": status_state if status_known else "Waiting on Home Assistant reload",
        "status_known": status_known,
        "status_tone": _status_tone(status_state, status_known),
    }


def _time_of_day(now: datetime | None = None) -> str:
    local_now = now or datetime.now(TZ)
    hour = local_now.hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "midday"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _first_known_state(entities: dict[str, dict[str, Any]], entity_ids: list[str]) -> str | None:
    for entity_id in entity_ids:
        value = _state_text(entities, entity_id)
        if _known_state(value):
            return value
    return None


def _first_known_float(entities: dict[str, dict[str, Any]], entity_ids: list[str]) -> float | None:
    raw = _first_known_state(entities, entity_ids)
    return _state_float(raw)


def _first_known_int(entities: dict[str, dict[str, Any]], entity_ids: list[str]) -> int | None:
    value = _first_known_float(entities, entity_ids)
    if value is None:
        return None
    return int(round(value))


def _float_or_none(value: Any) -> float | None:
    return _state_float(value)


def _int_or_none(value: Any) -> int | None:
    numeric = _state_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _intent_list_from_state(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [part.strip() for part in re.split(r"[|,;/\n]+", raw) if part.strip()]


def build_index_telemetry() -> TodayTelemetry:
    entity_ids = [
        "sensor.undercurrent_morning_mood",
        "sensor.undercurrent_morning_clarity",
        "sensor.undercurrent_morning_stress",
        "sensor.undercurrent_main_drag",
        "sensor.undercurrent_daily_intent",
        "sensor.undercurrent_date",
        "sensor.aperture_sleep_hours",
        "sensor.aperture_sleep_duration",
        "sensor.aperture_resting_heart_rate",
        "sensor.aperture_daily_steps",
        "sensor.aperture_active_notification_count",
        "sensor.index_sedentary_streak_min",
        "sensor.index_unlocks_per_hour",
        "sensor.index_late_night_screen_min",
        "sensor.index_screen_total_min",
        "sensor.index_screen_work_min",
        "sensor.index_screen_entertainment_min",
        "sensor.index_screen_social_min",
        "sensor.index_calendar_meetings_count",
        "sensor.index_calendar_busy_minutes",
        "sensor.index_home_media_minutes",
        "sensor.index_top_tasks",
        "input_text.index_top_tasks",
        "sensor.index_stop_doing",
        "input_text.index_stop_doing",
        "sensor.index_bedtime_target",
        "input_text.index_bedtime_target",
    ]
    entities = _load_ha_entities(entity_ids)

    sleep_hours = _first_known_float(entities, ["sensor.aperture_sleep_hours"])
    if sleep_hours is None:
        sleep_minutes = _first_known_float(entities, ["sensor.aperture_sleep_duration"])
        sleep_hours = round(sleep_minutes / 60, 2) if sleep_minutes is not None else None

    intent_raw = _first_known_state(
        entities,
        ["sensor.index_top_tasks", "input_text.index_top_tasks", "sensor.undercurrent_daily_intent"],
    )
    stop_doing = _first_known_state(entities, ["sensor.index_stop_doing", "input_text.index_stop_doing"]) or ""
    bedtime_target = _first_known_state(entities, ["sensor.index_bedtime_target", "input_text.index_bedtime_target"]) or ""
    vector_raw = _first_known_state(entities, ["sensor.undercurrent_main_drag"]) or "other"
    note_raw = _first_known_state(entities, ["sensor.undercurrent_daily_intent"]) or ""
    ts_raw = _first_known_state(entities, ["sensor.undercurrent_date"])
    try:
        behavioral = _behavioral_signal_suite()
    except Exception:
        behavioral = {}
    sedentary_streak_min = _int_or_none(behavioral.get("sedentary_streak_min"))
    if sedentary_streak_min is None:
        sedentary_streak_min = _first_known_int(entities, ["sensor.index_sedentary_streak_min"])

    return TodayTelemetry(
        date=datetime.now(TZ).date().isoformat(),
        time_of_day=_time_of_day(),
        pneuma={
            "mood": _first_known_int(entities, ["sensor.undercurrent_morning_mood"]),
            "clarity": _first_known_int(entities, ["sensor.undercurrent_morning_clarity"]),
            "stress": _first_known_int(entities, ["sensor.undercurrent_morning_stress"]),
            "vector": vector_raw,
            "note": note_raw,
            "ts": ts_raw,
        },
        body={
            "sleep_hours": sleep_hours,
            "resting_hr": _first_known_float(entities, ["sensor.aperture_resting_heart_rate"]),
            "steps": _first_known_int(entities, ["sensor.aperture_daily_steps"]),
            "sedentary_streak_min": sedentary_streak_min,
        },
        attention={
            "screen_total_min": _first_known_int(entities, ["sensor.index_screen_total_min"]),
            "screen_work_min": _first_known_int(entities, ["sensor.index_screen_work_min"]),
            "screen_entertainment_min": _first_known_int(entities, ["sensor.index_screen_entertainment_min"]),
            "screen_social_min": _first_known_int(entities, ["sensor.index_screen_social_min"]),
            "unlocks_per_hour": _first_known_float(entities, ["sensor.index_unlocks_per_hour"]),
            "late_night_screen_min": _first_known_int(entities, ["sensor.index_late_night_screen_min"]),
            "active_notification_count": _first_known_int(entities, ["sensor.aperture_active_notification_count"]),
        },
        context={
            "meetings_count": _first_known_int(entities, ["sensor.index_calendar_meetings_count"]),
            "busy_minutes": _first_known_int(entities, ["sensor.index_calendar_busy_minutes"]),
            "home_media_min": _first_known_int(entities, ["sensor.index_home_media_minutes"]),
        },
        commitments={
            "top_tasks": _intent_list_from_state(intent_raw),
            "stop_doing": stop_doing,
            "bedtime_target": bedtime_target,
        },
        behavioral={
            "first_departure_time": behavioral.get("first_departure_time"),
            "away_place_changes_today": _int_or_none(behavioral.get("away_place_changes_today")),
            "evening_away_minutes": _float_or_none(behavioral.get("evening_away_minutes")),
            "evening_home_minutes": _float_or_none(behavioral.get("evening_home_minutes")),
            "evening_home_protection_minutes": _float_or_none(behavioral.get("evening_home_protection_minutes")),
            "out_of_house_fragmentation_load_score": _float_or_none(behavioral.get("out_of_house_fragmentation_load_score")),
            "evening_home_protection_score": _float_or_none(behavioral.get("evening_home_protection_score")),
            "app_switches_today": _int_or_none(behavioral.get("app_switches_today")),
            "unique_apps_today": _int_or_none(behavioral.get("unique_apps_today")),
            "longest_single_app_streak_minutes": _float_or_none(behavioral.get("longest_single_app_streak_minutes")),
            "app_switches_per_hour": _float_or_none(behavioral.get("app_switches_per_hour")),
            "app_context_switch_load_score": _float_or_none(behavioral.get("app_context_switch_load_score")),
            "wind_down_charge_consistency_score": _float_or_none(behavioral.get("wind_down_charge_consistency_score")),
            "longest_still_block_workday_minutes": _float_or_none(behavioral.get("longest_still_block_workday_minutes")),
            "post_midday_movement_minutes": _float_or_none(behavioral.get("post_midday_movement_minutes")),
            "driving_transit_minutes_today": _float_or_none(behavioral.get("driving_transit_minutes_today")),
            "activity_transitions_today": _int_or_none(behavioral.get("activity_transitions_today")),
            "activity_pattern_load_score": _float_or_none(behavioral.get("activity_pattern_load_score")),
            "music_supported_focus_minutes_today": _float_or_none(behavioral.get("music_supported_focus_minutes_today")),
            "longest_music_supported_focus_block_minutes": _float_or_none(behavioral.get("longest_music_supported_focus_block_minutes")),
            "music_supported_focus_score": _float_or_none(behavioral.get("music_supported_focus_score")),
            "morning_pickup_delay_minutes": _float_or_none(behavioral.get("morning_pickup_delay_minutes")),
            "morning_pickup_delay_score": _float_or_none(behavioral.get("morning_pickup_delay_score")),
            "night_disruption_events": _int_or_none(behavioral.get("night_disruption_events")),
            "night_disruption_load_score": _float_or_none(behavioral.get("night_disruption_load_score")),
            "notification_spike_count": _int_or_none(behavioral.get("notification_spike_count")),
            "longest_notification_recovery_lag_minutes": _float_or_none(behavioral.get("longest_notification_recovery_lag_minutes")),
            "notification_recovery_load_score": _float_or_none(behavioral.get("notification_recovery_load_score")),
            "restorative_place_minutes_today": _float_or_none(behavioral.get("restorative_place_minutes_today")),
            "restorative_place_labels_today": behavioral.get("restorative_place_labels_today") or "",
            "restorative_place_score": _float_or_none(behavioral.get("restorative_place_score")),
            "hrv_relative_score": _float_or_none(behavioral.get("hrv_relative_score")),
        },
    )


def get_index_runtime(pneuma_scores: dict[str, Any] | None = None) -> dict[str, Any]:
    telemetry = build_index_telemetry()
    snapshot = build_index_snapshot(telemetry, pneuma_scores or get_pneuma_scores())
    sprite_catalog = {
        1: {"label": "Smug", "filename": "index_sprite_01_smug.png"},
        2: {"label": "Deadpan", "filename": "index_sprite_02_deadpan.png"},
        3: {"label": "Aha", "filename": "index_sprite_03_aha.png"},
        4: {"label": "Wink", "filename": "index_sprite_04_wink.png"},
        5: {"label": "Content", "filename": "index_sprite_05_content.png"},
        6: {"label": "Confused", "filename": "index_sprite_06_confused.png"},
        7: {"label": "Facepalm", "filename": "index_sprite_07_facepalm.png"},
        8: {"label": "Approve", "filename": "index_sprite_08_approve.png"},
        9: {"label": "Annoyed", "filename": "index_sprite_09_annoyed.png"},
        10: {"label": "Fading", "filename": "index_sprite_10_fading.png"},
        11: {"label": "Skeptical", "filename": "index_sprite_11_skeptical.png"},
        12: {"label": "Delight", "filename": "index_sprite_12_delight.png"},
    }
    sprite_meta = sprite_catalog.get(snapshot["sprite_id"], sprite_catalog[2])
    return {
        **snapshot,
        "ui": {
            "available": snapshot["available"],
            "mode": snapshot["mode"].replace("_", " ").title(),
            "commentary": snapshot["commentary"],
            "next_step": snapshot["next_step"],
            "confidence_pct": round(snapshot["confidence"] * 100),
            "sprite_label": sprite_meta["label"],
            "sprite_path": f"/static/Index_sprites/{sprite_meta['filename']}",
        },
    }


@app.get("/api/index/runtime")
def api_index_runtime():
    return get_index_runtime()


@app.get("/api/index/pneuma-scores")
def api_index_pneuma_scores():
    return get_pneuma_scorecard()


@app.get("/api/index/alignment-support")
def api_index_alignment_support():
    return get_alignment_support_data()


@app.get("/api/index/regulation-support")
def api_index_regulation_support():
    return get_regulation_support_data()


@app.get("/api/index/pneuma-latest")
def api_index_pneuma_latest():
    telemetry = build_index_telemetry()
    return telemetry.pneuma.model_dump(mode="json")


@app.post("/api/index/evaluate")
def api_index_evaluate(body: TodayTelemetry):
    return build_index_snapshot(body)


def _datetime_marks(start: datetime, end: datetime, *, step_minutes: int) -> list[datetime]:
    if end <= start:
        return [start]
    marks: list[datetime] = []
    cursor = start
    step = timedelta(minutes=step_minutes)
    while cursor <= end:
        marks.append(cursor)
        cursor += step
    if marks[-1] != end:
        marks.append(end)
    return marks


def _sample_rows_at_marks(rows: list[tuple[float, str]], marks: list[datetime]) -> list[str | None]:
    if not marks:
        return []

    cursor = 0
    current_state: str | None = None
    if rows and rows[0][0] < marks[0].timestamp():
        current_state = str(rows[0][1])
        cursor = 1

    out: list[str | None] = []
    for mark in marks:
        mark_ts = mark.timestamp()
        while cursor < len(rows) and rows[cursor][0] <= mark_ts:
            current_state = str(rows[cursor][1])
            cursor += 1
        out.append(current_state)
    return out


def _entity_state_series(
    entity_id: str,
    start: datetime,
    end: datetime,
    *,
    step_minutes: int = 5,
) -> list[tuple[datetime, str | None]]:
    marks = _datetime_marks(start, end, step_minutes=step_minutes)
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=start.timestamp(), end_ts=end.timestamp())
    values = _sample_rows_at_marks(rows, marks)
    return list(zip(marks, values))


def _entity_state_segments(entity_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=start_ts, end_ts=end_ts)
    if not rows:
        return []

    current_state: str | None = None
    current_start = start_ts
    cursor = 0
    if rows[0][0] < start_ts:
        current_state = str(rows[0][1])
        cursor = 1

    segments: list[tuple[datetime, datetime, str]] = []
    for updated_ts, state in rows[cursor:]:
        if updated_ts < start_ts:
            continue
        if updated_ts > end_ts:
            break
        if current_state is not None and updated_ts > current_start:
            segments.append(
                (
                    datetime.fromtimestamp(current_start, tz=TZ),
                    datetime.fromtimestamp(updated_ts, tz=TZ),
                    current_state,
                )
            )
        current_state = str(state)
        current_start = max(updated_ts, start_ts)

    if current_state is not None and end_ts > current_start:
        segments.append(
            (
                datetime.fromtimestamp(current_start, tz=TZ),
                datetime.fromtimestamp(end_ts, tz=TZ),
                current_state,
            )
        )
    return segments


def _format_local_clock(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(TZ).strftime("%I:%M %p").lstrip("0")


def _duration_minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60)


def _location_signature(raw_value: str | None) -> str | None:
    if not _known_state(raw_value):
        return None
    parts = [part.strip() for part in str(raw_value).split(",") if part.strip()]
    if not parts:
        return None
    street = re.sub(r"^\d+\s+", "", parts[0]).strip().lower()
    city = parts[1].strip().lower() if len(parts) > 1 else ""
    region = parts[2].strip().lower() if len(parts) > 2 else ""
    if not street:
        return None
    return " | ".join(part for part in [street, city, region] if part)


def _friendly_place_label(raw_label: str | None) -> str | None:
    if not _known_state(raw_label):
        return None
    label = str(raw_label)
    if label.startswith("wifi:"):
        return label.split(":", 1)[1]
    if label.startswith("loc:"):
        return label.split(":", 1)[1].split("|", 1)[0].strip().title()
    return label


def _normalize_token(raw_value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (raw_value or "").strip().lower()).strip("_")


def _normalize_app_name(raw_value: str | None) -> str | None:
    if not _known_state(raw_value):
        return None
    package_name = str(raw_value).strip().lower()
    if not package_name or package_name in APP_SWITCH_IGNORE:
        return None
    if package_name.endswith(".launcher"):
        return None
    leaf = package_name.split(".")[-1].replace("_", " ").replace("-", " ").strip()
    if not leaf:
        leaf = package_name
    return leaf.title()


def _activity_bucket(raw_value: str | None) -> str:
    if not _known_state(raw_value):
        return "unknown"
    value = str(raw_value).strip().lower()
    if value in MOVING_ACTIVITY_STATES:
        return "moving"
    if value in TRANSIT_ACTIVITY_STATES:
        return "transit"
    if value in STILL_ACTIVITY_STATES:
        return "still"
    return "other"


def _overlap_minutes(
    start: datetime,
    end: datetime,
    window_start: datetime,
    window_end: datetime,
) -> float:
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0.0
    return _duration_minutes(overlap_start, overlap_end)


def _latest_numeric_rows_with_dt(entity_id: str, *, days: int = 7) -> list[tuple[datetime, float]]:
    end = datetime.now(TZ)
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=(end - timedelta(days=days)).timestamp(), end_ts=end.timestamp())
    out: list[tuple[datetime, float]] = []
    for updated_ts, state in rows:
        value = _state_float(state)
        if value is None:
            continue
        out.append((datetime.fromtimestamp(updated_ts, tz=TZ), value))
    return out


def _latest_known_state_change(entity_id: str, *, days: int = 3) -> datetime | None:
    end = datetime.now(TZ)
    rows = _ha_raw_state_rows_from_db(entity_id, start_ts=(end - timedelta(days=days)).timestamp(), end_ts=end.timestamp())
    for updated_ts, state in reversed(rows):
        if _known_state(state):
            return datetime.fromtimestamp(updated_ts, tz=TZ)
    return None


def _sedentary_streak_from_step_count(
    now: datetime | None = None,
    *,
    wake_time: datetime | None = None,
) -> float | None:
    local_now = now or datetime.now(TZ)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_start
    if wake_time is not None:
        start = min(local_now, max(day_start, wake_time))
    if local_now <= start:
        return 0.0

    rows = _ha_raw_state_rows_from_db(
        "sensor.aperture_daily_steps",
        start_ts=start.timestamp(),
        end_ts=local_now.timestamp(),
    )
    if not rows:
        return None

    highest_steps: float | None = None
    last_increase_at = start
    first_known = False
    for updated_ts, raw_state in rows:
        steps = _state_float(raw_state)
        if steps is None:
            continue

        observed_at = max(start, datetime.fromtimestamp(updated_ts, tz=TZ))
        if not first_known:
            first_known = True
            highest_steps = steps
            last_increase_at = observed_at
            continue

        if highest_steps is None:
            highest_steps = steps
            last_increase_at = observed_at
            continue

        # Reset the sedentary streak only when the step counter itself advances.
        if steps > highest_steps:
            if (steps - highest_steps) >= 1.0:
                last_increase_at = observed_at
            highest_steps = steps

    if not first_known:
        return None
    return round(_duration_minutes(last_increase_at, local_now), 1)


def _build_home_anchor_context(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    start = local_now - timedelta(days=21)
    marks = _datetime_marks(start, local_now, step_minutes=30)
    wifi_rows = _ha_raw_state_rows_from_db(APERTURE_WIFI_ENTITY, start_ts=start.timestamp(), end_ts=local_now.timestamp())
    location_rows = _ha_raw_state_rows_from_db(APERTURE_LOCATION_ENTITY, start_ts=start.timestamp(), end_ts=local_now.timestamp())
    wifi_series = _sample_rows_at_marks(wifi_rows, marks)
    location_series = _sample_rows_at_marks(location_rows, marks)

    wifi_counts: dict[str, int] = {}
    for mark, wifi in zip(marks, wifi_series):
        if 22 <= mark.hour or mark.hour < 6:
            if _known_state(wifi) and str(wifi) != "<not connected>":
                wifi_text = str(wifi)
                wifi_counts[wifi_text] = wifi_counts.get(wifi_text, 0) + 1

    home_wifi = None
    if wifi_counts:
        home_wifi = max(wifi_counts, key=wifi_counts.get)

    location_counts: dict[str, int] = {}
    for mark, wifi, location in zip(marks, wifi_series, location_series):
        if not (22 <= mark.hour or mark.hour < 6):
            continue
        signature = _location_signature(location)
        if not signature:
            continue
        weight = 2 if home_wifi and wifi == home_wifi else 1
        location_counts[signature] = location_counts.get(signature, 0) + weight

    home_location_signatures = [
        signature
        for signature, _ in sorted(location_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    ]

    return {
        "home_wifi_anchor": home_wifi,
        "home_location_signatures": set(home_location_signatures),
        "home_location_anchor": home_location_signatures[0] if home_location_signatures else None,
    }


def _classify_place(
    wifi_state: str | None,
    location_state: str | None,
    home_context: dict[str, Any],
) -> tuple[str, str]:
    home_wifi = home_context.get("home_wifi_anchor")
    home_location_signatures = home_context.get("home_location_signatures") or set()
    location_signature = _location_signature(location_state)

    if home_wifi and wifi_state == home_wifi:
        return "home", "home"
    if location_signature and location_signature in home_location_signatures:
        return "home", "home"
    if _known_state(wifi_state) and str(wifi_state) != "<not connected>":
        return "away", f"wifi:{wifi_state}"
    if location_signature:
        return "away", f"loc:{location_signature}"
    return "unknown", "unknown"


def _compress_sample_blocks(
    marks: list[datetime],
    values: list[Any],
    end: datetime,
) -> list[tuple[datetime, datetime, Any]]:
    if not marks or not values:
        return []

    blocks: list[tuple[datetime, datetime, Any]] = []
    block_start = marks[0]
    block_value = values[0]
    for index in range(1, len(values)):
        if values[index] != block_value:
            blocks.append((block_start, marks[index], block_value))
            block_start = marks[index]
            block_value = values[index]
    blocks.append((block_start, end, block_value))
    return blocks


def _non_shallow_app_segments(start: datetime, end: datetime) -> list[dict[str, Any]]:
    segments = _entity_state_segments(APERTURE_LAST_USED_APP_ENTITY, start, end)
    out: list[dict[str, Any]] = []
    for seg_start, seg_end, state in segments:
        name = _normalize_app_name(state)
        if not name:
            continue
        if out and out[-1]["app"] == name and (seg_start - out[-1]["end"]).total_seconds() <= 300:
            out[-1]["end"] = seg_end
            continue
        out.append({"app": name, "start": seg_start, "end": seg_end})
    return out


def _infer_latest_wake_time(now: datetime | None = None) -> datetime | None:
    local_now = now or datetime.now(TZ)
    rows = _latest_numeric_rows_with_dt(APERTURE_SLEEP_DURATION_ENTITY, days=3)
    morning_rows = [(dt, value) for dt, value in rows if 3 <= dt.hour < 14 and dt <= local_now]
    if not morning_rows:
        return None

    clusters: list[list[tuple[datetime, float]]] = []
    current_cluster: list[tuple[datetime, float]] = [morning_rows[0]]
    for dt, value in morning_rows[1:]:
        if dt.date() == current_cluster[-1][0].date() and (dt - current_cluster[-1][0]).total_seconds() <= 90 * 60:
            current_cluster.append((dt, value))
        else:
            clusters.append(current_cluster)
            current_cluster = [(dt, value)]
    clusters.append(current_cluster)

    latest_cluster = max(clusters, key=lambda cluster: cluster[-1][0])
    return latest_cluster[-1][0]


def _charging_sessions(start: datetime, end: datetime) -> list[dict[str, Any]]:
    marks = _datetime_marks(start, end, step_minutes=5)
    charging_rows = _ha_raw_state_rows_from_db(APERTURE_CHARGING_ENTITY, start_ts=start.timestamp(), end_ts=end.timestamp())
    charger_type_rows = _ha_raw_state_rows_from_db(APERTURE_CHARGER_TYPE_ENTITY, start_ts=start.timestamp(), end_ts=end.timestamp())
    charging_states = _sample_rows_at_marks(charging_rows, marks)
    charger_types = _sample_rows_at_marks(charger_type_rows, marks)

    active_flags = []
    for charging_state, charger_type in zip(charging_states, charger_types):
        is_active = charging_state == "on"
        if _known_state(charger_type) and str(charger_type).strip().lower() != "none":
            is_active = True
        active_flags.append(is_active)

    sessions: list[dict[str, Any]] = []
    for block_start, block_end, is_active in _compress_sample_blocks(marks, active_flags, end):
        if not is_active:
            continue
        duration_minutes = _duration_minutes(block_start, block_end)
        sessions.append(
            {
                "start": block_start,
                "end": block_end,
                "duration_minutes": duration_minutes,
            }
        )
    return sessions


def _wind_down_shifted_minutes(value: datetime) -> float:
    minute_of_day = value.hour * 60 + value.minute
    if minute_of_day < 720:
        minute_of_day += 1440
    return float(minute_of_day)


def _qualifying_wind_down_sessions(now: datetime | None = None, *, days: int = 35) -> list[dict[str, Any]]:
    local_now = now or datetime.now(TZ)
    start = local_now - timedelta(days=days)
    sessions = _charging_sessions(start, local_now)
    out: list[dict[str, Any]] = []
    for session in sessions:
        session_start = session["start"]
        duration_minutes = session["duration_minutes"]
        hour = session_start.hour
        if duration_minutes < 45:
            continue
        if hour < 19 and hour >= 2:
            continue
        out.append(
            {
                **session,
                "shifted_minutes": _wind_down_shifted_minutes(session_start),
            }
        )
    return out


def _recent_event_count(events: list[datetime], mark: datetime, *, window_minutes: int) -> int:
    window_start = mark - timedelta(minutes=window_minutes)
    return sum(1 for event in events if window_start < event <= mark)


def _merge_close_event_times(events: list[datetime], *, merge_gap_minutes: int = 10) -> list[datetime]:
    if not events:
        return []
    merged = [events[0]]
    gap = timedelta(minutes=merge_gap_minutes)
    for event in events[1:]:
        if event - merged[-1] <= gap:
            continue
        merged.append(event)
    return merged


def _restorative_labels_for_sample(wifi_state: str | None, location_state: str | None) -> set[str]:
    labels: set[str] = set()
    wifi_token = _normalize_token(wifi_state)
    location_text = (location_state or "").strip().lower()

    if wifi_token:
        for keyword in RESTORATIVE_WIFI_KEYWORDS:
            if keyword in wifi_token:
                if "church" in keyword or "god" in keyword or "worship" in keyword or "chapel" in keyword:
                    labels.add("church")
                elif "gym" in keyword or "fitness" in keyword or "ymca" in keyword:
                    labels.add("gym")

    for label, keywords in RESTORATIVE_LOCATION_KEYWORDS.items():
        if any(keyword in location_text for keyword in keywords):
            labels.add(label)
    return labels


def _behavioral_signal_suite(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    marks = _datetime_marks(day_start, local_now, step_minutes=5)

    home_context = _build_home_anchor_context(local_now)
    wifi_rows = _ha_raw_state_rows_from_db(APERTURE_WIFI_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())
    location_rows = _ha_raw_state_rows_from_db(APERTURE_LOCATION_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())
    activity_rows = _ha_raw_state_rows_from_db(APERTURE_ACTIVITY_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())
    notifications_rows = _ha_raw_state_rows_from_db(APERTURE_NOTIFICATIONS_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())
    interactive_rows = _ha_raw_state_rows_from_db(APERTURE_INTERACTIVE_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())
    music_rows = _ha_raw_state_rows_from_db(APERTURE_MUSIC_ENTITY, start_ts=day_start.timestamp(), end_ts=local_now.timestamp())

    wifi_series = _sample_rows_at_marks(wifi_rows, marks)
    location_series = _sample_rows_at_marks(location_rows, marks)
    activity_series = _sample_rows_at_marks(activity_rows, marks)
    notification_series = _sample_rows_at_marks(notifications_rows, marks)
    interactive_series = _sample_rows_at_marks(interactive_rows, marks)
    music_series = _sample_rows_at_marks(music_rows, marks)

    place_series = [_classify_place(wifi, location, home_context) for wifi, location in zip(wifi_series, location_series)]
    place_blocks = _compress_sample_blocks(marks, place_series, local_now)

    away_blocks: list[dict[str, Any]] = []
    home_evening_minutes = 0.0
    home_evening_longest_block = 0.0
    evening_window_start = day_start.replace(hour=18)
    first_departure_time = None
    for block_start, block_end, value in place_blocks:
        place_kind, place_label = value
        block_minutes = _duration_minutes(block_start, block_end)
        if place_kind == "away" and block_minutes >= 15:
            away_blocks.append(
                {
                    "start": block_start,
                    "end": block_end,
                    "minutes": block_minutes,
                    "label": place_label,
                }
            )
            if first_departure_time is None and block_start.hour >= 5:
                first_departure_time = block_start
        if place_kind == "home":
            evening_overlap = _overlap_minutes(block_start, block_end, evening_window_start, local_now)
            if evening_overlap > 0:
                home_evening_minutes += evening_overlap
                home_evening_longest_block = max(home_evening_longest_block, evening_overlap)

    stable_away_labels: list[str] = []
    for block in away_blocks:
        if not stable_away_labels or stable_away_labels[-1] != block["label"]:
            stable_away_labels.append(block["label"])
    away_place_changes_today = max(0, len(stable_away_labels) - 1)
    evening_away_minutes = sum(
        _overlap_minutes(block["start"], block["end"], evening_window_start, local_now)
        for block in away_blocks
    )

    if away_place_changes_today == 0:
        location_change_penalty = 10.0
    elif away_place_changes_today == 1:
        location_change_penalty = 20.0
    elif away_place_changes_today == 2:
        location_change_penalty = 35.0
    elif away_place_changes_today == 3:
        location_change_penalty = 55.0
    elif away_place_changes_today == 4:
        location_change_penalty = 75.0
    else:
        location_change_penalty = 90.0

    if evening_away_minutes <= 30:
        evening_away_penalty = 10.0
    elif evening_away_minutes <= 90:
        evening_away_penalty = 30.0
    elif evening_away_minutes <= 180:
        evening_away_penalty = 55.0
    else:
        evening_away_penalty = 80.0

    if home_evening_longest_block >= 180:
        home_protection_penalty = 10.0
    elif home_evening_longest_block >= 120:
        home_protection_penalty = 30.0
    elif home_evening_longest_block >= 60:
        home_protection_penalty = 60.0
    else:
        home_protection_penalty = 85.0

    out_of_house_fragmentation_load_score = round(
        (location_change_penalty * 0.45) + (evening_away_penalty * 0.25) + (home_protection_penalty * 0.30),
        1,
    )

    if home_evening_minutes >= 180:
        evening_home_minutes_score = 90.0
    elif home_evening_minutes >= 120:
        evening_home_minutes_score = 70.0
    elif home_evening_minutes >= 60:
        evening_home_minutes_score = 45.0
    else:
        evening_home_minutes_score = 20.0

    if home_evening_longest_block >= 180:
        evening_home_block_score = 95.0
    elif home_evening_longest_block >= 120:
        evening_home_block_score = 75.0
    elif home_evening_longest_block >= 60:
        evening_home_block_score = 50.0
    else:
        evening_home_block_score = 20.0

    evening_home_protection_score = round(
        (evening_home_minutes_score * 0.4) + (evening_home_block_score * 0.6),
        1,
    )

    wake_time = _infer_latest_wake_time(local_now)
    sedentary_streak_min = _sedentary_streak_from_step_count(local_now, wake_time=wake_time)
    app_window_start = wake_time or day_start
    app_segments = _non_shallow_app_segments(app_window_start, local_now)
    app_switches_today = max(0, len(app_segments) - 1)
    unique_apps_today = len({segment["app"] for segment in app_segments})
    longest_single_app_streak_minutes = round(
        max((_duration_minutes(segment["start"], segment["end"]) for segment in app_segments), default=0.0),
        1,
    )
    app_window_hours = max(_duration_minutes(app_window_start, local_now) / 60, 1.0)
    app_switches_per_hour = app_switches_today / app_window_hours

    if app_switches_per_hour <= 4:
        switch_rate_penalty = 15.0
    elif app_switches_per_hour <= 6:
        switch_rate_penalty = 35.0
    elif app_switches_per_hour <= 8:
        switch_rate_penalty = 55.0
    elif app_switches_per_hour <= 10:
        switch_rate_penalty = 75.0
    else:
        switch_rate_penalty = 90.0

    if unique_apps_today <= 3:
        unique_apps_penalty = 15.0
    elif unique_apps_today <= 5:
        unique_apps_penalty = 35.0
    elif unique_apps_today <= 7:
        unique_apps_penalty = 55.0
    elif unique_apps_today <= 10:
        unique_apps_penalty = 75.0
    else:
        unique_apps_penalty = 90.0

    if longest_single_app_streak_minutes >= 90:
        streak_penalty = 15.0
    elif longest_single_app_streak_minutes >= 60:
        streak_penalty = 30.0
    elif longest_single_app_streak_minutes >= 30:
        streak_penalty = 55.0
    elif longest_single_app_streak_minutes >= 15:
        streak_penalty = 75.0
    else:
        streak_penalty = 90.0

    app_context_switch_load_score = round(
        (switch_rate_penalty * 0.45) + (unique_apps_penalty * 0.25) + (streak_penalty * 0.30),
        1,
    )

    wind_down_sessions = _qualifying_wind_down_sessions(local_now)
    latest_wind_down = wind_down_sessions[-1] if wind_down_sessions else None
    wind_down_charge_start = latest_wind_down["start"] if latest_wind_down else None
    wind_down_charge_duration_minutes = round(latest_wind_down["duration_minutes"], 1) if latest_wind_down else None
    wind_down_profile = _profile_from_values([session["shifted_minutes"] for session in wind_down_sessions[-30:]]) if wind_down_sessions else None
    wind_down_shifted = latest_wind_down["shifted_minutes"] if latest_wind_down else None
    wind_down_charge_drift_minutes = None
    wind_down_charge_consistency_score = None
    if wind_down_profile and wind_down_shifted is not None:
        wind_down_charge_drift_minutes = round(wind_down_shifted - wind_down_profile["mean"], 1)
        drift_abs = abs(wind_down_charge_drift_minutes)
        if drift_abs <= 15:
            wind_down_charge_consistency_score = 95.0
        elif drift_abs <= 30:
            wind_down_charge_consistency_score = 80.0
        elif drift_abs <= 60:
            wind_down_charge_consistency_score = 60.0
        elif drift_abs <= 90:
            wind_down_charge_consistency_score = 40.0
        else:
            wind_down_charge_consistency_score = 20.0

    workday_start = day_start.replace(hour=9)
    workday_end = min(local_now, day_start.replace(hour=18))
    activity_values = [_activity_bucket(value) for value in activity_series]
    activity_blocks = _compress_sample_blocks(marks, activity_values, local_now)

    longest_still_block_workday_minutes = 0.0
    driving_transit_minutes_today = 0.0
    activity_transitions_today = 0
    previous_activity = None
    for block_start, block_end, bucket in activity_blocks:
        if bucket != previous_activity and previous_activity is not None and bucket != "unknown":
            activity_transitions_today += 1
        if bucket != "unknown":
            previous_activity = bucket
        if bucket == "still":
            longest_still_block_workday_minutes = max(
                longest_still_block_workday_minutes,
                _overlap_minutes(block_start, block_end, workday_start, workday_end),
            )
        if bucket == "transit":
            driving_transit_minutes_today += _duration_minutes(block_start, block_end)

    midday_anchor = _latest_known_state_change("sensor.undercurrent_midday_drift") or day_start.replace(hour=12)
    post_midday_movement_minutes = 0.0
    for block_start, block_end, bucket in activity_blocks:
        if bucket == "moving":
            post_midday_movement_minutes += _overlap_minutes(block_start, block_end, midday_anchor, local_now)

    if longest_still_block_workday_minutes <= 45:
        still_penalty = 18.0
    elif longest_still_block_workday_minutes <= 90:
        still_penalty = 40.0
    elif longest_still_block_workday_minutes <= 150:
        still_penalty = 68.0
    else:
        still_penalty = 86.0

    if post_midday_movement_minutes >= 45:
        movement_penalty = 15.0
    elif post_midday_movement_minutes >= 25:
        movement_penalty = 35.0
    elif post_midday_movement_minutes >= 10:
        movement_penalty = 60.0
    else:
        movement_penalty = 85.0

    if activity_transitions_today <= 3:
        transition_penalty = 20.0
    elif activity_transitions_today <= 6:
        transition_penalty = 45.0
    elif activity_transitions_today <= 10:
        transition_penalty = 65.0
    else:
        transition_penalty = 85.0

    activity_pattern_load_score = round(
        (still_penalty * 0.5) + (movement_penalty * 0.3) + (transition_penalty * 0.2),
        1,
    )

    non_shallow_app_change_times = [segment["start"] for segment in app_segments[1:]]
    focus_flags: list[bool] = []
    for mark, music_state, interactive_state, notification_state in zip(
        marks,
        music_series,
        interactive_series,
        notification_series,
    ):
        notification_count = _state_float(notification_state)
        recent_switches = _recent_event_count(non_shallow_app_change_times, mark, window_minutes=30)
        focus_flags.append(
            music_state == "on"
            and interactive_state == "off"
            and notification_count is not None
            and notification_count <= 3
            and recent_switches <= 2
        )
    focus_blocks = [
        {
            "start": block_start,
            "end": block_end,
            "minutes": _duration_minutes(block_start, block_end),
        }
        for block_start, block_end, is_focus in _compress_sample_blocks(marks, focus_flags, local_now)
        if is_focus and _duration_minutes(block_start, block_end) >= 20
    ]
    music_supported_focus_minutes_today = round(sum(block["minutes"] for block in focus_blocks), 1)
    music_supported_focus_blocks_today = len(focus_blocks)
    longest_music_supported_focus_block_minutes = round(
        max((block["minutes"] for block in focus_blocks), default=0.0),
        1,
    )

    if music_supported_focus_minutes_today >= 120:
        focus_minutes_score = 100.0
    elif music_supported_focus_minutes_today >= 60:
        focus_minutes_score = 80.0
    elif music_supported_focus_minutes_today >= 30:
        focus_minutes_score = 60.0
    elif music_supported_focus_minutes_today > 0:
        focus_minutes_score = 40.0
    else:
        focus_minutes_score = 20.0

    if longest_music_supported_focus_block_minutes >= 60:
        focus_block_score = 95.0
    elif longest_music_supported_focus_block_minutes >= 40:
        focus_block_score = 75.0
    elif longest_music_supported_focus_block_minutes >= 20:
        focus_block_score = 55.0
    else:
        focus_block_score = 20.0

    music_supported_focus_score = round((focus_minutes_score * 0.6) + (focus_block_score * 0.4), 1)

    morning_pickup_time = None
    morning_pickup_delay_minutes = None
    morning_pickup_delay_score = None
    if wake_time is not None:
        pickup_candidates: list[datetime] = []
        interactive_segments = _entity_state_segments(APERTURE_INTERACTIVE_ENTITY, wake_time, min(local_now, wake_time + timedelta(hours=2)))
        for seg_start, _seg_end, state in interactive_segments:
            if state == "on":
                pickup_candidates.append(seg_start)
        if app_segments:
            for segment in app_segments:
                if wake_time <= segment["start"] <= wake_time + timedelta(hours=2):
                    pickup_candidates.append(segment["start"])
        if pickup_candidates:
            morning_pickup_time = min(pickup_candidates)
            morning_pickup_delay_minutes = round(_duration_minutes(wake_time, morning_pickup_time), 1)
            if morning_pickup_delay_minutes >= 60:
                morning_pickup_delay_score = 100.0
            elif morning_pickup_delay_minutes >= 30:
                morning_pickup_delay_score = 80.0
            elif morning_pickup_delay_minutes >= 15:
                morning_pickup_delay_score = 60.0
            elif morning_pickup_delay_minutes >= 5:
                morning_pickup_delay_score = 35.0
            else:
                morning_pickup_delay_score = 15.0

    overnight_window_start = None
    night_disruption_events = 0
    night_disruption_load_score = None
    if wake_time is not None:
        overnight_window_start = wind_down_charge_start
        if overnight_window_start is None or overnight_window_start >= wake_time:
            overnight_window_start = (wake_time - timedelta(days=1)).replace(hour=21, minute=30, second=0, microsecond=0)

        disturbance_times: list[datetime] = []
        interactive_segments = _entity_state_segments(APERTURE_INTERACTIVE_ENTITY, overnight_window_start, wake_time)
        for seg_start, _seg_end, state in interactive_segments:
            if state == "on" and seg_start >= overnight_window_start + timedelta(minutes=15):
                disturbance_times.append(seg_start)
        for segment in _non_shallow_app_segments(overnight_window_start, wake_time):
            if segment["start"] >= overnight_window_start + timedelta(minutes=15):
                disturbance_times.append(segment["start"])
        disturbance_times.sort()
        merged_disturbances = _merge_close_event_times(disturbance_times, merge_gap_minutes=10)
        night_disruption_events = len(merged_disturbances)
        if night_disruption_events == 0:
            night_disruption_load_score = 10.0
        elif night_disruption_events == 1:
            night_disruption_load_score = 30.0
        elif night_disruption_events == 2:
            night_disruption_load_score = 55.0
        elif night_disruption_events == 3:
            night_disruption_load_score = 75.0
        else:
            night_disruption_load_score = 90.0

    longest_notification_recovery_lag_minutes = 0.0
    notification_spike_durations: list[float] = []
    spike_start = None
    for mark, raw_value in zip(marks, notification_series):
        value = _state_float(raw_value)
        if value is None:
            continue
        if spike_start is None and value > 5:
            spike_start = mark
        elif spike_start is not None and value <= 2:
            lag_minutes = _duration_minutes(spike_start, mark)
            if lag_minutes >= 10:
                notification_spike_durations.append(lag_minutes)
                longest_notification_recovery_lag_minutes = max(longest_notification_recovery_lag_minutes, lag_minutes)
            spike_start = None
    if spike_start is not None:
        lag_minutes = _duration_minutes(spike_start, local_now)
        if lag_minutes >= 10:
            notification_spike_durations.append(lag_minutes)
            longest_notification_recovery_lag_minutes = max(longest_notification_recovery_lag_minutes, lag_minutes)

    notification_spike_count = len(notification_spike_durations)
    average_notification_recovery_lag_minutes = (
        round(sum(notification_spike_durations) / notification_spike_count, 1)
        if notification_spike_count
        else 0.0
    )

    if longest_notification_recovery_lag_minutes <= 10:
        lag_penalty = 15.0
    elif longest_notification_recovery_lag_minutes <= 25:
        lag_penalty = 35.0
    elif longest_notification_recovery_lag_minutes <= 45:
        lag_penalty = 60.0
    else:
        lag_penalty = 85.0

    if notification_spike_count == 0:
        spike_penalty = 10.0
    elif notification_spike_count == 1:
        spike_penalty = 30.0
    elif notification_spike_count == 2:
        spike_penalty = 55.0
    else:
        spike_penalty = 80.0

    notification_recovery_load_score = round((lag_penalty * 0.7) + (spike_penalty * 0.3), 1)

    restorative_minutes = 0.0
    restorative_labels: set[str] = set()
    for block_start, block_end, (place_kind, _place_label) in place_blocks:
        if place_kind != "away":
            continue
        sample_minutes = _duration_minutes(block_start, block_end)
        if sample_minutes < 20:
            continue
        block_labels: set[str] = set()
        for mark, wifi, location in zip(marks, wifi_series, location_series):
            if block_start <= mark < block_end:
                block_labels |= _restorative_labels_for_sample(wifi, location)
        if block_labels:
            restorative_minutes += sample_minutes
            restorative_labels |= block_labels
    restorative_place_minutes_today = round(restorative_minutes, 1)
    restorative_place_labels_today = ", ".join(sorted(restorative_labels)) if restorative_labels else ""

    if restorative_place_minutes_today >= 90:
        restorative_place_score = 100.0
    elif restorative_place_minutes_today >= 45:
        restorative_place_score = 80.0
    elif restorative_place_minutes_today >= 20:
        restorative_place_score = 60.0
    else:
        restorative_place_score = 20.0

    latest_hrv_rows = _latest_numeric_rows_with_dt(APERTURE_HRV_ENTITY, days=7)
    latest_hrv = latest_hrv_rows[-1][1] if latest_hrv_rows else None
    hrv_profile = _monthly_numeric_profile(APERTURE_HRV_ENTITY, trim_extremes_for_mean=True)
    hrv_relative_score = _profile_relative_score(latest_hrv, hrv_profile, min_span=8, fallback=None)

    return {
        "date": local_now.date().isoformat(),
        "generated_at": local_now.isoformat(),
        "home_wifi_anchor": home_context.get("home_wifi_anchor"),
        "home_location_anchor": home_context.get("home_location_anchor"),
        "first_departure_time": _format_local_clock(first_departure_time),
        "away_place_changes_today": away_place_changes_today,
        "evening_away_minutes": round(evening_away_minutes, 1),
        "evening_home_minutes": round(home_evening_minutes, 1),
        "evening_home_protection_minutes": round(home_evening_longest_block, 1),
        "out_of_house_fragmentation_load_score": out_of_house_fragmentation_load_score,
        "evening_home_protection_score": evening_home_protection_score,
        "app_switches_today": app_switches_today,
        "unique_apps_today": unique_apps_today,
        "longest_single_app_streak_minutes": longest_single_app_streak_minutes,
        "app_switches_per_hour": round(app_switches_per_hour, 2),
        "app_context_switch_load_score": app_context_switch_load_score,
        "wind_down_charge_start": _format_local_clock(wind_down_charge_start),
        "wind_down_charge_duration_minutes": wind_down_charge_duration_minutes,
        "wind_down_charge_drift_minutes": wind_down_charge_drift_minutes,
        "wind_down_charge_consistency_score": wind_down_charge_consistency_score,
        "longest_still_block_workday_minutes": round(longest_still_block_workday_minutes, 1),
        "sedentary_streak_min": sedentary_streak_min,
        "post_midday_movement_minutes": round(post_midday_movement_minutes, 1),
        "driving_transit_minutes_today": round(driving_transit_minutes_today, 1),
        "activity_transitions_today": activity_transitions_today,
        "activity_pattern_load_score": activity_pattern_load_score,
        "music_supported_focus_minutes_today": music_supported_focus_minutes_today,
        "music_supported_focus_blocks_today": music_supported_focus_blocks_today,
        "longest_music_supported_focus_block_minutes": longest_music_supported_focus_block_minutes,
        "music_supported_focus_score": music_supported_focus_score,
        "wake_time": _format_local_clock(wake_time),
        "morning_pickup_time": _format_local_clock(morning_pickup_time),
        "morning_pickup_delay_minutes": morning_pickup_delay_minutes,
        "morning_pickup_delay_score": morning_pickup_delay_score,
        "overnight_window_start": _format_local_clock(overnight_window_start),
        "night_disruption_events": night_disruption_events,
        "night_disruption_load_score": night_disruption_load_score,
        "notification_spike_count": notification_spike_count,
        "longest_notification_recovery_lag_minutes": round(longest_notification_recovery_lag_minutes, 1),
        "average_notification_recovery_lag_minutes": average_notification_recovery_lag_minutes,
        "notification_recovery_load_score": notification_recovery_load_score,
        "restorative_place_minutes_today": restorative_place_minutes_today,
        "restorative_place_labels_today": restorative_place_labels_today or None,
        "restorative_place_score": restorative_place_score,
        "latest_hrv": latest_hrv,
        "hrv_30d_average": (round(hrv_profile["mean"], 1) if hrv_profile else None),
        "hrv_30d_min": (round(hrv_profile["min"], 1) if hrv_profile else None),
        "hrv_30d_max": (round(hrv_profile["max"], 1) if hrv_profile else None),
        "hrv_relative_score": (round(hrv_relative_score, 1) if hrv_relative_score is not None else None),
    }


@app.get("/api/aperture/behavioral-signals")
def api_aperture_behavioral_signals():
    return JSONResponse(_behavioral_signal_suite())


@app.post("/wake", response_class=HTMLResponse)
def wake():
    rc, log_file = run_and_log(
        ["wakeonlan", "-i", "DEMO_BROADCAST_IP", ATELIER_MAC],
        "wake_atelier"
    )
    msg = f"Wake sent (exit code {rc}). Log: {log_file}"
    return RedirectResponse(url=f"/?msg={msg}&last_log={log_file}", status_code=303)


@app.post("/download/videos", response_class=HTMLResponse)
def download_videos(url: str = Form(default=VIDEO_PLAYLIST)):
    cmd = build_ytdlp_shell_cmd(url, VIDEO_OUT)
    rc, log_file = run_and_log(cmd, "dl_videos")
    msg = f"Video download started (exit code {rc}). Log: {log_file}"
    return RedirectResponse(url=f"/?msg={msg}&last_log={log_file}", status_code=303)


@app.post("/download/music", response_class=HTMLResponse)
def download_music(url: str = Form(default=MUSIC_PLAYLIST)):
    cmd = build_ytdlp_shell_cmd(url, MUSIC_OUT)
    rc, log_file = run_and_log(cmd, "dl_music")
    msg = f"Music download started (exit code {rc}). Log: {log_file}"
    return RedirectResponse(url=f"/?msg={msg}&last_log={log_file}", status_code=303)


@app.post("/download/abiding-moments/latest-hymn", response_class=HTMLResponse)
def download_latest_abiding_moments_hymn():
    try:
        ABIDING_MOMENTS_TARGET_DIR.mkdir(parents=True, exist_ok=True)
        latest_entry = get_latest_abiding_moments_message()
        if latest_entry is None:
            return _redirect_home("No Abiding Moments entries with a Hymn were found.")

        properties = latest_entry.get("properties") or {}
        hymn = _prop_plain_text(properties, ABIDING_MOMENTS_HYMN_PROP)
        if not hymn:
            return _redirect_home("The latest Abiding Moments entry does not include a Hymn.")

        entry_name = _prop_title_text(properties, ABIDING_MOMENTS_TITLE_PROP)
        entry_date = _prop_date_start(properties, ABIDING_MOMENTS_DATE_PROP)
        search_query = f"{hymn} {ABIDING_MOMENTS_SEARCH_SUFFIX}".strip()
        cmd = build_ytdlp_search_shell_cmd(
            search_query,
            ABIDING_MOMENTS_VIDEO_OUT,
            count=ABIDING_MOMENTS_SEARCH_COUNT,
        )
        rc, log_file = run_and_log(cmd, "dl_abiding_moments_hymn")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Abiding Moments download failed."
        return _redirect_home(detail)
    except Exception:
        return _redirect_home("Abiding Moments download failed.")

    source_bits = [bit for bit in [entry_name, entry_date] if bit]
    source_label = " / ".join(source_bits) if source_bits else "latest entry"
    msg = (
        f"Abiding Moments download started for '{hymn}' "
        f"(top YouTube hit from {source_label}; exit code {rc}). "
        f"Log: {log_file}"
    )
    return _redirect_home_with_log(msg, log_file)


@app.post("/ops/rebuild/aurora")
def rebuild_aurora(x_token: str = Header(default="")):
    if not REBUILD_TOKEN or x_token != REBUILD_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    rebuild_script = _configured_rebuild_script()
    p = subprocess.run(
        [rebuild_script, "rebuild"],
        capture_output=True,
        text=True,
        timeout=300,
    )

    return {
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "stdout": p.stdout[-8000:],  # keep response bounded
        "stderr": p.stderr[-8000:],
    }

@app.post("/ops/rebuild/aurora/ui", response_class=HTMLResponse)
def rebuild_aurora_ui(mode: str = Form(default="rebuild")):
    selected_mode = (mode or "rebuild").strip().lower()
    if selected_mode not in {"reload", "rebuild"}:
        raise HTTPException(status_code=400, detail="Invalid rebuild mode")

    rebuild_script = _configured_rebuild_script()
    rc, log_file = run_and_log(
        [rebuild_script, selected_mode],
        f"{selected_mode}_aurora",
    )
    msg = f"{selected_mode.title()} triggered (exit code {rc}). Log: {log_file}"
    return RedirectResponse(url=f"/?msg={msg}&last_log={log_file}", status_code=303)

# --- Notion config ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

UNDERCURRENT_DB_ID = "DEMO_DB_UNDERCURRENT"  # The Undercurrent
DAILY_DB_ID        = "DEMO_DB_DAILY_SUMMARY"  # Resonance Index
RHYTHMIC_RITES_DB_ID = "DEMO_DB_RHYTHMIC_RITES"  # Rhythmic Rites
QUEST_LIBRARY_DB_ID = "DEMO_DB_QUEST_LIBRARY"  # Quest Library
QUEST_RUNS_DB_ID = "DEMO_DB_QUEST_RUNS"  # Quest Runs
ECHOFORM_CODEX_DB_ID = "DEMO_DB_ECHOFORM_CODEX"  # The Echoform Codex
LIBRARY_DB_ID = "DEMO_DB_LIBRARY"  # Library
ARC_NODES_DB_ID = "DEMO_DB_ARC_NODES"  # Arc Nodes
ARC_ENGINES_DB_ID = "DEMO_DB_ARC_ENGINES"  # Arc Engines
ABIDING_MOMENTS_MESSAGES_DS_ID = "DEMO_DS_ABIDING_MESSAGES"  # Messages
QUEST_SELECTOR_VERSION = "quest_selector_v1"
ECHOFORM_IMAGE_DIR = BASE_DIR / "static" / "Echoforms"
ECHOFORM_IMAGE_NAME_ALIASES = {
    "cloakofbecoming": "Cloack of Becoming.png",
    "thequietledger": "Quiet Ledger.png",
    "quietledger": "Quiet Ledger.png",
}

# --- Undercurrent property names ---
UNDER_DATE_PROP = "Date"          # date property in undercurrent DB
UNDER_REL_PROP = "Resonance"      # relation property to daily page
UNDER_LESSON_PROP = os.getenv("UNDERCURRENT_LESSON_PROP", "Lesson")
UNDER_VERSION_PROP = os.getenv("UNDERCURRENT_VERSION_PROP", "Version")
ABIDING_MOMENTS_DATE_PROP = "Date"
ABIDING_MOMENTS_HYMN_PROP = "Hymn"
ABIDING_MOMENTS_TITLE_PROP = "Name"

TZ = ZoneInfo(os.getenv("TZ", "America/Chicago"))
UNDERCURRENT_TZ = ZoneInfo(os.getenv("UNDERCURRENT_TZ", "America/Chicago"))

MORNING_STATE_TAG_OPTIONS = [
    "steady",
    "foggy",
    "tense",
    "discouraged",
    "motivated",
    "avoidant",
    "restless",
    "grounded",
    "hopeful",
    "irritable",
    "burdened",
    "calm",
    "tired",
    "grateful",
]

MAIN_DRAG_OPTIONS = [
    "poor sleep",
    "work overload",
    "uncertainty",
    "conflict",
    "distraction",
    "temptation",
    "physical discomfort",
    "discouragement",
    "overstimulation",
    "no clear drag",
]

MIDDAY_DRIFT_OPTIONS = ["better", "same", "worse"]

MIDDAY_NEED_OPTIONS = [
    "food",
    "water",
    "movement",
    "prayer",
    "quiet",
    "sunlight",
    "break",
    "conversation",
    "recommitment",
    "deep work block",
    "cleanup/reset",
]

ALIGNMENT_OPTIONS = ["yes", "no", "partly"]

UNDERCURRENT_STATE_SHIFT_OPTIONS = ["more open", "same", "more closed"]

STATE_SHIFT_INTENSITY_OPTIONS = ["None", "Mild", "Strong"]

REGULATION_RESPONSE_OPTIONS = ["None", "Avoided", "Paused", "Repaired", "Recentered"]

PRIMARY_DISRUPTOR_OPTIONS = [
    "Noise",
    "Conflict",
    "Fatigue",
    "Hurry",
    "Uncertainty",
    "Appetite",
    "Screen",
    "Task Load",
    "Spiritual Drift",
]

CARRYOVER_OPTIONS = [
    "fatigue",
    "avoidance",
    "unresolved conflict",
    "spiritual drift",
    "fragmented attention",
    "emotional residue",
    "unfinished loop",
    "household disorder",
    "relational neglect",
    "overstimulation",
    "discouragement",
    "temptation pressure",
    "none",
]

NEGLECTED_DOMAIN_OPTIONS = [
    "Anchor",
    "Build",
    "Bond",
    "Body",
    "Stewardship",
    "Recovery",
]

MOST_DRAINING_OPTIONS = [
    "work pressure",
    "fragmented attention",
    "conflict",
    "fatigue",
    "uncertainty",
    "lack of progress",
    "physical discomfort",
    "temptation",
    "overstimulation",
    "social depletion",
]

MOST_RESTORATIVE_OPTIONS = [
    "prayer",
    "scripture",
    "walking",
    "sunlight",
    "music",
    "quiet",
    "family time",
    "task completion",
    "clean space",
    "meal",
    "rest",
    "worship",
    "journaling",
    "wife/family time",
]

TOMORROW_NEED_OPTIONS = [
    "prayer",
    "scripture",
    "movement",
    "water",
    "food",
    "quiet",
    "sunlight",
    "break",
    "conversation",
    "recommitment",
    "deep work block",
    "cleanup/reset",
    "cleanup/rest",
]

FOCUS_BLOCK_DOMAIN_LABELS = {
    "work": "Work",
    "personal": "Personal",
}
FOCUS_BLOCK_MODE_OPTIONS = [
    "Service",
    "Embodiment",
    "Learning",
    "Relationship",
    "Problem Solving",
    "Creation",
    "Review",
]
FOCUS_BLOCK_DEFAULT_DURATION_MINUTES = 90
FOCUS_BLOCK_FALLBACK_DURATION_MINUTES = 10
FOCUS_BLOCK_DEFAULT_PRESENCE = 4.0
FOCUS_BLOCK_DAY_START_HOUR = 6
FOCUS_BLOCK_DAY_END_HOUR = 22
FOCUS_BLOCK_SLOT_MINUTES = 30
FOCUS_BLOCK_FALLBACK_TILE = {
    "background": "#475569",
    "background_alt": "#334155",
    "border": "#1e293b",
    "text": "#f8fafc",
}
FOCUS_BLOCK_TILE_COLOR_MAP = {
    "blue": {
        "background": "#2563eb",
        "background_alt": "#1d4ed8",
        "border": "#1e40af",
        "text": "#eff6ff",
    },
    "brown": {
        "background": "#8b5e3c",
        "background_alt": "#6f472c",
        "border": "#4a2c1d",
        "text": "#fef7ed",
    },
    "dark blue": {
        "background": "#1d4ed8",
        "background_alt": "#1e3a8a",
        "border": "#172554",
        "text": "#eff6ff",
    },
    "gold": {
        "background": "#d4a017",
        "background_alt": "#b7791f",
        "border": "#92400e",
        "text": "#1f2937",
    },
    "green": {
        "background": "#16a34a",
        "background_alt": "#15803d",
        "border": "#166534",
        "text": "#f0fdf4",
    },
    "grey": {
        "background": "#64748b",
        "background_alt": "#475569",
        "border": "#334155",
        "text": "#f8fafc",
    },
    "light blue": {
        "background": "#38bdf8",
        "background_alt": "#0ea5e9",
        "border": "#0284c7",
        "text": "#082f49",
    },
    "orange": {
        "background": "#f97316",
        "background_alt": "#ea580c",
        "border": "#c2410c",
        "text": "#fff7ed",
    },
    "pink": {
        "background": "#ec4899",
        "background_alt": "#db2777",
        "border": "#9d174d",
        "text": "#fff1f2",
    },
    "purple": {
        "background": "#8b5cf6",
        "background_alt": "#7c3aed",
        "border": "#5b21b6",
        "text": "#f5f3ff",
    },
    "white": {
        "background": "#f8fafc",
        "background_alt": "#e2e8f0",
        "border": "#cbd5e1",
        "text": "#0f172a",
    },
    "yellow": {
        "background": "#facc15",
        "background_alt": "#eab308",
        "border": "#ca8a04",
        "text": "#1f2937",
    },
}
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DAILY_LOAD_FIELD_DEFS = [
    {
        "field": "work_meetings_count",
        "property": "Work Meetings Count",
        "label": "Work Meetings",
    },
    # Keep the legacy field/property name so existing Notion + Home Assistant wiring stays intact.
    {
        "field": "after_work_activity_count",
        "property": "After Work Activity Count",
        "label": "After-Work Hours",
        "step": "0.25",
    },
    {
        "field": "errands_appointments_count",
        "property": "Errands / Appointments Count",
        "label": "Errands / Appointments",
    },
    {
        "field": "social_commitments_count",
        "property": "Social Commitments Count",
        "label": "Social Commitments",
    },
]
AFTER_WORK_ACTIVITY_BRIEF_THRESHOLD_HOURS = 1.0
AFTER_WORK_BUSY_THRESHOLD_HOURS = 2.5
AFTER_WORK_SIGNAL_START_HOUR = 17
AFTER_WORK_SIGNAL_FALLBACK_HOURS = 1.0

DAILY_LOAD_SIGNAL_ARC_NODE_IDS_BY_FIELD = {
    "work_meetings_count": {
        "DEMO_ARC_NODE_MEETING",  # Meeting
    },
    "after_work_activity_count": {
        "DEMO_ARC_NODE_FELLOWSHIP",  # Fellowship
        "DEMO_ARC_NODE_CHURCH_MEETINGS",  # Church Meetings
        "DEMO_ARC_NODE_DATE_NIGHT",  # Date Night
    },
    "errands_appointments_count": {
        "DEMO_ARC_NODE_FAMILY_APPOINTMENTS",  # Family Appointments
        "DEMO_ARC_NODE_MY_APPOINTMENTS",  # My Appointments
    },
    "social_commitments_count": {
        "DEMO_ARC_NODE_FELLOWSHIP",  # Fellowship
        "DEMO_ARC_NODE_CHURCH_MEETINGS",  # Church Meetings
        "DEMO_ARC_NODE_DATE_NIGHT",  # Date Night
    },
}
DAILY_LOAD_AFTER_WORK_FIELDS = {"after_work_activity_count"}
DAILY_LOAD_SIGNAL_ARC_NODE_LABELS = {
    "DEMO_ARC_NODE_MEETING": "Meeting",
    "DEMO_ARC_NODE_FELLOWSHIP": "Fellowship",
    "DEMO_ARC_NODE_CHURCH_MEETINGS": "Church Meetings",
    "DEMO_ARC_NODE_DATE_NIGHT": "Date Night",
    "DEMO_ARC_NODE_FAMILY_APPOINTMENTS": "Family Appointments",
    "DEMO_ARC_NODE_MY_APPOINTMENTS": "My Appointments",
}

QUEST_SLOT_ORDER = {
    "Best Fit": 0,
    "Low-Friction": 1,
    "Wild Card": 2,
    "Manual": 3,
}

QUEST_STATUS_TONES = {
    "Offered": "warn",
    "Accepted": "good",
    "Done": "good",
    "Shrunken": "warn",
    "Replaced": "neutral",
    "Skipped": "bad",
}

QUEST_TIME_CAP_MINUTES = {
    "2 min": 2,
    "5 min": 5,
    "10 min": 10,
    "20 min": 20,
    "30 min": 30,
}

QUEST_COMPLETION_STATUS_OPTIONS = ["Done", "Shrunken", "Skipped"]
QUEST_COMPLETED_STATUSES = set(QUEST_COMPLETION_STATUS_OPTIONS)
QUEST_LINGER_STATUSES = {"Done", "Shrunken"}
QUEST_COST_FELT_OPTIONS = ["Light", "Normal", "Costly"]
QUEST_SWITCHABLE_STATUSES = {"Offered", "Accepted", "Replaced"}
QUEST_PNEUMA_TARGET_PROP = "Pneuma Target"
QUEST_PNEUMA_TARGET_KEYS = {
    "Capacity": "capacity",
    "Alignment": "alignment",
    "Headroom": "headroom",
    "Steadiness": "steadiness",
}
QUEST_LINGER_POINTS_BY_DAY = {
    0: 5,
    1: 3,
    2: 1,
}
QUEST_BASE_XP_BY_DIFFICULTY = {
    "Light": 15,
    "Normal": 22,
    "Costly": 30,
}
QUEST_ENERGY_XP_BONUS = {
    "Low": 0,
    "Medium": 3,
    "High": 6,
}
QUEST_TIME_XP_BONUS = {
    2: 0,
    5: 1,
    10: 3,
    20: 5,
    30: 7,
}
QUEST_COST_FELT_MULTIPLIER = {
    "Light": 1.0,
    "Normal": 1.15,
    "Costly": 1.35,
}
QUEST_STATUS_XP_MULTIPLIER = {
    "Done": 1.0,
    "Shrunken": 0.6,
    "Skipped": 0.0,
}
ECHOFORM_PRACTICE_BASE_XP = 10.0

STATE_SHIFTS_DB_ID = "DEMO_DB_STATE_SHIFTS"  # State Shifts
STATE_SHIFT_TIMESTAMP_PROP = "Timestamp"
STATE_SHIFT_RESONANCE_PROP = "Resonance"
STATE_SHIFT_UNDERCURRENT_PROP = "Related Undercurrent Day"

STATE_SHIFT_TRIGGER_OPTIONS = [
    "task friction",
    "interruption",
    "relational tension",
    "uncertainty",
    "body discomfort",
    "decision overload",
    "overstimulation",
    "temptation / escape pull",
    "transition moment",
    "no obvious trigger",
]

STATE_SHIFT_DIRECTION_OPTIONS = ["worse", "better", "same"]

STATE_SHIFT_RESPONSE_OPTIONS = [
    "pushed through",
    "avoided",
    "prayed",
    "moved body",
    "ate / drank",
    "rested",
    "named truth",
    "talked to someone",
    "cleaned / reset space",
    "scrolled / escaped",
    "returned to intent",
]

STATE_SHIFT_EFFECT_OPTIONS = [
    "unknown",
    "worse",
    "same",
    "slightly better",
    "clearly better",
]

STATE_SHIFT_INTENT_TESTED_OPTIONS = [
    "not tested",
    "lightly tested",
    "clearly tested",
    "failed test",
    "passed test",
]

STATE_SHIFT_FORMATION_OPTIONS = [
    "no",
    "insight only",
    "possible formation",
    "embodied formation",
]

STATE_SHIFT_NEED_OPTIONS = [
    "food",
    "water",
    "movement",
    "prayer",
    "quiet",
    "sunlight",
    "break",
    "conversation",
    "recommitment",
    "deep work block",
    "cleanup/reset",
]

STATE_SHIFT_BODY_CUE_OPTIONS = [
    "shoulders tight",
    "chest pressure",
    "headache",
    "stomach tension",
    "heavy eyes",
    "restless legs",
    "low breath",
    "general fatigue",
    "pain flare",
    "none noticed",
]

UNDERCURRENT_PHASES = [
    {
        "key": "morning",
        "label": "Morning",
        "window": "2:00 AM - 10:59 AM America/Chicago",
        "ui_path": "/notion/undercurrent/morning/ui",
    },
    {
        "key": "midday",
        "label": "Midday",
        "window": "11:00 AM - 5:59 PM America/Chicago",
        "ui_path": "/notion/undercurrent/midday/ui",
    },
    {
        "key": "evening",
        "label": "Evening",
        "window": "6:00 PM - 1:59 AM America/Chicago",
        "ui_path": "/notion/undercurrent/evening/ui",
    },
]

RHYTHMIC_RITES_MANUAL_TASKS = {"Abiding"}

UNDERCURRENT_STATE_SHIFT_SCORES = {
    "more open": 90.0,
    "same": 60.0,
    "more closed": 25.0,
}

STATE_SHIFT_INTENSITY_SCORES = {"None": 100.0, "Mild": 68.0, "Strong": 28.0}

REGULATION_RESPONSE_SCORES = {
    "None": 35.0,
    "Avoided": 15.0,
    "Paused": 60.0,
    "Repaired": 82.0,
    "Recentered": 100.0,
}

STATE_SHIFT_RESPONSE_SCORES = {
    "pushed through": 45.0,
    "avoided": 18.0,
    "prayed": 84.0,
    "moved body": 78.0,
    "ate / drank": 72.0,
    "rested": 74.0,
    "named truth": 88.0,
    "talked to someone": 80.0,
    "cleaned / reset space": 70.0,
    "scrolled / escaped": 10.0,
    "returned to intent": 94.0,
}

STATE_SHIFT_EFFECT_SCORES = {
    "unknown": 45.0,
    "worse": 20.0,
    "same": 55.0,
    "slightly better": 78.0,
    "clearly better": 96.0,
}

STATE_SHIFT_INTENT_TESTED_SCORES = {
    "not tested": 45.0,
    "lightly tested": 70.0,
    "clearly tested": 78.0,
    "failed test": 20.0,
    "passed test": 95.0,
}

STATE_SHIFT_FORMATION_SCORES = {
    "no": 35.0,
    "insight only": 60.0,
    "possible formation": 78.0,
    "embodied formation": 95.0,
}


def _notion_headers() -> dict:
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN is not set on the server")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": str(NOTION_VERSION).strip(),
        "Content-Type": "application/json",
    }


def notion_get(path: str) -> dict:
    path = "/" + path.lstrip("/")
    url = f"https://api.notion.com/v1{path}"
    print("NOTION GET:", url)
    r = requests.get(url, headers=_notion_headers(), timeout=20)
    if not r.ok:
        raise HTTPException(
            status_code=502,
            detail={"notion_status": r.status_code, "notion_body": r.text, "url": url},
        )
    return r.json()


def notion_post(path: str, payload: dict) -> dict:
    path = "/" + path.lstrip("/")
    url = f"https://api.notion.com/v1{path}"
    print("NOTION POST:", url)
    r = requests.post(url, headers=_notion_headers(), json=payload, timeout=20)
    if not r.ok:
        raise HTTPException(
            status_code=502,
            detail={"notion_status": r.status_code, "notion_body": r.text, "url": url},
        )
    return r.json()


def notion_patch(path: str, payload: dict) -> dict:
    path = "/" + path.lstrip("/")
    url = f"https://api.notion.com/v1{path}"
    print("NOTION PATCH:", url)
    r = requests.patch(url, headers=_notion_headers(), json=payload, timeout=20)
    if not r.ok:
        raise HTTPException(
            status_code=502,
            detail={"notion_status": r.status_code, "notion_body": r.text, "url": url},
        )
    return r.json()


def notion_append_children(block_id: str, children: list[dict]) -> dict:
    return notion_patch(f"/blocks/{block_id}/children", {"children": children})


@lru_cache(maxsize=32)
def get_data_source_id(database_id: str) -> str:
    """
    2025-09-03+: Databases are containers; query/creation happens via data_sources.
    """
    db = notion_get(f"/databases/{database_id}")
    dss = db.get("data_sources") or []
    if not dss:
        raise HTTPException(status_code=500, detail=f"No data_sources found for database {database_id}")
    return dss[0]["id"]


@lru_cache(maxsize=32)
def get_data_source_schema(data_source_id: str) -> dict:
    ds = notion_get(f"/data_sources/{data_source_id}")
    props = ds.get("properties")
    if not isinstance(props, dict) or not props:
        raise HTTPException(status_code=500, detail=f"No properties found for data_source {data_source_id}")
    return props


@lru_cache(maxsize=16)
def get_db_title_prop_name(database_id: str) -> str:
    ds_id = get_data_source_id(database_id)
    props = get_data_source_schema(ds_id)
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            return prop_name
    raise HTTPException(status_code=500, detail=f"Could not find title property for DB {database_id}")


@lru_cache(maxsize=1)
def ensure_undercurrent_daily_load_schema() -> None:
    under_ds_id = get_data_source_id(UNDERCURRENT_DB_ID)
    schema = get_data_source_schema(under_ds_id)
    updates: dict[str, dict[str, Any]] = {}

    for field in DAILY_LOAD_FIELD_DEFS:
        if field["property"] not in schema:
            updates[field["property"]] = {"number": {"format": "number"}}

    if not updates:
        return None

    notion_patch(f"/data_sources/{under_ds_id}", {"properties": updates})
    get_data_source_schema.cache_clear()
    get_db_title_prop_name.cache_clear()
    get_data_source_schema(under_ds_id)
    return None


def get_daily_page(today_iso: str) -> dict | None:
    daily_ds_id = get_data_source_id(DAILY_DB_ID)

    q = {"filter": {"property": "Date", "date": {"equals": today_iso}}, "page_size": 1}
    res = notion_post(f"/data_sources/{daily_ds_id}/query", q)
    results = res.get("results", [])
    if results:
        return results[0]
    return None


def find_or_create_daily_page(today_iso: str) -> str:
    """
    Find today's daily page by Date == today_iso; create it if missing.
    """
    page = get_daily_page(today_iso)
    if page:
        return page["id"]

    daily_ds_id = get_data_source_id(DAILY_DB_ID)

    title_prop = get_db_title_prop_name(DAILY_DB_ID)
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": daily_ds_id},
        "properties": {
            title_prop: {"title": [{"text": {"content": today_iso}}]},
            "Date": {"date": {"start": today_iso}},
        },
    }
    page = notion_post("/pages", payload)
    return page["id"]


def _normalize_echoform_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


@lru_cache(maxsize=1)
def _echoform_image_index() -> dict[str, str]:
    index: dict[str, str] = {}
    if ECHOFORM_IMAGE_DIR.exists():
        for path in ECHOFORM_IMAGE_DIR.iterdir():
            if path.is_file():
                index[_normalize_echoform_key(path.stem)] = path.name

    for alias, filename in ECHOFORM_IMAGE_NAME_ALIASES.items():
        index[alias] = filename

    return index


def _echoform_image_url(name: str | None) -> str | None:
    key = _normalize_echoform_key(name)
    if not key:
        return None

    image_index = _echoform_image_index()
    filename = image_index.get(key)
    if filename is None and key.startswith("the"):
        filename = image_index.get(key[3:])
    if filename is None and key == "cloakofbecoming":
        filename = image_index.get("cloackofbecoming")
    if not filename:
        return None

    return f"/static/Echoforms/{quote(filename)}"


def _redirect_home(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/?msg={quote(message, safe='')}", status_code=303)


def _redirect_home_with_log(message: str, log_file: str | None = None) -> RedirectResponse:
    url = f"/?msg={quote(message, safe='')}"
    if log_file:
        url += f"&last_log={quote(log_file, safe='')}"
    return RedirectResponse(url=url, status_code=303)


def _safe_return_to(value: str | None, default: str = "/") -> str:
    path = (value or "").strip()
    if path.startswith("/"):
        return path
    return default


def _redirect_to(path: str, message: str) -> RedirectResponse:
    return RedirectResponse(url=f"{path}?msg={quote(message, safe='')}", status_code=303)


def _notion_title_value(value: str) -> dict:
    text = (value or "").strip()
    if not text:
        return {"title": []}
    return {"title": [{"type": "text", "text": {"content": text[:2000]}}]}


def _notion_rich_text_items(value: str) -> list[dict]:
    text = (value or "").strip()
    if not text:
        return []
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]


def _notion_rich_text_value(value: str) -> dict:
    return {"rich_text": _notion_rich_text_items(value)}


def _validate_int(label: str, value: int) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")


def _validate_score(label: str, value: int) -> int:
    return _validate_bounded_int(label, value, 1, 5)


def _validate_bounded_int(label: str, value: int, minimum: int, maximum: int) -> int:
    number = _validate_int(label, value)
    if number < minimum or number > maximum:
        raise HTTPException(status_code=400, detail=f"{label} must be between {minimum} and {maximum}")
    return number


def _validate_positive_int(label: str, value: int | str) -> int:
    number = _validate_int(label, value)
    if number < 1:
        raise HTTPException(status_code=400, detail=f"{label} must be at least 1")
    return number


def _validate_non_negative_int(label: str, value: int | str) -> int:
    number = _validate_int(label, value)
    if number < 0:
        raise HTTPException(status_code=400, detail=f"{label} cannot be negative")
    return number


def _validate_choice(label: str, value: str, options: list[str]) -> str:
    v = (value or "").strip()
    if not v:
        raise HTTPException(status_code=400, detail=f"{label} cannot be blank")
    if v not in options:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: '{v}'. Allowed: {options}")
    return v


def _validate_multi_choice(label: str, values: list[str], options: list[str]) -> list[str]:
    cleaned = _clean_multi_choice_values(label, values, options)
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{label} needs at least one selection")
    return cleaned


def _clean_multi_choice_values(label: str, values: list[str], options: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen = set()

    for raw in values or []:
        value = (raw or "").strip()
        if not value:
            continue
        if value not in options:
            raise HTTPException(status_code=400, detail=f"Invalid {label}: '{value}'. Allowed: {options}")
        if value not in seen:
            cleaned.append(value)
            seen.add(value)

    return cleaned


def _validate_optional_multi_choice(label: str, values: list[str], options: list[str]) -> list[str]:
    return _clean_multi_choice_values(label, values, options)


def _validate_text(label: str, value: str, *, allow_blank: bool = False) -> str:
    text = (value or "").strip()
    if not text and not allow_blank:
        raise HTTPException(status_code=400, detail=f"{label} cannot be blank")
    return text


def _validate_bedtime(label: str, value: str) -> str:
    text = _validate_text(label, value)
    parts = _bedtime_parts(text)
    if parts is None:
        raise HTTPException(status_code=400, detail=f"{label} must use HH:MM in 24-hour time")
    hour, minute = parts
    return f"{hour:02d}:{minute:02d}"


def _validate_optional_choice(label: str, value: str | None, options: list[str]) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return _validate_choice(label, text, options)


def _validate_non_negative_number(label: str, value: int | float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} must be a number")

    if number < 0:
        raise HTTPException(status_code=400, detail=f"{label} cannot be negative")

    return number


def _parse_datetime_input(label: str, value: str | None, fallback_tz: ZoneInfo) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.now(fallback_tz)

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label} must be a valid date/time")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=fallback_tz)

    return dt


def find_undercurrent_page(today_iso: str) -> str | None:
    page = get_undercurrent_page(today_iso)
    if page:
        return page["id"]
    return None


def get_undercurrent_page(today_iso: str) -> dict | None:
    under_ds_id = get_data_source_id(UNDERCURRENT_DB_ID)
    q = {"filter": {"property": UNDER_DATE_PROP, "date": {"equals": today_iso}}, "page_size": 1}
    res = notion_post(f"/data_sources/{under_ds_id}/query", q)
    results = res.get("results", [])
    if results:
        return results[0]
    return None


def _after_work_signal_hours(
    start: datetime | None,
    end: datetime | None,
    day_start: datetime,
) -> float:
    if start is None:
        return 0.0

    threshold = day_start.replace(hour=AFTER_WORK_SIGNAL_START_HOUR, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    local_start = start.astimezone(UNDERCURRENT_TZ)
    effective_end = end if end and end > start else (start + timedelta(hours=AFTER_WORK_SIGNAL_FALLBACK_HOURS))
    local_end = effective_end.astimezone(UNDERCURRENT_TZ)
    overlap_start = max(local_start, threshold)
    overlap_end = min(local_end, day_end)
    if overlap_end <= overlap_start:
        return 0.0
    return _duration_minutes(overlap_start, overlap_end) / 60.0


def derive_daily_load_from_signal_field(today_iso: str) -> dict[str, Any]:
    day_value = date.fromisoformat(today_iso)
    day_start = datetime(day_value.year, day_value.month, day_value.day, tzinfo=UNDERCURRENT_TZ)
    tomorrow_start = day_start + timedelta(days=1)

    signal_ds_id = get_data_source_id(SIGNAL_DB_ID)
    rows = _query_data_source_all(
        signal_ds_id,
        {
            "filter": {
                "and": [
                    {"property": SIGNAL_DATE_PROP, "date": {"on_or_after": day_start.isoformat()}},
                    {"property": SIGNAL_DATE_PROP, "date": {"before": tomorrow_start.isoformat()}},
                ]
            },
            "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    values = {field["field"]: 0 for field in DAILY_LOAD_FIELD_DEFS}
    details = {field["field"]: [] for field in DAILY_LOAD_FIELD_DEFS}
    matched_entry_ids: set[str] = set()

    for row in rows:
        properties = row.get("properties") or {}
        start, end = _signal_date_range(properties)
        after_work_hours = _after_work_signal_hours(start, end, day_start)
        arc_node_ids = _prop_relation_ids(properties, SIGNAL_ARC_PROP)
        if start is None or not arc_node_ids:
            continue

        arc_node_id = arc_node_ids[0]
        title = _prop_title_text(properties, SIGNAL_TITLE_PROP) or "Untitled signal"

        for field in DAILY_LOAD_FIELD_DEFS:
            field_name = field["field"]
            if arc_node_id not in DAILY_LOAD_SIGNAL_ARC_NODE_IDS_BY_FIELD.get(field_name, set()):
                continue
            if field_name in DAILY_LOAD_AFTER_WORK_FIELDS:
                if after_work_hours <= 0:
                    continue
                values[field_name] += after_work_hours
            else:
                values[field_name] += 1
            details[field_name].append(
                {
                    "title": title,
                    "node": DAILY_LOAD_SIGNAL_ARC_NODE_LABELS.get(arc_node_id, "Signal Field"),
                    "start": start.isoformat(),
                    "end": end.isoformat() if end else None,
                    "hours": round(after_work_hours, 2) if field_name in DAILY_LOAD_AFTER_WORK_FIELDS else None,
                }
            )
            matched_entry_ids.add(row["id"])

    for field_name in DAILY_LOAD_AFTER_WORK_FIELDS:
        values[field_name] = round(float(values[field_name]), 2)

    return {
        "values": values,
        "details": details,
        "source_entry_count": len(matched_entry_ids),
    }


def sync_undercurrent_daily_load_from_signal_field(
    today_iso: str,
) -> dict[str, Any]:
    ensure_undercurrent_daily_load_schema()
    derived = derive_daily_load_from_signal_field(today_iso)
    page = get_undercurrent_page(today_iso)

    if not page and not derived["source_entry_count"]:
        return {
            **derived,
            "undercurrent_page_id": None,
            "daily_page_id": None,
            "created_today_page": False,
            "skipped": True,
        }

    daily_load_properties = {
        field["property"]: {"number": derived["values"][field["field"]]}
        for field in DAILY_LOAD_FIELD_DEFS
    }

    if not page:
        daily_load_properties[get_db_title_prop_name(UNDERCURRENT_DB_ID)] = _notion_title_value("Daily Load")

    undercurrent_page_id, daily_page_id, created = upsert_undercurrent_properties(
        daily_load_properties,
        today_iso=today_iso,
    )
    return {
        **derived,
        "undercurrent_page_id": undercurrent_page_id,
        "daily_page_id": daily_page_id,
        "created_today_page": created,
        "skipped": False,
    }


def _sync_daily_load_dates(date_isos: set[str]) -> str | None:
    errors: list[str] = []
    for date_iso in sorted(date_isos):
        try:
            sync_undercurrent_daily_load_from_signal_field(date_iso)
        except Exception as exc:
            errors.append(f"{date_iso}: {exc}")
    if not errors:
        return None
    return "; ".join(errors)


def _prop_number(properties: dict, name: str) -> int | float | None:
    return (properties.get(name) or {}).get("number")


def _prop_select_name(properties: dict, name: str) -> str | None:
    selected = (properties.get(name) or {}).get("select") or {}
    return selected.get("name")


def _prop_status_name(properties: dict, name: str) -> str | None:
    selected = (properties.get(name) or {}).get("status") or {}
    return selected.get("name")


def _prop_multi_select_count(properties: dict, name: str) -> int:
    return len((properties.get(name) or {}).get("multi_select") or [])


def _prop_multi_select_names(properties: dict, name: str) -> list[str]:
    values = (properties.get(name) or {}).get("multi_select") or []
    return [item.get("name") for item in values if item.get("name")]


def _prop_rich_text_count(properties: dict, name: str) -> int:
    return len((properties.get(name) or {}).get("rich_text") or [])


def _prop_rich_text_text(properties: dict, name: str) -> str:
    rich_text = (properties.get(name) or {}).get("rich_text") or []
    return "".join(
        item.get("plain_text") or ((item.get("text") or {}).get("content") or "")
        for item in rich_text
    ).strip()


def _prop_plain_text(properties: dict, name: str) -> str:
    value = properties.get(name)
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    for key in ("rich_text", "title", "text"):
        items = value.get(key) or []
        if not isinstance(items, list):
            continue
        text = "".join(
            item.get("plain_text") or ((item.get("text") or {}).get("content") or "")
            for item in items
            if isinstance(item, dict)
        ).strip()
        if text:
            return text

    formula = value.get("formula") or {}
    if formula.get("type") == "string":
        return str(formula.get("string") or "").strip()

    for key in ("plain_text", "url", "email", "phone_number"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()

    return ""


def _prop_title_text(properties: dict, name: str) -> str:
    title = (properties.get(name) or {}).get("title") or []
    return "".join(
        item.get("plain_text") or ((item.get("text") or {}).get("content") or "")
        for item in title
    ).strip()


def _prop_checkbox(properties: dict, name: str) -> bool:
    return bool((properties.get(name) or {}).get("checkbox"))


def _prop_formula_number(properties: dict, name: str) -> int | float | None:
    formula = (properties.get(name) or {}).get("formula") or {}
    if formula.get("type") != "number":
        return None
    return formula.get("number")


def _prop_numeric_value(properties: dict, name: str) -> int | float | None:
    value = _prop_number(properties, name)
    if value is not None:
        return value
    return _prop_formula_number(properties, name)


def _prop_rollup_number(properties: dict, name: str) -> int | float | None:
    rollup = (properties.get(name) or {}).get("rollup") or {}
    if rollup.get("type") != "number":
        return None
    return rollup.get("number")


def _prop_date_start(properties: dict, name: str) -> str | None:
    date_value = (properties.get(name) or {}).get("date") or {}
    return date_value.get("start")


def _prop_rollup_date_start(properties: dict, name: str) -> str | None:
    rollup = (properties.get(name) or {}).get("rollup") or {}
    if rollup.get("type") != "date":
        return None
    date_value = rollup.get("date") or {}
    return date_value.get("start")


def _rollup_item_text(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""

    item_type = item.get("type")
    if item_type in {"rich_text", "title"}:
        values = item.get(item_type) or []
        return "".join(
            value.get("plain_text") or ((value.get("text") or {}).get("content") or "")
            for value in values
            if isinstance(value, dict)
        ).strip()

    if item_type == "number":
        value = item.get("number")
        return "" if value is None else str(value)

    if item_type == "select":
        return ((item.get("select") or {}).get("name") or "").strip()

    if item_type == "date":
        date_value = item.get("date") or {}
        return (date_value.get("start") or "").strip()

    return ""


def _prop_rollup_texts(properties: dict, name: str) -> list[str]:
    rollup = (properties.get(name) or {}).get("rollup") or {}
    if rollup.get("type") != "array":
        return []

    values: list[str] = []
    for item in rollup.get("array") or []:
        text = _rollup_item_text(item)
        if text:
            values.append(text)
    return values


def _prop_relation_ids(properties: dict, name: str) -> list[str]:
    relation = (properties.get(name) or {}).get("relation") or []
    return [item.get("id") for item in relation if item.get("id")]


def _query_data_source_all(data_source_id: str, payload: dict) -> list[dict]:
    query = dict(payload)
    results: list[dict] = []

    while True:
        response = notion_post(f"/data_sources/{data_source_id}/query", query)
        results.extend(response.get("results", []))
        if not response.get("has_more") or not response.get("next_cursor"):
            return results
        query["start_cursor"] = response["next_cursor"]


def get_latest_abiding_moments_message(page_size: int = 10) -> dict | None:
    response = notion_post(
        f"/data_sources/{ABIDING_MOMENTS_MESSAGES_DS_ID}/query",
        {
            "sorts": [{"property": ABIDING_MOMENTS_DATE_PROP, "direction": "descending"}],
            "page_size": max(1, min(page_size, 25)),
        },
    )
    results = response.get("results", []) or []
    for row in results:
        hymn = _prop_plain_text(row.get("properties") or {}, ABIDING_MOMENTS_HYMN_PROP)
        if hymn:
            return row
    return results[0] if results else None


def _format_compact_date(value: str | None) -> str | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.split("T", 1)[0]

    if dt.year == datetime.now(TZ).year:
        return dt.strftime("%b %d").replace(" 0", " ")
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _format_cadence_label(cadence: int | float | None) -> str | None:
    if cadence is None:
        return None

    if int(cadence) == cadence:
        cadence = int(cadence)

    if cadence == 1:
        return "Daily"
    return f"Every {cadence:g} days"


def _format_number_display(value: int | float | None) -> str | None:
    if value is None:
        return None

    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _merge_behavioral_signal_entities(
    entities: dict[str, dict[str, Any]],
    behavioral: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    merged = dict(entities)
    suite = behavioral
    if suite is None:
        try:
            suite = _behavioral_signal_suite()
        except Exception:
            suite = {}

    sedentary = _state_float((suite or {}).get("sedentary_streak_min"))
    if sedentary is not None:
        merged["sensor.index_sedentary_streak_min"] = {
            "state": _format_number_display(sedentary) or str(sedentary),
            "attributes": {
                "unit_of_measurement": "min",
                "friendly_name": "Index Sedentary Streak Min",
            },
        }
    return merged


def _local_date_from_iso(value: str | None) -> date | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).date()


def _is_date_today(value: str | None) -> bool:
    local_date = _local_date_from_iso(value)
    return bool(local_date and local_date == datetime.now(TZ).date())


def _rite_is_due_today(
    latest_complete_start: str | None,
    cadence: int | float | None,
    now: datetime | None = None,
) -> bool:
    completed_on = _local_date_from_iso(latest_complete_start)
    if completed_on is None:
        return True

    cadence_days = max(int(cadence or 1), 1)
    today = (now or datetime.now(TZ)).date()
    return (today - completed_on).days >= cadence_days


def get_active_rhythmic_rites() -> list[dict]:
    rites_ds_id = get_data_source_id(RHYTHMIC_RITES_DB_ID)
    rows = _query_data_source_all(
        rites_ds_id,
        {
            "filter": {"property": "Active", "checkbox": {"equals": True}},
            "sorts": [{"property": "Task Name", "direction": "ascending"}],
            "page_size": 100,
        },
    )

    rites = []
    for row in rows:
        properties = row.get("properties") or {}
        name = _prop_title_text(properties, "Task Name")
        cadence = _prop_number(properties, "Cadence")
        latest_complete_start = _prop_rollup_date_start(properties, "Latest Complete Date")
        completed_on_current_day = _is_date_today(latest_complete_start)
        # Treat cadence as calendar-day based so daily rites reset at midnight,
        # not exactly 24 hours after the last completion timestamp.
        if not (completed_on_current_day or _rite_is_due_today(latest_complete_start, cadence)):
            continue

        rites.append(
            {
                "page_id": row["id"],
                "name": name,
                "description": _prop_rich_text_text(properties, "Description"),
                "cadence": cadence,
                "cadence_label": _format_cadence_label(cadence),
                "complete_today": completed_on_current_day,
                "manual": name in RHYTHMIC_RITES_MANUAL_TASKS,
                "latest_complete_label": _format_compact_date(latest_complete_start),
            }
        )

    rites.sort(key=lambda rite: (rite["complete_today"], rite["name"].lower()))
    return rites


def get_undercurrent_snapshot(today_iso: str) -> tuple[dict[str, bool], str]:
    page = get_undercurrent_page(today_iso)
    if not page:
        return ({phase["key"]: False for phase in UNDERCURRENT_PHASES}, "")

    properties = page.get("properties") or {}
    done = {
        "morning": all(
            [
                _prop_number(properties, "Morning Energy") is not None,
                _prop_number(properties, "Morning Clarity") is not None,
                _prop_number(properties, "Morning Mood") is not None,
                _prop_number(properties, "Morning Stress") is not None,
                _prop_number(properties, "Morning Spiritual Orientation") is not None,
                _prop_number(properties, "Morning Wellness") is not None,
                _prop_number(properties, "Sleep Score") is not None,
                _prop_rich_text_count(properties, "Bedtime") > 0,
                _prop_number(properties, "Base HR") is not None,
                _prop_multi_select_count(properties, "Morning State Tags") > 0,
                _prop_multi_select_count(properties, "Main Drag") > 0,
                _prop_rich_text_count(properties, "Daily Intent") > 0,
            ]
        ),
        "midday": all(
            [
                _prop_number(properties, "Midday Energy") is not None,
                _prop_number(properties, "Midday Focus") is not None,
                _prop_number(properties, "Midday Wellness") is not None,
                _prop_select_name(properties, "Midday Drift") is not None,
                _prop_multi_select_count(properties, "Midday Need") > 0,
            ]
        ),
        "evening": all(
            [
                _prop_number(properties, "Day Score") is not None,
                _prop_number(properties, "Evening Wellness") is not None,
                _prop_number(properties, "Evening Spiritual Orientation") is not None,
                _prop_select_name(properties, "Alignment") is not None,
                _prop_select_name(properties, "State Shift") is not None,
                _prop_select_name(properties, "State Shift Intensity") is not None,
                _prop_select_name(properties, "Regulation Response") is not None,
                _prop_multi_select_count(properties, "Primary Disruptor") > 0,
                _prop_multi_select_count(properties, "Carryover") > 0,
                _prop_select_name(properties, "Most Draining") is not None,
                _prop_select_name(properties, "Most Restorative") is not None,
                _prop_rich_text_count(properties, "Reflection Note") > 0,
                _prop_rich_text_count(properties, "Gratitude Note") > 0,
                _prop_multi_select_count(properties, "Tomorrow Need") > 0,
                _prop_rich_text_count(properties, UNDER_LESSON_PROP) > 0,
            ]
        ),
    }
    return done, _prop_rich_text_text(properties, "Daily Intent")


def get_undercurrent_completion(today_iso: str) -> dict[str, bool]:
    done, _ = get_undercurrent_snapshot(today_iso)
    return done


def get_current_undercurrent_phase(now: datetime | None = None) -> str:
    local_now = now or datetime.now(UNDERCURRENT_TZ)
    hour = local_now.hour
    if 2 <= hour < 11:
        return "morning"
    if 11 <= hour < 18:
        return "midday"
    return "evening"


def _phase_exists(phase: str) -> bool:
    return any(item["key"] == phase for item in UNDERCURRENT_PHASES)


def build_undercurrent_template_context(visible_phase: str | None = None) -> dict:
    current_phase = get_current_undercurrent_phase()
    phase_to_show = visible_phase or current_phase
    if not _phase_exists(phase_to_show):
        raise HTTPException(status_code=404, detail=f"Unknown Undercurrent phase: {phase_to_show}")

    today_iso = datetime.now(UNDERCURRENT_TZ).date().isoformat()
    try:
        done, daily_intent = get_undercurrent_snapshot(today_iso)
    except Exception:
        done = {phase["key"]: False for phase in UNDERCURRENT_PHASES}
        daily_intent = ""

    try:
        sync_undercurrent_daily_load_from_signal_field(today_iso)
    except Exception:
        pass

    return {
        "current_undercurrent_phase": current_phase,
        "visible_phase": phase_to_show,
        "undercurrent_done": done,
        "daily_intent": daily_intent,
        "undercurrent_phases": UNDERCURRENT_PHASES,
        "morning_state_tag_options": MORNING_STATE_TAG_OPTIONS,
        "main_drag_options": MAIN_DRAG_OPTIONS,
        "midday_drift_options": MIDDAY_DRIFT_OPTIONS,
        "midday_need_options": MIDDAY_NEED_OPTIONS,
        "alignment_options": ALIGNMENT_OPTIONS,
        "undercurrent_state_shift_options": UNDERCURRENT_STATE_SHIFT_OPTIONS,
        "state_shift_intensity_options": STATE_SHIFT_INTENSITY_OPTIONS,
        "regulation_response_options": REGULATION_RESPONSE_OPTIONS,
        "primary_disruptor_options": PRIMARY_DISRUPTOR_OPTIONS,
        "carryover_options": CARRYOVER_OPTIONS,
        "neglected_domain_options": NEGLECTED_DOMAIN_OPTIONS,
        "most_draining_options": MOST_DRAINING_OPTIONS,
        "most_restorative_options": MOST_RESTORATIVE_OPTIONS,
        "tomorrow_need_options": TOMORROW_NEED_OPTIONS,
    }


def build_state_shift_template_context(now: datetime | None = None) -> dict:
    local_now = (now or datetime.now(TZ)).replace(second=0, microsecond=0)
    return {
        "state_shift_trigger_options": STATE_SHIFT_TRIGGER_OPTIONS,
        "state_shift_direction_options": STATE_SHIFT_DIRECTION_OPTIONS,
        "state_shift_response_options": STATE_SHIFT_RESPONSE_OPTIONS,
        "state_shift_effect_options": STATE_SHIFT_EFFECT_OPTIONS,
        "state_shift_intent_tested_options": STATE_SHIFT_INTENT_TESTED_OPTIONS,
        "state_shift_formation_options": STATE_SHIFT_FORMATION_OPTIONS,
        "state_shift_need_options": STATE_SHIFT_NEED_OPTIONS,
        "state_shift_body_cue_options": STATE_SHIFT_BODY_CUE_OPTIONS,
        "state_shift_timestamp_default": local_now.strftime("%Y-%m-%dT%H:%M"),
    }


def _normalize_completion_ratio(value: int | float | None) -> float | None:
    if value is None:
        return None

    ratio = float(value)
    if ratio > 1:
        ratio = ratio / 100.0
    return max(0.0, ratio)


def _normalize_title_key(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def get_library_books() -> list[dict[str, Any]]:
    library_ds_id = get_data_source_id(LIBRARY_DB_ID)
    title_prop = get_db_title_prop_name(LIBRARY_DB_ID)
    rows = _query_data_source_all(
        library_ds_id,
        {
            "sorts": [{"property": title_prop, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    books: list[dict[str, Any]] = []
    for row in rows:
        properties = row.get("properties") or {}
        title = _prop_title_text(properties, title_prop)
        if not title:
            continue

        total_chapters = _prop_number(properties, "Chapters")
        chapters_complete = _prop_number(properties, "Chapters Complete")
        completion_ratio = _normalize_completion_ratio(_prop_formula_number(properties, "Completion"))
        completion_percent = None if completion_ratio is None else round(completion_ratio * 100, 1)
        total_display = _format_number_display(total_chapters)
        complete_display = _format_number_display(chapters_complete or 0)

        progress_parts = []
        if complete_display:
            progress_parts.append(complete_display)
        if total_display:
            progress_parts.append(total_display)

        option_suffix_parts = []
        if len(progress_parts) == 2:
            option_suffix_parts.append(f"{progress_parts[0]}/{progress_parts[1]} chapters")
        elif total_display:
            option_suffix_parts.append(f"{total_display} chapters")
        if completion_percent is not None:
            option_suffix_parts.append(f"{completion_percent:.1f}%")

        books.append(
            {
                "page_id": row["id"],
                "title": title,
                "title_key": _normalize_title_key(title),
                "chapters": total_chapters,
                "chapters_complete": chapters_complete,
                "chapters_display": total_display,
                "chapters_complete_display": complete_display,
                "completion_ratio": completion_ratio,
                "completion_percent": completion_percent,
                "option_label": (
                    f"{title} ({' · '.join(option_suffix_parts)})"
                    if option_suffix_parts
                    else title
                ),
            }
        )

    return books


def get_incomplete_library_books() -> list[dict[str, Any]]:
    books = get_library_books()
    return [
        book
        for book in books
        if book["completion_ratio"] is None or book["completion_ratio"] < 1
    ]


def build_book_reflection_template_context() -> dict[str, Any]:
    try:
        books = get_incomplete_library_books()
        return {
            "library_books": books,
            "library_books_available_count": len(books),
            "library_books_error": None,
        }
    except Exception:
        return {
            "library_books": [],
            "library_books_available_count": 0,
            "library_books_error": "Library unavailable.",
        }


def create_library_book_page(title: str, total_chapters: int) -> dict:
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": get_data_source_id(LIBRARY_DB_ID)},
        "properties": {
            get_db_title_prop_name(LIBRARY_DB_ID): _notion_title_value(title),
            "Chapters": {"number": total_chapters},
            "Chapters Complete": {"number": 0},
        },
    }
    return notion_post("/pages", payload)


def append_book_chapter_reflection(book_page_id: str, chapter: int, reflection_note: str) -> None:
    paragraphs = [
        section.strip()
        for section in re.split(r"\n\s*\n", reflection_note.strip())
        if section.strip()
    ]
    if not paragraphs:
        paragraphs = [reflection_note.strip()]

    children = [
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": _notion_rich_text_items(f"Chapter {chapter}"),
            },
        }
    ]
    children.extend(
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": _notion_rich_text_items(paragraph),
            },
        }
        for paragraph in paragraphs
    )
    notion_append_children(book_page_id, children)


def upsert_undercurrent_properties(
    properties: dict,
    *,
    today_iso: str | None = None,
) -> tuple[str, str, bool]:
    today_iso = today_iso or datetime.now(UNDERCURRENT_TZ).date().isoformat()
    daily_page_id = find_or_create_daily_page(today_iso)
    page_id = find_undercurrent_page(today_iso)
    properties = dict(properties)
    properties[UNDER_VERSION_PROP] = {"number": 3}

    if page_id:
        notion_patch(f"/pages/{page_id}", {"properties": properties})
        return page_id, daily_page_id, False

    under_ds_id = get_data_source_id(UNDERCURRENT_DB_ID)
    title_prop = get_db_title_prop_name(UNDERCURRENT_DB_ID)
    base_properties = {
        title_prop: _notion_title_value(""),
        UNDER_DATE_PROP: {"date": {"start": today_iso}},
        UNDER_REL_PROP: {"relation": [{"id": daily_page_id}]},
    }
    base_properties.update(properties)

    page = notion_post(
        "/pages",
        {
            "parent": {"type": "data_source_id", "data_source_id": under_ds_id},
            "properties": base_properties,
        },
    )
    return page["id"], daily_page_id, True


class MorningLogIn(BaseModel):
    morning_energy: int
    morning_clarity: int
    morning_mood: int
    morning_stress: int
    morning_spiritual_orientation: int
    morning_wellness: int
    sleep_score: int
    bedtime: str
    base_hr: int
    morning_state_tags: list[str] = Field(default_factory=list)
    main_drag: list[str] = Field(default_factory=list)
    daily_intent: str
    morning_notes: str = ""


class MiddayLogIn(BaseModel):
    midday_energy: int
    midday_focus: int
    midday_wellness: int
    midday_drift: str
    midday_need: list[str] = Field(default_factory=list)
    midday_notes: str = ""


class EveningLogIn(BaseModel):
    day_score: int
    evening_wellness: int
    evening_spiritual_orientation: int
    alignment: str
    state_shift: str
    state_shift_intensity: str
    regulation_response: str
    primary_disruptor: list[str] = Field(default_factory=list)
    carryover: list[str] = Field(default_factory=list)
    most_draining: str
    neglected_domain: list[str] = Field(default_factory=list)
    most_restorative: str
    reflection_note: str
    gratitude_note: str
    lesson: str
    tomorrow_need: list[str] = Field(default_factory=list)


class AbidingLogIn(BaseModel):
    reflection_note: str


class DailyNotesIn(BaseModel):
    note: str


def submit_morning_log(body: MorningLogIn) -> dict:
    properties = {
        get_db_title_prop_name(UNDERCURRENT_DB_ID): _notion_title_value("Morning"),
        "Morning Energy": {"number": _validate_score("Morning Energy", body.morning_energy)},
        "Morning Clarity": {"number": _validate_score("Morning Clarity", body.morning_clarity)},
        "Morning Mood": {"number": _validate_score("Morning Mood", body.morning_mood)},
        "Morning Stress": {"number": _validate_score("Morning Stress", body.morning_stress)},
        "Morning Spiritual Orientation": {
            "number": _validate_score("Morning Spiritual Orientation", body.morning_spiritual_orientation)
        },
        "Morning Wellness": {"number": _validate_int("Morning Wellness", body.morning_wellness)},
        "Sleep Score": {"number": _validate_int("Sleep Score", body.sleep_score)},
        "Bedtime": _notion_rich_text_value(_validate_bedtime("Bedtime", body.bedtime)),
        "Base HR": {"number": _validate_int("Base HR", body.base_hr)},
        "Morning State Tags": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice(
                    "Morning State Tags",
                    body.morning_state_tags,
                    MORNING_STATE_TAG_OPTIONS,
                )
            ]
        },
        "Main Drag": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice("Main Drag", body.main_drag, MAIN_DRAG_OPTIONS)
            ]
        },
        "Daily Intent": _notion_rich_text_value(_validate_text("Daily Intent", body.daily_intent)),
    }
    morning_notes = _validate_text("Morning Notes", body.morning_notes, allow_blank=True)
    if morning_notes:
        properties["Morning Notes"] = _notion_rich_text_value(morning_notes)

    page_id, daily_page_id, created = upsert_undercurrent_properties(properties)
    quest_offer_result: dict[str, Any]
    try:
        quest_offer_result = generate_morning_quest_offers(replace_only_offered=True)
    except Exception as exc:
        quest_offer_result = {
            "state": "error",
            "created_count": 0,
            "replaced_count": 0,
            "offers": [],
            "error": str(exc),
        }

    return {
        "ok": True,
        "phase": "morning",
        "created_today_page": created,
        "undercurrent_page_id": page_id,
        "daily_page_id": daily_page_id,
        "quest_offer_state": quest_offer_result.get("state"),
        "quest_offers_created": quest_offer_result.get("created_count", 0),
        "quest_offers_replaced": quest_offer_result.get("replaced_count", 0),
    }


def submit_midday_log(body: MiddayLogIn) -> dict:
    properties = {
        get_db_title_prop_name(UNDERCURRENT_DB_ID): _notion_title_value("Midday"),
        "Midday Energy": {"number": _validate_score("Midday Energy", body.midday_energy)},
        "Midday Focus": {"number": _validate_score("Midday Focus", body.midday_focus)},
        "Midday Wellness": {"number": _validate_int("Midday Wellness", body.midday_wellness)},
        "Midday Drift": {"select": {"name": _validate_choice("Midday Drift", body.midday_drift, MIDDAY_DRIFT_OPTIONS)}},
        "Midday Need": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice("Midday Need", body.midday_need, MIDDAY_NEED_OPTIONS)
            ]
        },
    }
    midday_notes = _validate_text("Midday Notes", body.midday_notes, allow_blank=True)
    if midday_notes:
        properties["Midday Notes"] = _notion_rich_text_value(midday_notes)

    page_id, daily_page_id, created = upsert_undercurrent_properties(properties)
    return {
        "ok": True,
        "phase": "midday",
        "created_today_page": created,
        "undercurrent_page_id": page_id,
        "daily_page_id": daily_page_id,
    }


def submit_evening_log(body: EveningLogIn) -> dict:
    properties = {
        get_db_title_prop_name(UNDERCURRENT_DB_ID): _notion_title_value("Night"),
        "Day Score": {"number": _validate_score("Day Score", body.day_score)},
        "Evening Wellness": {"number": _validate_int("Evening Wellness", body.evening_wellness)},
        "Evening Spiritual Orientation": {
            "number": _validate_score(
                "Evening Spiritual Orientation",
                body.evening_spiritual_orientation,
            )
        },
        "Alignment": {"select": {"name": _validate_choice("Alignment", body.alignment, ALIGNMENT_OPTIONS)}},
        "State Shift": {
            "select": {
                "name": _validate_choice(
                    "State Shift",
                    body.state_shift,
                    UNDERCURRENT_STATE_SHIFT_OPTIONS,
                )
            }
        },
        "State Shift Intensity": {
            "select": {
                "name": _validate_choice(
                    "State Shift Intensity",
                    body.state_shift_intensity,
                    STATE_SHIFT_INTENSITY_OPTIONS,
                )
            }
        },
        "Regulation Response": {
            "select": {
                "name": _validate_choice(
                    "Regulation Response",
                    body.regulation_response,
                    REGULATION_RESPONSE_OPTIONS,
                )
            }
        },
        "Primary Disruptor": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice(
                    "Primary Disruptor",
                    body.primary_disruptor,
                    PRIMARY_DISRUPTOR_OPTIONS,
                )
            ]
        },
        "Carryover": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice("Carryover", body.carryover, CARRYOVER_OPTIONS)
            ]
        },
        "Most Draining": {
            "select": {"name": _validate_choice("Most Draining", body.most_draining, MOST_DRAINING_OPTIONS)}
        },
        "Neglected Domain": {
            "multi_select": [
                {"name": value}
                for value in _validate_optional_multi_choice(
                    "Neglected Domain",
                    body.neglected_domain,
                    NEGLECTED_DOMAIN_OPTIONS,
                )
            ]
        },
        "Most Restorative": {
            "select": {
                "name": _validate_choice("Most Restorative", body.most_restorative, MOST_RESTORATIVE_OPTIONS)
            }
        },
        "Reflection Note": _notion_rich_text_value(_validate_text("Reflection Note", body.reflection_note)),
        "Gratitude Note": _notion_rich_text_value(_validate_text("Gratitude Note", body.gratitude_note)),
        UNDER_LESSON_PROP: _notion_rich_text_value(_validate_text(UNDER_LESSON_PROP, body.lesson)),
        "Tomorrow Need": {
            "multi_select": [
                {"name": value}
                for value in _validate_multi_choice(
                    "Tomorrow Need",
                    body.tomorrow_need,
                    TOMORROW_NEED_OPTIONS,
                )
            ]
        },
    }

    page_id, daily_page_id, created = upsert_undercurrent_properties(properties)
    return {
        "ok": True,
        "phase": "evening",
        "created_today_page": created,
        "undercurrent_page_id": page_id,
        "daily_page_id": daily_page_id,
    }


def submit_abiding_log(body: AbidingLogIn) -> dict:
    reflection_note = _validate_text("Abiding Notes", body.reflection_note)
    rite_page_id = get_rite_page_id("Abiding")
    if not rite_page_id:
        raise HTTPException(status_code=404, detail="Could not find the 'Abiding' rite in Rhythmic Rites.")

    undercurrent_page_id, daily_page_id, created = upsert_undercurrent_properties(
        {"Abiding Notes": _notion_rich_text_value(reflection_note)}
    )

    signal_result: dict[str, Any] | None = None
    signal_error: str | None = None
    try:
        signal_result = create_rite_signal_entry(task_name="Abiding", rite_page_id=rite_page_id)
    except HTTPException as exc:
        signal_error = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    except Exception as exc:
        signal_error = str(exc)

    return {
        "ok": True,
        "created_today_page": created,
        "undercurrent_page_id": undercurrent_page_id,
        "daily_page_id": daily_page_id,
        "signal_page_id": (signal_result or {}).get("page_id"),
        "signal_skipped": bool((signal_result or {}).get("skipped")),
        "signal_reason": (signal_result or {}).get("reason"),
        "signal_error": signal_error,
    }


def submit_daily_notes(body: DailyNotesIn) -> dict:
    note = _validate_text("Daily Notes", body.note)
    today_iso = datetime.now(UNDERCURRENT_TZ).date().isoformat()
    existing_page = get_undercurrent_page(today_iso)
    existing_notes = ""
    if existing_page:
        existing_notes = _prop_rich_text_text(existing_page.get("properties") or {}, "Daily Notes")

    combined_notes = f"{existing_notes}\n{note}" if existing_notes else note
    undercurrent_page_id, daily_page_id, created = upsert_undercurrent_properties(
        {"Daily Notes": _notion_rich_text_value(combined_notes)}
    )

    return {
        "ok": True,
        "created_today_page": created,
        "undercurrent_page_id": undercurrent_page_id,
        "daily_page_id": daily_page_id,
        "appended": bool(existing_notes),
    }


def _quest_time_cap_minutes(label: str | None) -> int | None:
    if not label:
        return None
    return QUEST_TIME_CAP_MINUTES.get(label)


def _quest_status_tone(status: str | None) -> str:
    return QUEST_STATUS_TONES.get(status or "", "neutral")


def _quest_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    slot = item.get("offer_slot") or ""
    name = item.get("quest_name") or item.get("title") or ""
    return QUEST_SLOT_ORDER.get(slot, 99), name.lower()


def _quest_clean_name(name: str | None, slot: str | None = None) -> str:
    text = (name or "").strip()
    prefix = f"{slot} - " if slot else ""
    if prefix and text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.split("T", 1)[0]).date()
    except ValueError:
        return None


def get_quest_library(*, active_only: bool = True) -> list[dict[str, Any]]:
    quest_ds_id = get_data_source_id(QUEST_LIBRARY_DB_ID)
    title_prop = get_db_title_prop_name(QUEST_LIBRARY_DB_ID)
    query: dict[str, Any] = {
        "sorts": [{"property": "Weight", "direction": "descending"}],
        "page_size": 100,
    }
    if active_only:
        query["filter"] = {"property": "Active", "checkbox": {"equals": True}}
    rows = _query_data_source_all(quest_ds_id, query)

    quests: list[dict[str, Any]] = []
    for row in rows:
        properties = row.get("properties") or {}
        time_cap = _prop_select_name(properties, "Time Cap")
        quests.append(
            {
                "page_id": row["id"],
                "name": _prop_title_text(properties, title_prop),
                "domain": _prop_select_name(properties, "Domain"),
                "difficulty": _prop_select_name(properties, "Difficulty"),
                "cooldown_days": int(_prop_number(properties, "Cooldown Days") or 0),
                "weight": _prop_number(properties, "Weight"),
                "energy_required": _prop_select_name(properties, "Energy Required"),
                "time_cap": time_cap,
                "time_cap_minutes": _quest_time_cap_minutes(time_cap),
                "carryover_match": _prop_multi_select_names(properties, "Carryover Match"),
                "need_match": _prop_multi_select_names(properties, "Need Match"),
                "signal_tags": _prop_multi_select_names(properties, "Signal Tags"),
                "drag_match": _prop_multi_select_names(properties, "Drag Match"),
                "formation_relevant": _prop_checkbox(properties, "Formation-Relevant?"),
                "success_condition": _prop_rich_text_text(properties, "Success Condition"),
                "shrink_version": _prop_rich_text_text(properties, "Shrink Version"),
                "pneuma_target": _prop_select_name(properties, QUEST_PNEUMA_TARGET_PROP),
            }
        )

    quests.sort(key=lambda quest: (-(quest.get("weight") or 50), quest["name"].lower()))
    return quests


def get_active_quest_library() -> list[dict[str, Any]]:
    return get_quest_library(active_only=True)


def _quest_run_row_to_dict(
    row: dict[str, Any],
    quest_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    properties = row.get("properties") or {}
    title_prop = get_db_title_prop_name(QUEST_RUNS_DB_ID)
    quest_ids = _prop_relation_ids(properties, "Quest")
    quest = (quest_index or {}).get(quest_ids[0]) if quest_ids else None
    title = _prop_title_text(properties, title_prop)
    offer_slot = _prop_select_name(properties, "Offer Slot")
    quest_name = _quest_clean_name((quest or {}).get("name") or title, offer_slot)
    status = _prop_select_name(properties, "Status") or "Offered"
    date_start = _prop_date_start(properties, "Date")

    return {
        "run_page_id": row["id"],
        "title": title,
        "quest_page_id": quest_ids[0] if quest_ids else None,
        "quest_name": quest_name,
        "offer_slot": offer_slot,
        "offer_score": _prop_number(properties, "Offer Score"),
        "selector_version": _prop_rich_text_text(properties, "Selector Version"),
        "date": date_start.split("T", 1)[0] if date_start else None,
        "date_obj": _parse_iso_date(date_start),
        "status": status,
        "status_tone": _quest_status_tone(status),
        "source": _prop_select_name(properties, "Source"),
        "why_offered": _prop_rich_text_text(properties, "Why Offered"),
        "formation_candidate": _prop_checkbox(properties, "Formation Candidate"),
        "xp": _prop_number(properties, "XP"),
        "echoform_xp": _prop_number(properties, "Echoform XP"),
        "cost_felt": _prop_select_name(properties, "Cost Felt"),
        "last_edited_time": row.get("last_edited_time"),
        "domain": (quest or {}).get("domain"),
        "difficulty": (quest or {}).get("difficulty"),
        "energy_required": (quest or {}).get("energy_required"),
        "time_cap": (quest or {}).get("time_cap"),
        "time_cap_minutes": (quest or {}).get("time_cap_minutes"),
        "success_condition": (quest or {}).get("success_condition"),
        "shrink_version": (quest or {}).get("shrink_version"),
        "pneuma_target": (quest or {}).get("pneuma_target"),
    }


def get_recent_quest_runs(days_back: int = 45, now: datetime | None = None) -> list[dict[str, Any]]:
    local_now = now or datetime.now(TZ)
    today = local_now.date()
    since_iso = (today - timedelta(days=days_back)).isoformat()
    quest_ds_id = get_data_source_id(QUEST_RUNS_DB_ID)
    quest_index = {quest["page_id"]: quest for quest in get_quest_library(active_only=False)}
    rows = _query_data_source_all(
        quest_ds_id,
        {
            "filter": {"property": "Date", "date": {"on_or_after": since_iso}},
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 100,
        },
    )
    return [_quest_run_row_to_dict(row, quest_index) for row in rows]


def get_today_quest_runs(
    now: datetime | None = None,
    quest_index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()
    resolved_quest_index = quest_index or {
        quest["page_id"]: quest for quest in get_quest_library(active_only=False)
    }
    quest_ds_id = get_data_source_id(QUEST_RUNS_DB_ID)
    rows = _query_data_source_all(
        quest_ds_id,
        {
            "filter": {"property": "Date", "date": {"equals": today_iso}},
            "page_size": 50,
        },
    )
    runs = [_quest_run_row_to_dict(row, resolved_quest_index) for row in rows]
    runs.sort(key=_quest_sort_key)
    return runs


def _quest_selection_context(now: datetime | None = None) -> dict[str, Any] | None:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()
    yesterday_iso = (local_now.date() - timedelta(days=1)).isoformat()

    today_page = get_undercurrent_page(today_iso)
    if not today_page:
        return None

    today_properties = today_page.get("properties") or {}
    morning_energy = _prop_number(today_properties, "Morning Energy")
    morning_state_tags = _prop_multi_select_names(today_properties, "Morning State Tags")
    main_drag = _prop_multi_select_names(today_properties, "Main Drag")

    if morning_energy is None or not morning_state_tags or not main_drag:
        return None

    yesterday_page = get_undercurrent_page(yesterday_iso)
    yesterday_properties = (yesterday_page or {}).get("properties") or {}

    return {
        "today_iso": today_iso,
        "today_date": local_now.date(),
        "daily_page_id": find_or_create_daily_page(today_iso),
        "morning_energy": float(morning_energy),
        "morning_state_tags": morning_state_tags,
        "main_drag": main_drag,
        "carryover": _prop_multi_select_names(yesterday_properties, "Carryover"),
        "tomorrow_need": _prop_multi_select_names(yesterday_properties, "Tomorrow Need"),
        "neglected_domain": _prop_multi_select_names(yesterday_properties, "Neglected Domain"),
    }


def get_echoform_codex() -> list[dict[str, Any]]:
    echoform_ds_id = get_data_source_id(ECHOFORM_CODEX_DB_ID)
    title_prop = get_db_title_prop_name(ECHOFORM_CODEX_DB_ID)
    rows = _query_data_source_all(
        echoform_ds_id,
        {
            "sorts": [{"property": title_prop, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    echoforms: list[dict[str, Any]] = []
    for row in rows:
        properties = row.get("properties") or {}
        name = _prop_title_text(properties, title_prop)
        notion_level = _prop_formula_number(properties, "Level")
        base_bonus = _prop_formula_number(properties, "Base Bonus")
        boost_level = _prop_formula_number(properties, "Boost/Level")
        resonance_day_xp = _prop_rollup_number(properties, "XP") or 0
        legacy_signal_xp = _prop_rollup_number(properties, "Legacy Signal XP") or 0
        notion_total_xp = _prop_formula_number(properties, "Total XP")
        total_xp = notion_total_xp
        if total_xp is None:
            total_xp = round(float(resonance_day_xp) + float(legacy_signal_xp), 2)

        effective_level = notion_level
        if effective_level is None:
            effective_level = 1 + math.sqrt(max(total_xp, 0) / 30) if total_xp > 0 else 1
            effective_level = max(int(math.floor(effective_level)), 1)
        echoforms.append(
            {
                "page_id": row["id"],
                "name": name,
                "condition": _prop_rich_text_text(properties, "Condition"),
                "domain_tags": _prop_multi_select_names(properties, "Domain Tags"),
                "signal_tags": _prop_multi_select_names(properties, "Signal Tags"),
                "drag_match": _prop_multi_select_names(properties, "Drag Match"),
                "carryover_match": _prop_multi_select_names(properties, "Carryover Match"),
                "need_match": _prop_multi_select_names(properties, "Need Match"),
                "formation_themes": _prop_multi_select_names(properties, "Formation Themes"),
                "tier_affinity": _prop_multi_select_names(properties, "Tier Affinity"),
                "activation_phrase": _prop_rich_text_text(properties, "Activation Phrase"),
                "shadow_drift": _prop_rich_text_text(properties, "Shadow Drift"),
                "level": notion_level,
                "level_display": _format_number_display(notion_level),
                "base_bonus": base_bonus,
                "base_bonus_display": _format_number_display(base_bonus),
                "boost_level": boost_level,
                "boost_level_display": _format_number_display(boost_level),
                "effective_level": effective_level,
                "effective_level_display": _format_number_display(effective_level),
                "resonance_day_xp": resonance_day_xp,
                "resonance_day_xp_display": _format_number_display(resonance_day_xp),
                "legacy_signal_xp": legacy_signal_xp,
                "legacy_signal_xp_display": _format_number_display(legacy_signal_xp),
                "xp": total_xp,
                "xp_display": _format_number_display(total_xp),
                "formation_log_count": len(_prop_relation_ids(properties, "⛰️ Formation Log")),
                "image_url": _echoform_image_url(name),
            }
        )

    echoforms.sort(key=lambda echoform: echoform["name"].lower())
    return echoforms


def _score_echoform_candidate(
    echoform: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    carryover_values = context.get("carryover") or context.get("yesterday_carryover") or []
    tomorrow_need_values = context.get("tomorrow_need") or context.get("yesterday_tomorrow_need") or []
    morning_state_tags = context.get("morning_state_tags") or []
    main_drag_values = context.get("main_drag") or []
    neglected_domain_values = context.get("neglected_domain") or context.get("yesterday_neglected_domain") or []

    drag_hits = sorted(set(echoform["drag_match"]) & set(main_drag_values))
    carryover_hits = sorted(set(echoform["carryover_match"]) & set(carryover_values))
    signal_hits = sorted(set(echoform["signal_tags"]) & set(morning_state_tags))
    need_hits = sorted(set(echoform["need_match"]) & set(tomorrow_need_values))
    domain_hits = sorted(set(echoform["domain_tags"]) & set(neglected_domain_values))

    if drag_hits:
        score += len(drag_hits) * 20
        reasons.append(f"Main Drag = {', '.join(drag_hits)}")

    if carryover_hits:
        score += len(carryover_hits) * 20
        reasons.append(f"Carryover = {', '.join(carryover_hits)}")

    if signal_hits:
        score += len(signal_hits) * 15
        reasons.append(f"Morning State = {', '.join(signal_hits)}")

    if need_hits:
        score += len(need_hits) * 15
        reasons.append(f"Tomorrow Need = {', '.join(need_hits)}")

    if domain_hits:
        score += len(domain_hits) * 10
        reasons.append(f"Neglected Domain = {', '.join(domain_hits)}")

    if int(echoform.get("formation_log_count") or 0) > 0:
        score += 10
        reasons.append("Formation lineage already exists")

    level = int(round(float(echoform.get("effective_level") or echoform.get("level") or 1)))
    score += min(max(level, 1), 5) * 3
    if level > 1:
        reasons.append(f"Level {level} availability")

    if not reasons:
        reasons.append("Available today without a stronger competing signal.")

    return {
        "echoform": echoform,
        "score": round(score, 1),
        "why": reasons,
    }


def _echoform_practice_multiplier(echoform: dict[str, Any] | None) -> float:
    if not echoform:
        return 1.0

    base_bonus = echoform.get("base_bonus")
    boost_level = echoform.get("boost_level")
    if base_bonus is None and boost_level is None:
        return 1.0
    return max(float(base_bonus or 0) + float(boost_level or 0), 1.0)


def _echoform_practice_xp(echoform: dict[str, Any] | None) -> float:
    return round(ECHOFORM_PRACTICE_BASE_XP * _echoform_practice_multiplier(echoform), 2)


def _daily_echoform_xp_value(
    properties: dict[str, Any],
    echoform: dict[str, Any] | None = None,
) -> int | float | None:
    value = _prop_numeric_value(properties, "Echoform XP")
    if value is not None:
        return value

    legacy_multiplier = _prop_formula_number(properties, "Echoform XP Multiplier (Legacy)")
    if legacy_multiplier is not None:
        return round(ECHOFORM_PRACTICE_BASE_XP * float(legacy_multiplier), 2)

    if _prop_checkbox(properties, "Echoform Practiced"):
        return _echoform_practice_xp(echoform)
    return None


def build_daily_echoform_context(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()

    try:
        echoforms = get_echoform_codex()
        echoform_index = {echoform["page_id"]: echoform for echoform in echoforms}
        daily_page = get_daily_page(today_iso)
        daily_properties = (daily_page or {}).get("properties") or {}
        selected_ids = _prop_relation_ids(daily_properties, "Echoform")
        selected_id = selected_ids[0] if selected_ids else None
        practiced = _prop_checkbox(daily_properties, "Echoform Practiced")
        daily_echoform_xp = None

        ranked_echoforms: list[dict[str, Any]] = []
        selected_echoform: dict[str, Any] | None = None
        note = None
        state = "empty"

        selection_context = _quest_selection_context(local_now)
        if selection_context is not None and echoforms:
            scored = [
                _score_echoform_candidate(echoform, selection_context)
                for echoform in echoforms
            ]
            scored.sort(
                key=lambda item: (
                    -item["score"],
                    -(item["echoform"].get("formation_log_count") or 0),
                    item["echoform"]["name"].lower(),
                )
            )

            for item in scored:
                ranked_echoform = dict(item["echoform"])
                ranked_echoform["score"] = int(round(item["score"]))
                ranked_echoform["score_display"] = str(int(round(item["score"])))
                ranked_echoform["why"] = item["why"]
                ranked_echoform["why_preview"] = item["why"][:3]
                ranked_echoforms.append(ranked_echoform)

        if selected_id:
            selected_echoform = dict(
                echoform_index.get(selected_id)
                or {
                    "page_id": selected_id,
                    "name": "Selected Echoform",
                    "condition": "",
                    "domain_tags": [],
                    "signal_tags": [],
                    "drag_match": [],
                    "carryover_match": [],
                    "need_match": [],
                    "formation_themes": [],
                    "tier_affinity": [],
                    "activation_phrase": "",
                    "shadow_drift": "",
                    "level": None,
                    "level_display": None,
                    "base_bonus": None,
                    "base_bonus_display": None,
                    "boost_level": None,
                    "boost_level_display": None,
                    "effective_level": 1,
                    "effective_level_display": "1",
                    "resonance_day_xp": None,
                    "resonance_day_xp_display": None,
                    "legacy_signal_xp": None,
                    "legacy_signal_xp_display": None,
                    "xp": None,
                    "xp_display": None,
                    "formation_log_count": 0,
                    "image_url": None,
                }
            )
            ranked_match = next(
                (echoform for echoform in ranked_echoforms if echoform["page_id"] == selected_id),
                None,
            )
            if ranked_match:
                selected_echoform.update(
                    {
                        "score": ranked_match.get("score"),
                        "score_display": ranked_match.get("score_display"),
                        "why": ranked_match.get("why", []),
                        "why_preview": ranked_match.get("why_preview", []),
                    }
                )
            else:
                selected_echoform["why"] = []
                selected_echoform["why_preview"] = []

            daily_echoform_xp = _daily_echoform_xp_value(daily_properties, selected_echoform)
            selected_echoform["daily_xp"] = daily_echoform_xp
            selected_echoform["daily_xp_display"] = _format_number_display(daily_echoform_xp)
            state = "practiced" if practiced else "selected"
        elif ranked_echoforms:
            state = "ready"
        elif selection_context is None:
            state = "morning_incomplete"
            note = "Fill out the Morning Undercurrent log to rank today's Echoforms."
        elif not echoforms:
            note = "No Echoforms available right now."

        alternatives = [
            echoform
            for echoform in ranked_echoforms
            if echoform["page_id"] != selected_id
        ]

        return {
            "selected_echoform": selected_echoform,
            "echoform_practiced": practiced,
            "echoform_ranked": ranked_echoforms,
            "echoform_alternatives": alternatives,
            "echoform_note": note,
            "echoform_error": None,
            "echoform_state": state,
            "echoform_can_reselect": bool(selected_echoform and not practiced and alternatives),
        }
    except Exception:
        return {
            "selected_echoform": None,
            "echoform_practiced": False,
            "echoform_ranked": [],
            "echoform_alternatives": [],
            "echoform_note": None,
            "echoform_error": "Echoforms unavailable.",
            "echoform_state": "error",
            "echoform_can_reselect": False,
        }


def select_daily_echoform(
    echoform_page_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()
    echoform_id = echoform_page_id.strip()
    echoforms = get_echoform_codex()
    echoform_index = {echoform["page_id"]: echoform for echoform in echoforms}
    echoform = echoform_index.get(echoform_id)
    if not echoform:
        raise HTTPException(status_code=404, detail="Echoform not found.")

    daily_page_id = find_or_create_daily_page(today_iso)
    daily_page = notion_get(f"/pages/{daily_page_id}")
    daily_properties = daily_page.get("properties") or {}
    current_ids = _prop_relation_ids(daily_properties, "Echoform")
    current_id = current_ids[0] if current_ids else None
    practiced = _prop_checkbox(daily_properties, "Echoform Practiced")

    if current_id != echoform_id:
        if practiced:
            raise HTTPException(
                status_code=409,
                detail="Today's Echoform is already practiced in Resonance Index. Clear it there before changing it.",
            )
        if _quest_selection_context(local_now) is None:
            raise HTTPException(
                status_code=400,
                detail="Fill out the Morning Undercurrent log before selecting today's Echoform.",
            )

    properties = {"Echoform": {"relation": [{"id": echoform_id}]}}
    if current_id != echoform_id:
        properties["Echoform Practiced"] = {"checkbox": False}
        properties["Echoform XP"] = {"number": None}

    notion_patch(f"/pages/{daily_page_id}", {"properties": properties})
    return {
        "ok": True,
        "daily_page_id": daily_page_id,
        "echoform_id": echoform_id,
        "echoform_name": echoform["name"],
        "changed": current_id != echoform_id,
    }


def log_daily_echoform_practice(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()
    daily_page = get_daily_page(today_iso)
    if not daily_page:
        raise HTTPException(status_code=400, detail="Choose today's Echoform before logging it.")

    daily_properties = daily_page.get("properties") or {}
    selected_ids = _prop_relation_ids(daily_properties, "Echoform")
    if not selected_ids:
        raise HTTPException(status_code=400, detail="Choose today's Echoform before logging it.")

    echoforms = get_echoform_codex()
    echoform_index = {echoform["page_id"]: echoform for echoform in echoforms}
    selected_echoform = echoform_index.get(selected_ids[0])
    practiced = _prop_checkbox(daily_properties, "Echoform Practiced")
    echoform_xp = _daily_echoform_xp_value(daily_properties, selected_echoform)

    if practiced:
        return {
            "ok": True,
            "already_logged": True,
            "echoform_name": (selected_echoform or {}).get("name") or "Today's Echoform",
            "echoform_xp": echoform_xp,
            "echoform_xp_display": _format_number_display(echoform_xp),
            "echoform_total_xp": (selected_echoform or {}).get("xp"),
            "echoform_total_xp_display": (selected_echoform or {}).get("xp_display"),
            "echoform_level_display": (selected_echoform or {}).get("effective_level_display")
            or (selected_echoform or {}).get("level_display"),
        }

    echoform_xp = _echoform_practice_xp(selected_echoform)
    updated_page = notion_patch(
        f"/pages/{daily_page['id']}",
        {
            "properties": {
                "Echoform Practiced": {"checkbox": True},
                "Echoform XP": {"number": echoform_xp},
            }
        },
    )
    updated_properties = updated_page.get("properties") or {}
    echoform_xp = _daily_echoform_xp_value(updated_properties, selected_echoform)
    refreshed_echoform = {echoform["page_id"]: echoform for echoform in get_echoform_codex()}.get(selected_ids[0])
    return {
        "ok": True,
        "already_logged": False,
        "echoform_name": (selected_echoform or {}).get("name") or "Today's Echoform",
        "echoform_xp": echoform_xp,
        "echoform_xp_display": _format_number_display(echoform_xp),
        "echoform_total_xp": (refreshed_echoform or {}).get("xp"),
        "echoform_total_xp_display": (refreshed_echoform or {}).get("xp_display"),
        "echoform_level_display": (refreshed_echoform or {}).get("effective_level_display")
        or (refreshed_echoform or {}).get("level_display"),
    }


def _score_quest_candidate(
    quest: dict[str, Any],
    context: dict[str, Any],
    history_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    score = float(quest.get("weight") or 50)
    reasons: list[str] = []
    carryover_values = context.get("carryover") or context.get("yesterday_carryover") or []
    tomorrow_need_values = context.get("tomorrow_need") or context.get("yesterday_tomorrow_need") or []
    morning_state_tags = context.get("morning_state_tags") or []
    main_drag_values = context.get("main_drag") or []
    neglected_domain_values = context.get("neglected_domain") or context.get("yesterday_neglected_domain") or []
    morning_energy = float(context.get("morning_energy") or 0)
    today_date = context.get("today_date") or _parse_iso_date(context.get("today_iso")) or datetime.now(TZ).date()

    carryover_hits = sorted(set(quest["carryover_match"]) & set(carryover_values))
    need_hits = sorted(set(quest["need_match"]) & set(tomorrow_need_values))
    signal_hits = sorted(set(quest["signal_tags"]) & set(morning_state_tags))
    drag_hits = sorted(set(quest["drag_match"]) & set(main_drag_values))
    domain_hit = quest.get("domain") in set(neglected_domain_values)

    if domain_hit:
        score += 25
        reasons.append(f"Neglected Domain = {quest['domain']}")

    if carryover_hits:
        score += 35
        reasons.append(f"Carryover = {', '.join(carryover_hits)}")

    if need_hits:
        score += 25
        reasons.append(f"Tomorrow Need = {', '.join(need_hits)}")

    if signal_hits:
        score += 25
        reasons.append(f"Morning State = {', '.join(signal_hits)}")

    if drag_hits:
        score += 30
        reasons.append(f"Main Drag = {', '.join(drag_hits)}")

    if morning_energy <= 3 and quest.get("energy_required") == "High":
        score -= 60
        reasons.append("High-energy ask on a low-energy morning")
    elif morning_energy <= 4 and quest.get("energy_required") == "Medium":
        score -= 15
        reasons.append("Medium-energy ask on a soft morning")

    history = history_index.get(quest["page_id"], [])
    latest_run_date = max((run["date_obj"] for run in history if run.get("date_obj")), default=None)
    cooldown_days = int(quest.get("cooldown_days") or 0)
    if latest_run_date is not None and cooldown_days > 0:
        if (today_date - latest_run_date).days <= cooldown_days:
            return {
                "quest": quest,
                "score": score,
                "reasons": reasons,
                "excluded": True,
                "excluded_reason": f"Cooldown active ({cooldown_days}d)",
            }

    if latest_run_date is not None and (today_date - latest_run_date).days <= 3:
        score -= 20
        reasons.append("Recently offered")

    return {
        "quest": quest,
        "score": round(score, 1),
        "reasons": reasons,
        "excluded": False,
        "excluded_reason": None,
    }


def _quest_is_low_friction(quest: dict[str, Any]) -> bool:
    return (
        quest.get("energy_required") == "Low"
        and quest.get("difficulty") == "Light"
        and (quest.get("time_cap_minutes") or 999) <= 10
    )


def _build_quest_offer(
    slot: str,
    candidate: dict[str, Any],
    context: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    quest = candidate["quest"]
    reasons = list(candidate["reasons"])

    if slot == "Best Fit":
        reasons.insert(0, "Strongest overall morning fit")
    elif slot == "Low-Friction":
        reasons.insert(
            0,
            f"Low-friction fit: {quest.get('energy_required') or 'Unknown'} energy, {quest.get('time_cap') or 'open time'}, {quest.get('difficulty') or 'open difficulty'}",
        )
    elif slot == "Wild Card":
        reasons.insert(0, "Wild card from the fresh low/medium-energy pool")

    why_offered = "; ".join(reason for reason in reasons if reason).strip()
    if not why_offered:
        why_offered = "Relevant today, with no stronger contextual signal than its base fit."

    return {
        "quest_page_id": quest["page_id"],
        "quest_name": quest["name"],
        "offer_slot": slot,
        "offer_score": int(round(candidate["score"])),
        "why_offered": why_offered[:1900],
        "source": source,
        "formation_candidate": bool(quest.get("formation_relevant")),
        "date": context["today_iso"],
        "daily_page_id": context.get("daily_page_id"),
    }


def _select_quest_offers(
    context: dict[str, Any],
    quests: list[dict[str, Any]],
    recent_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    neglected_domain_values = context.get("neglected_domain") or context.get("yesterday_neglected_domain") or []
    history_index: dict[str, list[dict[str, Any]]] = {}
    for run in recent_runs:
        quest_id = run.get("quest_page_id")
        if quest_id:
            history_index.setdefault(quest_id, []).append(run)

    scored = [
        _score_quest_candidate(quest, context, history_index)
        for quest in quests
    ]
    eligible = [item for item in scored if not item["excluded"]]
    eligible.sort(key=lambda item: (-item["score"], -(item["quest"].get("weight") or 50), item["quest"]["name"].lower()))
    if not eligible:
        return []

    offers: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    best_fit = eligible[0]
    offers.append(_build_quest_offer("Best Fit", best_fit, context, "Morning"))
    selected_ids.add(best_fit["quest"]["page_id"])

    low_friction_pool = [
        item for item in eligible
        if item["quest"]["page_id"] not in selected_ids and _quest_is_low_friction(item["quest"])
    ]
    if not low_friction_pool:
        low_friction_pool = [
            item
            for item in eligible
            if item["quest"]["page_id"] not in selected_ids
            and item["quest"].get("energy_required") == "Low"
            and (item["quest"].get("time_cap_minutes") or 999) <= 10
        ]
    if not low_friction_pool:
        low_friction_pool = [item for item in eligible if item["quest"]["page_id"] not in selected_ids]
    if low_friction_pool:
        low_friction = low_friction_pool[0]
        offers.append(_build_quest_offer("Low-Friction", low_friction, context, "Morning"))
        selected_ids.add(low_friction["quest"]["page_id"])

    wild_pool = [
        item
        for item in eligible
        if item["quest"]["page_id"] not in selected_ids
        and item["quest"].get("energy_required") in {"Low", "Medium"}
    ]
    if not wild_pool:
        wild_pool = [item for item in eligible if item["quest"]["page_id"] not in selected_ids]

    neglected_domain_pool = [
        item
        for item in wild_pool
        if item["quest"].get("domain") in set(neglected_domain_values)
    ]
    if neglected_domain_pool:
        wild_pool = neglected_domain_pool

    if wild_pool:
        top_wild_pool = wild_pool[: min(5, len(wild_pool))]
        rng = random.Random(f"{context['today_iso']}|wild-card|{len(top_wild_pool)}")
        wild_card = rng.choice(top_wild_pool)
        offers.append(_build_quest_offer("Wild Card", wild_card, context, "Random Fallback"))

    offers.sort(key=_quest_sort_key)
    return offers


def _create_quest_run(offer: dict[str, Any]) -> dict[str, Any]:
    quest_runs_ds_id = get_data_source_id(QUEST_RUNS_DB_ID)
    title_prop = get_db_title_prop_name(QUEST_RUNS_DB_ID)
    properties = {
        title_prop: _notion_title_value(f"{offer['offer_slot']} - {offer['quest_name']}"),
        "Date": {"date": {"start": offer["date"]}},
        "Source": {"select": {"name": offer["source"]}},
        "Why Offered": _notion_rich_text_value(offer["why_offered"]),
        "Status": {"select": {"name": "Offered"}},
        "Offer Slot": {"select": {"name": offer["offer_slot"]}},
        "Offer Score": {"number": offer["offer_score"]},
        "Selector Version": _notion_rich_text_value(QUEST_SELECTOR_VERSION),
        "Formation Candidate": {"checkbox": bool(offer["formation_candidate"])},
    }
    if offer.get("quest_page_id"):
        properties["Quest"] = {"relation": [{"id": offer["quest_page_id"]}]}
    if offer.get("daily_page_id"):
        properties["Resonance Day"] = {"relation": [{"id": offer["daily_page_id"]}]}

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": quest_runs_ds_id},
        "properties": properties,
    }
    return notion_post("/pages", payload)


def _replace_today_offered_quest_runs(today_iso: str) -> int:
    quest_runs_ds_id = get_data_source_id(QUEST_RUNS_DB_ID)
    rows = _query_data_source_all(
        quest_runs_ds_id,
        {
            "filter": {
                "and": [
                    {"property": "Date", "date": {"equals": today_iso}},
                    {"property": "Status", "select": {"equals": "Offered"}},
                ]
            },
            "page_size": 50,
        },
    )
    for row in rows:
        notion_patch(f"/pages/{row['id']}", {"properties": {"Status": {"select": {"name": "Replaced"}}}})
    return len(rows)


def generate_morning_quest_offers(
    now: datetime | None = None,
    *,
    replace_only_offered: bool = False,
) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_iso = local_now.date().isoformat()
    quests = get_active_quest_library()
    quest_index = {quest["page_id"]: quest for quest in quests}
    today_runs = get_today_quest_runs(local_now, quest_index)

    if today_runs:
        blocking_statuses = {"Accepted", "Done", "Shrunken", "Skipped"}
        if replace_only_offered and not any(run["status"] in blocking_statuses for run in today_runs):
            replaced_count = _replace_today_offered_quest_runs(today_iso)
        else:
            return {
                "state": "existing",
                "created_count": 0,
                "replaced_count": 0,
                "offers": today_runs,
            }
    else:
        replaced_count = 0

    context = _quest_selection_context(local_now)
    if context is None:
        return {
            "state": "morning_incomplete",
            "created_count": 0,
            "replaced_count": replaced_count,
            "offers": get_today_quest_runs(local_now, quest_index),
        }

    recent_runs = [
        run
        for run in get_recent_quest_runs(45, local_now)
        if run.get("date") != today_iso
    ]
    selected_offers = _select_quest_offers(context, quests, recent_runs)
    if not selected_offers:
        return {
            "state": "no_candidates",
            "created_count": 0,
            "replaced_count": replaced_count,
            "offers": [],
        }

    for offer in selected_offers:
        _create_quest_run(offer)

    return {
        "state": "refreshed" if replaced_count else "created",
        "created_count": len(selected_offers),
        "replaced_count": replaced_count,
        "offers": get_today_quest_runs(local_now, quest_index),
    }


def accept_quest_run(run_page_id: str) -> dict[str, Any]:
    page = notion_get(f"/pages/{run_page_id}")
    properties = page.get("properties") or {}
    offer_slot = _prop_select_name(properties, "Offer Slot")
    title = _quest_clean_name(
        _prop_title_text(properties, get_db_title_prop_name(QUEST_RUNS_DB_ID)),
        offer_slot,
    )
    date_start = _prop_date_start(properties, "Date")
    today_iso = date_start.split("T", 1)[0] if date_start else datetime.now(TZ).date().isoformat()

    notion_patch(f"/pages/{run_page_id}", {"properties": {"Status": {"select": {"name": "Accepted"}}}})

    quest_runs_ds_id = get_data_source_id(QUEST_RUNS_DB_ID)
    rows = _query_data_source_all(
        quest_runs_ds_id,
        {
            "filter": {"property": "Date", "date": {"equals": today_iso}},
            "page_size": 50,
        },
    )

    replaced_count = 0
    for row in rows:
        if row["id"] == run_page_id:
            continue
        row_status = _prop_select_name(row.get("properties") or {}, "Status")
        if row_status not in {"Offered", "Accepted"}:
            continue
        notion_patch(f"/pages/{row['id']}", {"properties": {"Status": {"select": {"name": "Replaced"}}}})
        replaced_count += 1

    return {
        "ok": True,
        "quest_run_id": run_page_id,
        "quest_name": title,
        "replaced_count": replaced_count,
    }


def complete_quest_run(
    run_page_id: str,
    *,
    status: str,
    cost_felt: str | None = None,
) -> dict[str, Any]:
    page = notion_get(f"/pages/{run_page_id}")
    properties = page.get("properties") or {}
    offer_slot = _prop_select_name(properties, "Offer Slot")
    quest_ids = _prop_relation_ids(properties, "Quest")
    quest_index = {quest["page_id"]: quest for quest in get_quest_library(active_only=False)}
    quest = quest_index.get(quest_ids[0]) if quest_ids else None
    resolved_cost_felt = cost_felt or (quest or {}).get("difficulty") or "Normal"
    xp = _quest_xp_for_completion(quest, status=status, cost_felt=resolved_cost_felt)
    title = _quest_clean_name(
        _prop_title_text(properties, get_db_title_prop_name(QUEST_RUNS_DB_ID)),
        offer_slot,
    )

    update_properties: dict[str, Any] = {
        "Status": {"select": {"name": status}},
        "XP": {"number": xp},
    }
    if resolved_cost_felt:
        update_properties["Cost Felt"] = {"select": {"name": resolved_cost_felt}}

    notion_patch(f"/pages/{run_page_id}", {"properties": update_properties})
    return {
        "ok": True,
        "quest_run_id": run_page_id,
        "quest_name": title,
        "status": status,
        "xp": xp,
        "cost_felt": resolved_cost_felt,
    }


def _quest_focus_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    accepted = [run for run in runs if run.get("status") == "Accepted"]
    if accepted:
        return max(accepted, key=lambda run: run.get("last_edited_time") or "")

    completed = [run for run in runs if run.get("status") in QUEST_COMPLETED_STATUSES]
    if completed:
        return max(completed, key=lambda run: run.get("last_edited_time") or "")

    return None


def _quest_xp_for_completion(
    quest: dict[str, Any] | None,
    *,
    status: str,
    cost_felt: str | None,
) -> int:
    if status == "Skipped":
        return 0

    difficulty = (quest or {}).get("difficulty")
    energy_required = (quest or {}).get("energy_required")
    time_cap_minutes = (quest or {}).get("time_cap_minutes")

    base_xp = QUEST_BASE_XP_BY_DIFFICULTY.get(difficulty or "", 18)
    base_xp += QUEST_ENERGY_XP_BONUS.get(energy_required or "", 0)
    base_xp += QUEST_TIME_XP_BONUS.get(int(time_cap_minutes or 0), 0)

    multiplier = QUEST_COST_FELT_MULTIPLIER.get(cost_felt or "", 1.0)
    multiplier *= QUEST_STATUS_XP_MULTIPLIER.get(status, 1.0)
    return int(round(base_xp * multiplier))


def _quest_linger_points(days_since_completion: int) -> int:
    if days_since_completion < 0:
        return 0
    return QUEST_LINGER_POINTS_BY_DAY.get(days_since_completion, 0)


def get_quest_linger_bonus(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today = local_now.date()
    bonuses = {
        "capacity": 0,
        "alignment": 0,
        "headroom": 0,
        "steadiness": 0,
    }
    details: list[dict[str, Any]] = []

    for run in get_recent_quest_runs(days_back=2, now=local_now):
        if run.get("status") not in QUEST_LINGER_STATUSES:
            continue

        target_label = run.get("pneuma_target")
        target_key = QUEST_PNEUMA_TARGET_KEYS.get(target_label or "")
        completed_on = run.get("date_obj")
        if target_key is None or completed_on is None:
            continue

        days_since_completion = (today - completed_on).days
        points = _quest_linger_points(days_since_completion)
        if points <= 0:
            continue

        bonuses[target_key] += points
        details.append(
            {
                "quest_name": run.get("quest_name"),
                "status": run.get("status"),
                "target": target_label,
                "points": points,
                "completed_on": completed_on.isoformat(),
                "days_since_completion": days_since_completion,
            }
        )

    details.sort(
        key=lambda item: (
            item["days_since_completion"],
            (item.get("quest_name") or "").lower(),
        )
    )
    return {
        "date": today.isoformat(),
        "capacity_bonus": bonuses["capacity"],
        "alignment_bonus": bonuses["alignment"],
        "headroom_bonus": bonuses["headroom"],
        "steadiness_bonus": bonuses["steadiness"],
        "details": details,
    }


def build_today_quest_offers_context(now: datetime | None = None, *, auto_generate: bool = False) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    try:
        quests = get_active_quest_library()
        quest_index = {quest["page_id"]: quest for quest in quests}
        all_offers = get_today_quest_runs(local_now, quest_index)
        state = "existing" if all_offers else "empty"

        if auto_generate and not all_offers:
            generated = generate_morning_quest_offers(local_now)
            all_offers = generated["offers"]
            state = generated["state"]

        focus_offer = _quest_focus_run(all_offers)
        offers = [focus_offer] if focus_offer else list(all_offers)
        switch_options: list[dict[str, Any]] = []
        if focus_offer and focus_offer.get("status") in QUEST_COMPLETED_STATUSES:
            switch_options = [
                run
                for run in all_offers
                if run["run_page_id"] != focus_offer["run_page_id"]
                and run.get("status") in QUEST_SWITCHABLE_STATUSES
            ]
            switch_options.sort(key=_quest_sort_key)

        note = None
        if not offers:
            if state == "morning_incomplete":
                note = "Fill out the Morning Undercurrent log to generate today's three quest offers."
            elif state == "no_candidates":
                note = "No active quests passed today's selector."
            else:
                note = "No quest offers yet."
        elif focus_offer and focus_offer.get("status") in QUEST_COMPLETED_STATUSES and not switch_options:
            note = "No remaining quest offers from today's original 3."

        return {
            "offers": offers,
            "all_offers": all_offers,
            "focus_offer": focus_offer,
            "switch_options": switch_options,
            "note": note,
            "error": None,
            "state": state,
        }
    except Exception:
        return {
            "offers": [],
            "all_offers": [],
            "focus_offer": None,
            "switch_options": [],
            "note": None,
            "error": "Quest offers unavailable.",
            "state": "error",
        }


@app.post("/notion/undercurrent/morning")
def notion_undercurrent_morning(body: MorningLogIn):
    return submit_morning_log(body)


@app.post("/notion/undercurrent/midday")
def notion_undercurrent_midday(body: MiddayLogIn):
    return submit_midday_log(body)


@app.post("/notion/undercurrent/evening")
def notion_undercurrent_evening(body: EveningLogIn):
    return submit_evening_log(body)


@app.post("/notion/undercurrent/daily-notes")
def notion_undercurrent_daily_notes(body: DailyNotesIn):
    return submit_daily_notes(body)


@app.post("/notion/rhythmic-rites/abiding")
def notion_rhythmic_rites_abiding(body: AbidingLogIn):
    return submit_abiding_log(body)


@app.get("/notion/undercurrent/{phase}/ui", response_class=HTMLResponse)
def notion_undercurrent_phase_ui(request: Request, phase: str, msg: str | None = None):
    context = {
        "request": request,
        "msg": msg,
        "return_to": f"/notion/undercurrent/{phase}/ui",
    }
    context.update(build_undercurrent_template_context(visible_phase=phase))
    return templates.TemplateResponse("undercurrent_phase.html", context)


@app.post("/notion/undercurrent/morning/ui", response_class=HTMLResponse)
async def notion_undercurrent_morning_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = submit_morning_log(
            MorningLogIn(
                morning_energy=_validate_int("Morning Energy", form.get("morning_energy")),
                morning_clarity=_validate_int("Morning Clarity", form.get("morning_clarity")),
                morning_mood=_validate_int("Morning Mood", form.get("morning_mood")),
                morning_stress=_validate_int("Morning Stress", form.get("morning_stress")),
                morning_spiritual_orientation=_validate_int(
                    "Morning Spiritual Orientation",
                    form.get("morning_spiritual_orientation"),
                ),
                morning_wellness=_validate_int("Morning Wellness", form.get("morning_wellness")),
                sleep_score=_validate_int("Sleep Score", form.get("sleep_score")),
                bedtime=str(form.get("bedtime", "")),
                base_hr=_validate_int("Base HR", form.get("base_hr")),
                morning_state_tags=list(form.getlist("morning_state_tags")),
                main_drag=list(form.getlist("main_drag")),
                daily_intent=str(form.get("daily_intent", "")),
                morning_notes=str(form.get("morning_notes", "")),
            )
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Morning log saved to Undercurrent page {result['undercurrent_page_id']}."
    if result.get("quest_offers_created"):
        msg += f" Generated {result['quest_offers_created']} quest offers."
    elif result.get("quest_offer_state") == "existing":
        msg += " Quest offers are already in place for today."
    elif result.get("quest_offer_state") == "no_candidates":
        msg += " No quest offers matched today's selector."
    return _redirect_to(return_to, msg)


@app.post("/notion/undercurrent/midday/ui", response_class=HTMLResponse)
async def notion_undercurrent_midday_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = submit_midday_log(
            MiddayLogIn(
                midday_energy=_validate_int("Midday Energy", form.get("midday_energy")),
                midday_focus=_validate_int("Midday Focus", form.get("midday_focus")),
                midday_wellness=_validate_int("Midday Wellness", form.get("midday_wellness")),
                midday_drift=str(form.get("midday_drift", "")),
                midday_need=list(form.getlist("midday_need")),
                midday_notes=str(form.get("midday_notes", "")),
            )
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    return _redirect_to(
        return_to,
        f"Midday update saved to Undercurrent page {result['undercurrent_page_id']}."
    )


@app.post("/notion/undercurrent/evening/ui", response_class=HTMLResponse)
async def notion_undercurrent_evening_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = submit_evening_log(
            EveningLogIn(
                day_score=_validate_int("Day Score", form.get("day_score")),
                evening_wellness=_validate_int("Evening Wellness", form.get("evening_wellness")),
                evening_spiritual_orientation=_validate_int(
                    "Evening Spiritual Orientation",
                    form.get("evening_spiritual_orientation"),
                ),
                alignment=str(form.get("alignment", "")),
                state_shift=str(form.get("state_shift", "")),
                state_shift_intensity=str(form.get("state_shift_intensity", "")),
                regulation_response=str(form.get("regulation_response", "")),
                primary_disruptor=list(form.getlist("primary_disruptor")),
                carryover=list(form.getlist("carryover")),
                most_draining=str(form.get("most_draining", "")),
                neglected_domain=list(form.getlist("neglected_domain")),
                most_restorative=str(form.get("most_restorative", "")),
                reflection_note=str(form.get("reflection_note", "")),
                gratitude_note=str(form.get("gratitude_note", "")),
                lesson=str(form.get("lesson", "")),
                tomorrow_need=list(form.getlist("tomorrow_need")),
            )
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    return _redirect_to(
        return_to,
        f"Evening update saved to Undercurrent page {result['undercurrent_page_id']}."
    )


@app.post("/notion/undercurrent/daily-notes/ui", response_class=HTMLResponse)
async def notion_undercurrent_daily_notes_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = submit_daily_notes(DailyNotesIn(note=str(form.get("note", ""))))
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Daily note saved to Undercurrent page {result['undercurrent_page_id']}."
    if result.get("appended"):
        msg += " Appended to existing Daily Notes."
    return _redirect_to(return_to, msg)


@app.post("/notion/rhythmic-rites/abiding/ui", response_class=HTMLResponse)
async def notion_rhythmic_rites_abiding_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = submit_abiding_log(
            AbidingLogIn(reflection_note=str(form.get("reflection_note", "")))
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Abiding note saved to Undercurrent page {result['undercurrent_page_id']}."
    if result.get("signal_error"):
        msg += f" Signal Field log failed: {result['signal_error']}"
    elif result.get("signal_skipped"):
        msg += " Abiding was already logged in The Signal Field today."
    else:
        msg += " Abiding logged in The Signal Field."
    return _redirect_to(return_to, msg)


@app.post("/notion/quests/accept/ui", response_class=HTMLResponse)
async def notion_quests_accept_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    quest_run_id = str(form.get("quest_run_id", "")).strip()
    if not quest_run_id:
        return _redirect_to(return_to, "Quest offer not specified.")

    try:
        result = accept_quest_run(quest_run_id)
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Accepted quest '{result['quest_name']}'."
    if result.get("replaced_count"):
        msg += f" Replaced {result['replaced_count']} other offered quest(s)."
    return _redirect_to(return_to, msg)


@app.post("/notion/quests/complete/ui", response_class=HTMLResponse)
async def notion_quests_complete_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    quest_run_id = str(form.get("quest_run_id", "")).strip()
    if not quest_run_id:
        return _redirect_to(return_to, "Quest run not specified.")

    try:
        status = _validate_choice(
            "Quest Status",
            str(form.get("status", "")),
            QUEST_COMPLETION_STATUS_OPTIONS,
        )
        cost_felt = _validate_optional_choice(
            "Cost Felt",
            str(form.get("cost_felt", "")),
            QUEST_COST_FELT_OPTIONS,
        )
        result = complete_quest_run(
            quest_run_id,
            status=status,
            cost_felt=cost_felt,
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    return _redirect_to(
        return_to,
        f"Logged quest '{result['quest_name']}' as {result['status']} for {result['xp']} XP."
    )


@app.post("/notion/echoforms/select/ui", response_class=HTMLResponse)
async def notion_echoforms_select_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    echoform_id = str(form.get("echoform_id", "")).strip()
    if not echoform_id:
        return _redirect_to(return_to, "Echoform not specified.")

    try:
        result = select_daily_echoform(echoform_id)
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Selected Echoform '{result['echoform_name']}'."
    if not result.get("changed"):
        msg += " It was already today's selection."
    return _redirect_to(return_to, msg)


@app.post("/notion/echoforms/practice/ui", response_class=HTMLResponse)
async def notion_echoforms_practice_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))

    try:
        result = log_daily_echoform_practice()
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    if result.get("already_logged"):
        msg = f"Echoform '{result['echoform_name']}' was already logged in Resonance Index."
    else:
        msg = f"Logged Echoform '{result['echoform_name']}' in Resonance Index."

    if result.get("echoform_xp_display"):
        msg += f" Today's Echoform XP is {result['echoform_xp_display']}."
    if result.get("echoform_total_xp_display"):
        msg += f" Lifetime Echoform XP is {result['echoform_total_xp_display']}."
    if result.get("echoform_level_display"):
        msg += f" Level {result['echoform_level_display']}."
    return _redirect_to(return_to, msg)

# --- Signal Field constants ---
SIGNAL_DB_ID = "DEMO_DB_SIGNAL_FIELD"  # The Signal Field

SIGNAL_TITLE_PROP   = "Signal"            # title
SIGNAL_ARC_PROP     = "Arc Node"        # relation -> Arc Nodes
SIGNAL_MODE_PROP    = "Mode"            # select
SIGNAL_PRESENCE_PROP= "Presence"         # number
SIGNAL_RES_PROP     = "Resonance Index"  # relation -> daily page
SIGNAL_RITE_PROP    = "Rite"            # relation -> Rhythmic Rites page
SIGNAL_BOOK_PROP    = "Book"            # relation -> Library page
SIGNAL_DATE_PROP = "Date"   # date property in Signal Field (time logged)
DAILIES_ARC_NODE_PAGE_ID = "DEMO_ARC_NODE_DAILIES"
ABIDING_SIGNAL_ARC_NODE_PAGE_ID = "DEMO_ARC_NODE_PRACTICES"
TASKS_ARC_NODE_PAGE_ID = "DEMO_ARC_NODE_PRACTICES"
ABIDING_SIGNAL_MODE = "Creation"
ABIDING_SIGNAL_ICON = "🌄"

RITES = {
    "Breath Anchor": {
        "rite_page_id": "DEMO_RITE_BREATH_ANCHOR",
        "mode": "Embodiment",
    },
    "One Sentence Truth": {
        "rite_page_id": "DEMO_RITE_ONE_SENTENCE_TRUTH",
        "mode": "Review",
        "needs_note": True,
    },
    "Pattern Interrupt": {
        "rite_page_id": "DEMO_RITE_PATTERN_INTERRUPT",
        "mode": "Embodiment",
    },
    "Spiritual Pause": {
        "rite_page_id": "DEMO_RITE_SPIRITUAL_PAUSE",
        "mode": "Embodiment",
    },
}

def signal_logged_today(task_name: str, daily_page_id: str) -> bool:
    """
    True if Signal Field already has an entry for (task_name) linked to today's daily page.
    """
    ds_id = get_data_source_id(SIGNAL_DB_ID)
    q = {
        "filter": {
            "and": [
                {"property": SIGNAL_TITLE_PROP, "title": {"equals": task_name}},
                {"property": SIGNAL_RES_PROP, "relation": {"contains": daily_page_id}},
            ]
        },
        "page_size": 1,
    }
    res = notion_post(f"/data_sources/{ds_id}/query", q)
    return bool(res.get("results"))


def signal_rite_logged_today(rite_page_id: str, daily_page_id: str) -> bool:
    ds_id = get_data_source_id(SIGNAL_DB_ID)
    q = {
        "filter": {
            "and": [
                {"property": SIGNAL_RITE_PROP, "relation": {"contains": rite_page_id}},
                {"property": SIGNAL_RES_PROP, "relation": {"contains": daily_page_id}},
            ]
        },
        "page_size": 1,
    }
    res = notion_post(f"/data_sources/{ds_id}/query", q)
    return bool(res.get("results"))


@lru_cache(maxsize=32)
def get_rite_page_id(task_name: str) -> str | None:
    rites_ds_id = get_data_source_id(RHYTHMIC_RITES_DB_ID)
    res = notion_post(
        f"/data_sources/{rites_ds_id}/query",
        {
            "filter": {"property": "Task Name", "title": {"equals": task_name}},
            "page_size": 1,
        },
    )
    results = res.get("results", [])
    if not results:
        return None
    return results[0].get("id")


def _parse_notion_datetime(value: str | None, fallback_tz: ZoneInfo = TZ) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=fallback_tz)
    return dt.astimezone(fallback_tz)


def _signal_date_range(properties: dict) -> tuple[datetime | None, datetime | None]:
    date_value = (properties.get(SIGNAL_DATE_PROP) or {}).get("date") or {}
    start = _parse_notion_datetime(date_value.get("start"))
    end = _parse_notion_datetime(date_value.get("end"))
    return start, end


def get_alignment_support_data(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    seven_day_start = today_start - timedelta(days=6)

    signal_ds_id = get_data_source_id(SIGNAL_DB_ID)

    abiding_days_last_7: int | None = None
    abiding_rite_page_id = get_rite_page_id("Abiding")
    if abiding_rite_page_id:
        rows = _query_data_source_all(
            signal_ds_id,
            {
                "filter": {
                    "and": [
                        {"property": SIGNAL_RITE_PROP, "relation": {"contains": abiding_rite_page_id}},
                        {"property": SIGNAL_DATE_PROP, "date": {"on_or_after": seven_day_start.isoformat()}},
                    ]
                },
                "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "descending"}],
                "page_size": 100,
            },
        )
        days_seen: set[str] = set()
        for row in rows:
            start, _ = _signal_date_range(row.get("properties") or {})
            if start is None:
                continue
            local_date = start.astimezone(TZ).date()
            if seven_day_start.date() <= local_date <= today_start.date():
                days_seen.add(local_date.isoformat())
        abiding_days_last_7 = len(days_seen)

    presence_rows = _query_data_source_all(
        signal_ds_id,
        {
            "filter": {
                "and": [
                    {"property": SIGNAL_DATE_PROP, "date": {"on_or_after": (today_start - timedelta(days=1)).isoformat()}},
                    {"property": SIGNAL_DATE_PROP, "date": {"before": tomorrow_start.isoformat()}},
                ]
            },
            "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    total_presence_hours = 0.0
    weighted_presence_total = 0.0
    entries_with_presence = 0
    for row in presence_rows:
        properties = row.get("properties") or {}
        presence = _prop_number(properties, SIGNAL_PRESENCE_PROP)
        start, end = _signal_date_range(properties)
        if presence is None or start is None:
            continue

        # Single-point signal entries still count; use a 1h default weight when no end is logged.
        effective_end = end if end and end > start else (start + timedelta(hours=1))
        overlap_start = max(start, today_start)
        overlap_end = min(effective_end, tomorrow_start)
        duration_hours = _duration_minutes(overlap_start, overlap_end) / 60.0
        if duration_hours <= 0:
            continue

        weighted_presence_total += float(presence) * duration_hours
        total_presence_hours += duration_hours
        entries_with_presence += 1

    signal_weighted_presence_today = None
    if total_presence_hours > 0:
        signal_weighted_presence_today = round(weighted_presence_total / total_presence_hours, 2)

    return {
        "date": today_start.date().isoformat(),
        "generated_at": local_now.isoformat(),
        "abiding_last_7_days": abiding_days_last_7,
        "abiding_last_7_days_score": (
            round(_abiding_last_7_days_numeric_score(float(abiding_days_last_7)), 1)
            if abiding_days_last_7 is not None
            else None
        ),
        "signal_weighted_presence_today": signal_weighted_presence_today,
        "signal_presence_hours_today": round(total_presence_hours, 2) if total_presence_hours > 0 else None,
        "signal_entries_today": entries_with_presence,
    }


def _state_shift_intensity_load_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 2:
        return 18.0
    if value <= 4:
        return 38.0
    if value <= 6:
        return 60.0
    if value <= 8:
        return 80.0
    return 92.0


def get_regulation_support_data(now: datetime | None = None) -> dict[str, Any]:
    local_now = now or datetime.now(TZ)
    today_start = local_now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    state_shift_ds_id = get_data_source_id(STATE_SHIFTS_DB_ID)
    rows = _query_data_source_all(
        state_shift_ds_id,
        {
            "filter": {
                "and": [
                    {
                        "property": STATE_SHIFT_TIMESTAMP_PROP,
                        "date": {"on_or_after": today_start.isoformat()},
                    },
                    {
                        "property": STATE_SHIFT_TIMESTAMP_PROP,
                        "date": {"before": tomorrow_start.isoformat()},
                    },
                ]
            },
            "sorts": [{"property": STATE_SHIFT_TIMESTAMP_PROP, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    intensity_values: list[float] = []
    response_scores: list[float] = []
    effect_scores: list[float] = []
    intent_scores: list[float] = []
    formation_scores: list[float] = []
    body_cue_total = 0
    need_total = 0

    for row in rows:
        properties = row.get("properties") or {}

        intensity = _prop_number(properties, "Intensity")
        if intensity is not None:
            intensity_values.append(float(intensity))

        response = _prop_select_name(properties, "Response Chosen")
        if response in STATE_SHIFT_RESPONSE_SCORES:
            response_scores.append(STATE_SHIFT_RESPONSE_SCORES[response])

        effect = _prop_select_name(properties, "Effect")
        if effect in STATE_SHIFT_EFFECT_SCORES:
            effect_scores.append(STATE_SHIFT_EFFECT_SCORES[effect])

        intent_tested = _prop_select_name(properties, "Intent Tested")
        if intent_tested in STATE_SHIFT_INTENT_TESTED_SCORES:
            intent_scores.append(STATE_SHIFT_INTENT_TESTED_SCORES[intent_tested])

        formation = _prop_select_name(properties, "Formation Candidate")
        if formation in STATE_SHIFT_FORMATION_SCORES:
            formation_scores.append(STATE_SHIFT_FORMATION_SCORES[formation])

        body_cue_total += _prop_multi_select_count(properties, "Body Cue")
        need_total += _prop_multi_select_count(properties, "Need")

    state_shift_count = len(rows)
    avg_intensity = round(sum(intensity_values) / len(intensity_values), 2) if intensity_values else None

    def _avg(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    return {
        "date": today_start.date().isoformat(),
        "generated_at": local_now.isoformat(),
        "state_shift_count_today": state_shift_count,
        "state_shift_avg_intensity_today": avg_intensity,
        "state_shift_intensity_load_score": (
            round(_state_shift_intensity_load_score(avg_intensity), 1)
            if avg_intensity is not None
            else None
        ),
        "state_shift_response_score_today": _avg(response_scores),
        "state_shift_effect_score_today": _avg(effect_scores),
        "state_shift_intent_test_score_today": _avg(intent_scores),
        "state_shift_formation_score_today": _avg(formation_scores),
        "state_shift_body_cue_count_today": body_cue_total if state_shift_count else 0,
        "state_shift_need_count_today": need_total if state_shift_count else 0,
    }


def get_latest_signal_entry(task_name: str, rite_page_id: str | None = None) -> dict | None:
    ds_id = get_data_source_id(SIGNAL_DB_ID)
    base_query = {
        "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "descending"}],
        "page_size": 1,
    }

    if rite_page_id:
        res = notion_post(
            f"/data_sources/{ds_id}/query",
            {
                **base_query,
                "filter": {"property": SIGNAL_RITE_PROP, "relation": {"contains": rite_page_id}},
            },
        )
        results = res.get("results", [])
        if results:
            return results[0]

    res = notion_post(
        f"/data_sources/{ds_id}/query",
        {
            **base_query,
            "filter": {"property": SIGNAL_TITLE_PROP, "title": {"equals": task_name}},
        },
    )
    results = res.get("results", [])
    if results:
        return results[0]
    return None


def create_rite_signal_entry(
    task_name: str,
    rite_page_id: str,
    note: str | None = None,
    when_iso: str | None = None,
) -> dict:
    now = datetime.now(TZ)
    dt = now if not when_iso else datetime.fromisoformat(when_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    today_iso = dt.date().isoformat()
    dt_iso = dt.isoformat()
    daily_page_id = find_or_create_daily_page(today_iso)
    if signal_rite_logged_today(rite_page_id, daily_page_id):
        return {"skipped": True, "reason": "already_logged_today", "daily_page_id": daily_page_id}

    latest_entry = get_latest_signal_entry(task_name, rite_page_id=rite_page_id)
    latest_properties = (latest_entry or {}).get("properties") or {}

    properties = {
        SIGNAL_TITLE_PROP: {"title": [{"text": {"content": task_name}}]},
        SIGNAL_DATE_PROP: {"date": {"start": dt_iso}},
        SIGNAL_PRESENCE_PROP: {"number": _prop_number(latest_properties, SIGNAL_PRESENCE_PROP) or 5},
        SIGNAL_RES_PROP: {"relation": [{"id": daily_page_id}]},
        SIGNAL_RITE_PROP: {"relation": [{"id": rite_page_id}]},
    }

    mode_name = _prop_select_name(latest_properties, SIGNAL_MODE_PROP)
    if mode_name:
        properties[SIGNAL_MODE_PROP] = {"select": {"name": mode_name}}

    arc_ids = _prop_relation_ids(latest_properties, SIGNAL_ARC_PROP)
    if arc_ids:
        properties[SIGNAL_ARC_PROP] = {"relation": [{"id": arc_id} for arc_id in arc_ids]}

    if task_name in RITES and SIGNAL_MODE_PROP not in properties:
        properties[SIGNAL_MODE_PROP] = {"select": {"name": RITES[task_name]["mode"]}}

    if task_name in RITES and SIGNAL_ARC_PROP not in properties:
        properties[SIGNAL_ARC_PROP] = {"relation": [{"id": DAILIES_ARC_NODE_PAGE_ID}]}

    if task_name == "Abiding" and SIGNAL_MODE_PROP not in properties:
        properties[SIGNAL_MODE_PROP] = {"select": {"name": ABIDING_SIGNAL_MODE}}

    if task_name == "Abiding":
        properties[SIGNAL_ARC_PROP] = {"relation": [{"id": ABIDING_SIGNAL_ARC_NODE_PAGE_ID}]}

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": get_data_source_id(SIGNAL_DB_ID)},
        "properties": properties,
    }

    if latest_entry and latest_entry.get("icon"):
        payload["icon"] = latest_entry["icon"]
    elif task_name == "Abiding":
        payload["icon"] = {"type": "emoji", "emoji": ABIDING_SIGNAL_ICON}

    children = []
    if note:
        note = note.strip()
        if note:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": note}}]
                },
            })
    if children:
        payload["children"] = children

    page = notion_post("/pages", payload)
    return {"skipped": False, "page_id": page["id"], "daily_page_id": daily_page_id}

def create_signal_entry(task_name: str, note: str | None = None, when_iso: str | None = None) -> dict:
    """
    when_iso: optional ISO8601 datetime string (e.g. 2026-02-10T08:30:00-06:00).
              If omitted, uses now in TZ.
    """
    if task_name not in RITES:
        raise HTTPException(status_code=400, detail=f"Unknown signal task: {task_name}")

    now = datetime.now(TZ)
    dt = now if not when_iso else datetime.fromisoformat(when_iso)
    # Ensure timezone-aware; if user passes naive, assume TZ
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    today_iso = dt.date().isoformat()
    dt_iso = dt.isoformat()

    daily_page_id = find_or_create_daily_page(today_iso)
    if signal_logged_today(task_name, daily_page_id):
        return {"skipped": True, "reason": "already_logged_today", "daily_page_id": daily_page_id}

    ds_id = get_data_source_id(SIGNAL_DB_ID)
    rite_page_id = RITES[task_name]["rite_page_id"]
    mode_value = RITES[task_name]["mode"]

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": ds_id},
        "properties": {
            SIGNAL_TITLE_PROP: {"title": [{"text": {"content": task_name}}]},
            SIGNAL_DATE_PROP: {"date": {"start": dt_iso}},  # ✅ explicit log time
            SIGNAL_ARC_PROP: {"relation": [{"id": DAILIES_ARC_NODE_PAGE_ID}]},
            SIGNAL_MODE_PROP: {"select": {"name": mode_value}},
            SIGNAL_PRESENCE_PROP: {"number": 5},
            SIGNAL_RES_PROP: {"relation": [{"id": daily_page_id}]},
            SIGNAL_RITE_PROP: {"relation": [{"id": rite_page_id}]},
        },
    }

    children = []
    if note:
        note = note.strip()
        if note:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": note}}]
                },
            })
    if children:
        payload["children"] = children

    page = notion_post("/pages", payload)
    return {"skipped": False, "page_id": page["id"], "daily_page_id": daily_page_id}


def create_book_chapter_signal_entry(
    book_page_id: str,
    chapter: int,
    when_iso: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(TZ)
    dt = now if not when_iso else datetime.fromisoformat(when_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    today_iso = dt.date().isoformat()
    dt_iso = dt.isoformat()
    daily_page_id = find_or_create_daily_page(today_iso)

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": get_data_source_id(SIGNAL_DB_ID)},
        "properties": {
            SIGNAL_TITLE_PROP: {"title": [{"text": {"content": f"Chapter {chapter}"}}]},
            SIGNAL_DATE_PROP: {"date": {"start": dt_iso}},
            SIGNAL_ARC_PROP: {"relation": [{"id": TASKS_ARC_NODE_PAGE_ID}]},
            SIGNAL_MODE_PROP: {"select": {"name": "Learning"}},
            SIGNAL_PRESENCE_PROP: {"number": 5},
            SIGNAL_RES_PROP: {"relation": [{"id": daily_page_id}]},
            SIGNAL_BOOK_PROP: {"relation": [{"id": book_page_id}]},
        },
    }
    page = notion_post("/pages", payload)
    return {"page_id": page["id"], "daily_page_id": daily_page_id}


def _normalize_focus_block_domain(value: str | None) -> str:
    key = (value or "work").strip().lower()
    if key not in FOCUS_BLOCK_DOMAIN_LABELS:
        return "work"
    return key


def _focus_block_week_start(day_value: date) -> date:
    return day_value - timedelta(days=day_value.weekday())


def _parse_focus_block_week_start(value: str | None, now: datetime | None = None) -> date:
    text = (value or "").strip()
    if text:
        try:
            return _focus_block_week_start(datetime.fromisoformat(text).date())
        except ValueError:
            pass
    today = (now or datetime.now(TZ)).date()
    return _focus_block_week_start(today)


def _focus_block_default_mode(
    node_name: str,
    domain: str | None,
    last_mode: str | None = None,
) -> str:
    if last_mode in FOCUS_BLOCK_MODE_OPTIONS:
        return last_mode

    text = (node_name or "").strip().casefold()
    if any(keyword in text for keyword in ("scripture", "sermon", "note", "notes", "chapter", "study", "read")):
        return "Learning"
    if any(keyword in text for keyword in ("family", "date night", "fellowship", "wife", "friend")):
        return "Relationship"
    if any(keyword in text for keyword in ("task", "tasks", "email", "filter", "clean", "admin", "errand")):
        return "Service"
    if any(keyword in text for keyword in ("review", "retro", "audit")):
        return "Review"
    if (domain or "").casefold() == "work":
        return "Problem Solving"
    return "Creation"


def _normalize_hex_color(value: str) -> str | None:
    text = (value or "").strip()
    if not HEX_COLOR_RE.fullmatch(text):
        return None

    if len(text) == 4:
        return "#" + "".join(char * 2 for char in text[1:])
    return text.lower()


def _mix_hex_color(base_hex: str, mix_hex: str, amount: float) -> str:
    base = _normalize_hex_color(base_hex)
    mix = _normalize_hex_color(mix_hex)
    if base is None or mix is None:
        return FOCUS_BLOCK_FALLBACK_TILE["background"]

    amount = max(0.0, min(amount, 1.0))
    channels = []
    for offset in (1, 3, 5):
        base_value = int(base[offset:offset + 2], 16)
        mix_value = int(mix[offset:offset + 2], 16)
        channel = round(base_value + ((mix_value - base_value) * amount))
        channels.append(max(0, min(channel, 255)))
    return "#{:02x}{:02x}{:02x}".format(*channels)


def _hex_color_luminance(hex_color: str) -> float:
    normalized = _normalize_hex_color(hex_color)
    if normalized is None:
        return 0.0

    rgb = [int(normalized[offset:offset + 2], 16) / 255.0 for offset in (1, 3, 5)]
    adjusted = []
    for channel in rgb:
        if channel <= 0.03928:
            adjusted.append(channel / 12.92)
        else:
            adjusted.append(((channel + 0.055) / 1.055) ** 2.4)
    return (0.2126 * adjusted[0]) + (0.7152 * adjusted[1]) + (0.0722 * adjusted[2])


def _focus_block_tile_palette(raw_value: str | None) -> dict[str, str]:
    key = (raw_value or "").strip().casefold()
    if key in FOCUS_BLOCK_TILE_COLOR_MAP:
        return dict(FOCUS_BLOCK_TILE_COLOR_MAP[key])

    hex_color = _normalize_hex_color(raw_value or "")
    if hex_color is None:
        return dict(FOCUS_BLOCK_FALLBACK_TILE)

    return {
        "background": hex_color,
        "background_alt": _mix_hex_color(hex_color, "#000000", 0.18),
        "border": _mix_hex_color(hex_color, "#000000", 0.28),
        "text": "#0f172a" if _hex_color_luminance(hex_color) >= 0.58 else "#f8fafc",
    }


def _focus_block_engine_index() -> dict[str, dict[str, Any]]:
    engine_ds_id = get_data_source_id(ARC_ENGINES_DB_ID)
    rows = _query_data_source_all(
        engine_ds_id,
        {
            "sorts": [
                {"property": "Domain", "direction": "ascending"},
                {"property": "Engine", "direction": "ascending"},
            ],
            "page_size": 100,
        },
    )

    engine_index: dict[str, dict[str, Any]] = {}
    for row in rows:
        properties = row.get("properties") or {}
        name = _prop_title_text(properties, "Engine")
        if not name:
            continue
        engine_index[row["id"]] = {
            "page_id": row["id"],
            "engine": name,
            "domain": _prop_select_name(properties, "Domain"),
            "line": _prop_select_name(properties, "Line"),
            "score": _prop_number(properties, "Score"),
        }
    return engine_index


def _focus_block_signal_defaults() -> dict[str, dict[str, Any]]:
    signal_ds_id = get_data_source_id(SIGNAL_DB_ID)
    response = notion_post(
        f"/data_sources/{signal_ds_id}/query",
        {
            "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "descending"}],
            "page_size": 100,
        },
    )

    defaults: dict[str, dict[str, Any]] = {}
    for row in response.get("results", []):
        properties = row.get("properties") or {}
        arc_node_ids = _prop_relation_ids(properties, SIGNAL_ARC_PROP)
        if not arc_node_ids:
            continue
        arc_node_id = arc_node_ids[0]
        if arc_node_id in defaults:
            continue
        start, end = _signal_date_range(properties)
        defaults[arc_node_id] = {
            "last_signal_title": _prop_title_text(properties, SIGNAL_TITLE_PROP),
            "last_mode": _prop_select_name(properties, SIGNAL_MODE_PROP),
            "last_presence": _prop_number(properties, SIGNAL_PRESENCE_PROP),
            "last_start": start.isoformat() if start else None,
            "last_end": end.isoformat() if end else None,
        }
    return defaults


def _focus_block_arc_node_index() -> dict[str, dict[str, Any]]:
    arc_ds_id = get_data_source_id(ARC_NODES_DB_ID)
    engine_index = _focus_block_engine_index()
    signal_defaults = _focus_block_signal_defaults()
    rows = _query_data_source_all(
        arc_ds_id,
        {
            "sorts": [
                {"property": "Engine", "direction": "ascending"},
                {"property": "Node", "direction": "ascending"},
            ],
            "page_size": 100,
        },
    )

    nodes: dict[str, dict[str, Any]] = {}
    for row in rows:
        properties = row.get("properties") or {}
        name = _prop_title_text(properties, "Node")
        if not name:
            continue

        engine_ids = _prop_relation_ids(properties, "Engine")
        engine = engine_index.get(engine_ids[0]) if engine_ids else None
        signal_default = signal_defaults.get(row["id"], {})
        domain = (engine or {}).get("domain")
        tile_color_name = next(iter(_prop_rollup_texts(properties, "Calendar Tile Color")), None)
        tile_palette = _focus_block_tile_palette(tile_color_name)

        nodes[row["id"]] = {
            "page_id": row["id"],
            "name": name,
            "status": _prop_status_name(properties, "Status"),
            "engine_page_id": engine_ids[0] if engine_ids else None,
            "engine": (engine or {}).get("engine"),
            "domain": domain,
            "line": (engine or {}).get("line"),
            "novely": _prop_number(properties, "Novely"),
            "last_mode": signal_default.get("last_mode"),
            "last_presence": signal_default.get("last_presence"),
            "last_signal_title": signal_default.get("last_signal_title"),
            "tile_color_name": tile_color_name,
            "tile_background": tile_palette["background"],
            "tile_background_alt": tile_palette["background_alt"],
            "tile_border_color": tile_palette["border"],
            "tile_text_color": tile_palette["text"],
            "suggested_mode": _focus_block_default_mode(
                name,
                domain,
                signal_default.get("last_mode"),
            ),
        }
    return nodes


def _focus_block_entry_kind(properties: dict) -> str:
    if _prop_relation_ids(properties, SIGNAL_RITE_PROP):
        return "rite"
    if _prop_relation_ids(properties, SIGNAL_BOOK_PROP):
        return "book"
    if _prop_relation_ids(properties, "Echoforms") or _prop_relation_ids(properties, "Echo Vault"):
        return "echoform"
    return "focus"


def _focus_block_entries_for_week(
    week_start: date,
    arc_node_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    signal_ds_id = get_data_source_id(SIGNAL_DB_ID)
    week_start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=TZ)
    week_end_dt = week_start_dt + timedelta(days=7)
    rows = _query_data_source_all(
        signal_ds_id,
        {
            "filter": {
                "and": [
                    {"property": SIGNAL_DATE_PROP, "date": {"on_or_after": week_start_dt.isoformat()}},
                    {"property": SIGNAL_DATE_PROP, "date": {"before": week_end_dt.isoformat()}},
                ]
            },
            "sorts": [{"property": SIGNAL_DATE_PROP, "direction": "ascending"}],
            "page_size": 100,
        },
    )

    entries: list[dict[str, Any]] = []
    for row in rows:
        properties = row.get("properties") or {}
        arc_node_ids = _prop_relation_ids(properties, SIGNAL_ARC_PROP)
        arc_node_id = arc_node_ids[0] if arc_node_ids else None
        node = arc_node_index.get(arc_node_id) if arc_node_id else None

        start, end = _signal_date_range(properties)
        if start is None:
            continue
        effective_end = end if end and end > start else start + timedelta(minutes=FOCUS_BLOCK_FALLBACK_DURATION_MINUTES)
        entry_kind = _focus_block_entry_kind(properties)
        tile_palette = _focus_block_tile_palette((node or {}).get("tile_color_name"))
        entries.append(
            {
                "page_id": row["id"],
                "signal": _prop_title_text(properties, SIGNAL_TITLE_PROP),
                "mode": _prop_select_name(properties, SIGNAL_MODE_PROP),
                "presence": _prop_number(properties, SIGNAL_PRESENCE_PROP),
                "arc_node_id": arc_node_id,
                "arc_node_name": (node or {}).get("name"),
                "engine": (node or {}).get("engine"),
                "domain": (node or {}).get("domain"),
                "line": (node or {}).get("line"),
                "tile_color_name": (node or {}).get("tile_color_name"),
                "tile_background": (node or {}).get("tile_background") or tile_palette["background"],
                "tile_background_alt": (node or {}).get("tile_background_alt") or tile_palette["background_alt"],
                "tile_border_color": (node or {}).get("tile_border_color") or tile_palette["border"],
                "tile_text_color": (node or {}).get("tile_text_color") or tile_palette["text"],
                "start": start.isoformat(),
                "end": effective_end.isoformat(),
                "has_explicit_end": bool(end and end > start),
                "entry_kind": entry_kind,
                "editable": entry_kind == "focus" and bool(arc_node_id),
            }
        )

    return entries


def build_focus_blocks_context(week_start: date, domain_key: str) -> dict[str, Any]:
    normalized_domain = _normalize_focus_block_domain(domain_key)
    week_start = _focus_block_week_start(week_start)
    today = datetime.now(TZ).date()
    arc_node_index = _focus_block_arc_node_index()
    nodes = list(arc_node_index.values())
    entries = _focus_block_entries_for_week(week_start, arc_node_index)
    days = []
    for offset in range(7):
        day_value = week_start + timedelta(days=offset)
        days.append(
            {
                "iso": day_value.isoformat(),
                "label_short": day_value.strftime("%a %-d"),
                "label_long": day_value.strftime("%A, %B %-d"),
                "is_today": day_value == today,
            }
        )

    selected_day_iso = today.isoformat() if week_start <= today < (week_start + timedelta(days=7)) else week_start.isoformat()

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "domain": normalized_domain,
        "domain_label": FOCUS_BLOCK_DOMAIN_LABELS[normalized_domain],
        "today_iso": today.isoformat(),
        "selected_day_iso": selected_day_iso,
        "days": days,
        "nodes": nodes,
        "entries": entries,
        "mode_options": FOCUS_BLOCK_MODE_OPTIONS,
        "default_duration_minutes": FOCUS_BLOCK_DEFAULT_DURATION_MINUTES,
        "default_presence": FOCUS_BLOCK_DEFAULT_PRESENCE,
        "slot_minutes": FOCUS_BLOCK_SLOT_MINUTES,
        "day_start_hour": FOCUS_BLOCK_DAY_START_HOUR,
        "day_end_hour": FOCUS_BLOCK_DAY_END_HOUR,
    }


def _validate_presence_value(label: str, value: float | int | str) -> float | int:
    number = _validate_non_negative_number(label, value)
    if number < 1 or number > 5:
        raise HTTPException(status_code=400, detail=f"{label} must be between 1 and 5")
    rounded = round(number, 2)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


class BookChapterReflectionIn(BaseModel):
    book_page_id: str | None = Field(default=None, max_length=80)
    new_book_title: str | None = Field(default=None, max_length=200)
    total_chapters: int | None = None
    chapter: int
    reflection_note: str = Field(..., min_length=1)


def submit_book_chapter_reflection(body: BookChapterReflectionIn) -> dict[str, Any]:
    chapter = _validate_positive_int("Chapter", body.chapter)
    reflection_note = _validate_text("Reflection", body.reflection_note)
    selected_book_page_id = (body.book_page_id or "").strip()
    new_book_title = _validate_text("New Book Title", body.new_book_title or "", allow_blank=True)

    books = get_library_books()
    books_by_id = {book["page_id"]: book for book in books}
    books_by_title = {book["title_key"]: book for book in books}

    created_book = False
    current_progress = 0

    if new_book_title:
        if selected_book_page_id:
            raise HTTPException(
                status_code=400,
                detail="Choose either an existing book or add a new one, not both.",
            )
        if _normalize_title_key(new_book_title) in books_by_title:
            raise HTTPException(
                status_code=400,
                detail="That book already exists in Library. Select it from the dropdown instead.",
            )

        total_chapters = _validate_positive_int("Total Chapters", body.total_chapters)
        if chapter > total_chapters:
            raise HTTPException(
                status_code=400,
                detail="Chapter cannot be greater than Total Chapters for a new book.",
            )

        book_page = create_library_book_page(new_book_title, total_chapters)
        book_page_id = book_page["id"]
        book_title = new_book_title
        created_book = True
    else:
        if not selected_book_page_id:
            raise HTTPException(status_code=400, detail="Select a book or add a new one.")

        book = books_by_id.get(selected_book_page_id)
        if not book:
            raise HTTPException(status_code=400, detail="Selected book was not found in Library.")

        total_chapters = book["chapters"]
        if total_chapters is not None and chapter > int(total_chapters):
            raise HTTPException(
                status_code=400,
                detail="Chapter cannot be greater than the total chapters stored in Library.",
            )

        book_page_id = book["page_id"]
        book_title = book["title"]
        current_progress = int(book["chapters_complete"] or 0)

    append_book_chapter_reflection(book_page_id, chapter, reflection_note)

    progress_chapter = max(current_progress, chapter)
    notion_patch(
        f"/pages/{book_page_id}",
        {"properties": {"Chapters Complete": {"number": progress_chapter}}},
    )

    signal_page_id = None
    signal_error = None
    try:
        signal = create_book_chapter_signal_entry(book_page_id, chapter)
        signal_page_id = signal["page_id"]
    except HTTPException as exc:
        signal_error = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

    return {
        "ok": True,
        "book_page_id": book_page_id,
        "book_title": book_title,
        "created_book": created_book,
        "chapter_logged": chapter,
        "progress_chapter": progress_chapter,
        "progress_already_ahead": current_progress > chapter,
        "signal_page_id": signal_page_id,
        "signal_error": signal_error,
    }


class SignalIn(BaseModel):
    task: str = Field(..., min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)
    when_iso: str | None = Field(default=None, max_length=40)  # optional override


class FocusBlockSignalIn(BaseModel):
    page_id: str | None = Field(default=None, max_length=80)
    arc_node_id: str = Field(..., min_length=1, max_length=80)
    signal: str = Field(..., min_length=1, max_length=200)
    mode: str | None = Field(default=None, max_length=40)
    presence: float = Field(...)
    start: str = Field(..., min_length=1, max_length=40)
    end: str | None = Field(default=None, max_length=40)


class StateShiftIn(BaseModel):
    shift: str = Field(..., min_length=1, max_length=120)
    trigger: str
    direction: str
    response_chosen: str
    effect: str = "unknown"
    formation_candidate: str = "no"
    intent_tested: str = "not tested"
    intensity: float
    need: list[str] = Field(default_factory=list)
    body_cue: list[str] = Field(default_factory=list)
    note: str = ""
    timestamp: str | None = None


def save_focus_block_entry(body: FocusBlockSignalIn) -> dict[str, Any]:
    arc_node_id = (body.arc_node_id or "").strip()
    if not arc_node_id:
        raise HTTPException(status_code=400, detail="Arc Node is required")

    signal_name = _validate_text("Signal", body.signal)
    start = _parse_datetime_input("Start", body.start, TZ)
    end = _parse_datetime_input("End", body.end or "", TZ) if (body.end or "").strip() else (
        start + timedelta(minutes=FOCUS_BLOCK_DEFAULT_DURATION_MINUTES)
    )
    if end <= start:
        raise HTTPException(status_code=400, detail="End must be after Start")

    arc_node_index = _focus_block_arc_node_index()
    node = arc_node_index.get(arc_node_id)
    if not node:
        raise HTTPException(status_code=400, detail="Selected Arc Node was not found")

    mode_name = _validate_choice(
        "Mode",
        (body.mode or node.get("suggested_mode") or "").strip(),
        FOCUS_BLOCK_MODE_OPTIONS,
    )
    presence_value = _validate_presence_value("Presence", body.presence)
    date_iso = start.date().isoformat()
    sync_dates = {date_iso}
    daily_page_id = find_or_create_daily_page(date_iso)

    properties = {
        SIGNAL_TITLE_PROP: _notion_title_value(signal_name),
        SIGNAL_DATE_PROP: {"date": {"start": start.isoformat(), "end": end.isoformat()}},
        SIGNAL_ARC_PROP: {"relation": [{"id": arc_node_id}]},
        SIGNAL_MODE_PROP: {"select": {"name": mode_name}},
        SIGNAL_PRESENCE_PROP: {"number": presence_value},
        SIGNAL_RES_PROP: {"relation": [{"id": daily_page_id}]},
    }

    page_id = (body.page_id or "").strip()
    if page_id:
        existing_page = notion_get(f"/pages/{page_id}")
        existing_properties = existing_page.get("properties") or {}
        if _focus_block_entry_kind(existing_properties) != "focus":
            raise HTTPException(
                status_code=400,
                detail="This Signal Field entry is managed by another workflow and can't be edited here.",
            )
        existing_start, _ = _signal_date_range(existing_properties)
        if existing_start is not None:
            sync_dates.add(existing_start.astimezone(UNDERCURRENT_TZ).date().isoformat())
        notion_patch(f"/pages/{page_id}", {"properties": properties})
        daily_load_sync_error = _sync_daily_load_dates(sync_dates)
        return {
            "ok": True,
            "page_id": page_id,
            "daily_page_id": daily_page_id,
            "updated": True,
            "signal": signal_name,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "daily_load_sync_error": daily_load_sync_error,
        }

    page = notion_post(
        "/pages",
        {
            "parent": {"type": "data_source_id", "data_source_id": get_data_source_id(SIGNAL_DB_ID)},
            "properties": properties,
        },
    )
    daily_load_sync_error = _sync_daily_load_dates(sync_dates)
    return {
        "ok": True,
        "page_id": page["id"],
        "daily_page_id": daily_page_id,
        "updated": False,
        "signal": signal_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "daily_load_sync_error": daily_load_sync_error,
    }


def create_state_shift_entry(body: StateShiftIn) -> dict:
    shift_name = _validate_text("Shift", body.shift)
    trigger = _validate_choice("Trigger", body.trigger, STATE_SHIFT_TRIGGER_OPTIONS)
    direction = _validate_choice("Direction", body.direction, STATE_SHIFT_DIRECTION_OPTIONS)
    response_chosen = _validate_choice("Response Chosen", body.response_chosen, STATE_SHIFT_RESPONSE_OPTIONS)
    effect = _validate_choice("Effect", body.effect, STATE_SHIFT_EFFECT_OPTIONS)
    formation_candidate = _validate_choice(
        "Formation Candidate",
        body.formation_candidate,
        STATE_SHIFT_FORMATION_OPTIONS,
    )
    intent_tested = _validate_choice("Intent Tested", body.intent_tested, STATE_SHIFT_INTENT_TESTED_OPTIONS)
    intensity = _validate_non_negative_number("Intensity", body.intensity)
    needs = _validate_optional_multi_choice("Need", body.need, STATE_SHIFT_NEED_OPTIONS)
    body_cues = _validate_optional_multi_choice("Body Cue", body.body_cue, STATE_SHIFT_BODY_CUE_OPTIONS)
    note = _validate_text("Note", body.note, allow_blank=True)
    shift_time = _parse_datetime_input("Timestamp", body.timestamp, TZ)

    date_iso = shift_time.date().isoformat()
    daily_page_id = find_or_create_daily_page(date_iso)
    undercurrent_page_id = find_undercurrent_page(date_iso)

    properties = {
        get_db_title_prop_name(STATE_SHIFTS_DB_ID): _notion_title_value(shift_name),
        "Trigger": {"select": {"name": trigger}},
        "Direction": {"select": {"name": direction}},
        "Response Chosen": {"select": {"name": response_chosen}},
        "Effect": {"select": {"name": effect}},
        "Formation Candidate": {"select": {"name": formation_candidate}},
        "Intent Tested": {"select": {"name": intent_tested}},
        "Intensity": {"number": intensity},
        STATE_SHIFT_TIMESTAMP_PROP: {"date": {"start": shift_time.isoformat()}},
        STATE_SHIFT_RESONANCE_PROP: {"relation": [{"id": daily_page_id}]},
        "Need": {"multi_select": [{"name": value} for value in needs]},
        "Body Cue": {"multi_select": [{"name": value} for value in body_cues]},
    }

    if note:
        properties["Note"] = _notion_rich_text_value(note)

    if undercurrent_page_id:
        properties[STATE_SHIFT_UNDERCURRENT_PROP] = {"relation": [{"id": undercurrent_page_id}]}

    state_shift_ds_id = get_data_source_id(STATE_SHIFTS_DB_ID)
    page = notion_post(
        "/pages",
        {
            "parent": {"type": "data_source_id", "data_source_id": state_shift_ds_id},
            "properties": properties,
        },
    )

    return {
        "ok": True,
        "page_id": page["id"],
        "daily_page_id": daily_page_id,
        "undercurrent_page_id": undercurrent_page_id,
        "timestamp": shift_time.isoformat(),
    }


@app.post("/notion/state-shifts")
def notion_state_shifts(body: StateShiftIn):
    return create_state_shift_entry(body)


@app.post("/notion/state-shifts/ui", response_class=HTMLResponse)
async def notion_state_shifts_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    try:
        result = create_state_shift_entry(
            StateShiftIn(
                shift=str(form.get("shift", "")),
                trigger=str(form.get("trigger", "")),
                direction=str(form.get("direction", "")),
                response_chosen=str(form.get("response_chosen", "")),
                effect=str(form.get("effect", "unknown")),
                formation_candidate=str(form.get("formation_candidate", "no")),
                intent_tested=str(form.get("intent_tested", "not tested")),
                intensity=_validate_non_negative_number("Intensity", form.get("intensity")),
                need=list(form.getlist("need")),
                body_cue=list(form.getlist("body_cue")),
                note=str(form.get("note", "")),
                timestamp=str(form.get("timestamp", "")),
            )
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    return _redirect_to(
        return_to,
        f"State Shift saved to page {result['page_id']}."
    )


@app.post("/notion/library/chapter-reflections")
def notion_library_chapter_reflections(body: BookChapterReflectionIn):
    return submit_book_chapter_reflection(body)


@app.post("/notion/library/chapter-reflections/ui", response_class=HTMLResponse)
async def notion_library_chapter_reflections_ui(request: Request):
    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to", "/")))
    book_selection = str(form.get("book_selection", "")).strip()
    is_new_book = book_selection == "__new__"

    try:
        result = submit_book_chapter_reflection(
            BookChapterReflectionIn(
                book_page_id=None if is_new_book else (book_selection or None),
                new_book_title=str(form.get("new_book_title", "")) if is_new_book else None,
                total_chapters=(
                    _validate_positive_int("Total Chapters", form.get("total_chapters"))
                    if is_new_book
                    else None
                ),
                chapter=_validate_positive_int("Chapter", form.get("chapter")),
                reflection_note=str(form.get("reflection_note", "")),
            )
        )
    except HTTPException as exc:
        return _redirect_to(return_to, str(exc.detail))

    msg = f"Logged Chapter {result['chapter_logged']} for '{result['book_title']}'."
    if result.get("created_book"):
        msg += " Added the book to Library."
    if result.get("progress_already_ahead"):
        msg += f" Library progress stayed at Chapter {result['progress_chapter']}."
    else:
        msg += f" Library progress is now Chapter {result['progress_chapter']}."
    if result.get("signal_error"):
        msg += f" Signal Field log failed: {result['signal_error']}"
    else:
        msg += " Signal Field updated."
    return _redirect_to(return_to, msg)


@app.post("/notion/signal")
def notion_signal(body: SignalIn):
    task = body.task.strip()
    note = (body.note or "").strip() or None
    when_iso = (body.when_iso or "").strip() or None
    return create_signal_entry(task, note, when_iso)

@app.post("/notion/signal/ui", response_class=HTMLResponse)
def notion_signal_ui(
    task: str = Form(...),
    note: str = Form(default=""),
):
    task = (task or "").strip()
    note = (note or "").strip() or None
    if not task:
        return RedirectResponse(url="/?msg=Signal%20task%20was%20blank", status_code=303)

    out = create_signal_entry(task, note)
    if out.get("skipped"):
        msg = f"Signal '{task}' already logged today."
    else:
        msg = f"Logged signal '{task}' → page {out['page_id']} (daily {out['daily_page_id']})"
    return _redirect_home(msg)


@app.post("/notion/rhythmic-rites/complete/ui", response_class=HTMLResponse)
def notion_rhythmic_rites_complete_ui(
    rite_page_id: str = Form(...),
    task_name: str = Form(...),
    return_to: str = Form(default="/"),
):
    safe_return_to = _safe_return_to(return_to)
    task_name = (task_name or "").strip()
    rite_page_id = (rite_page_id or "").strip()

    if not task_name or not rite_page_id:
        return _redirect_to(safe_return_to, "Missing rite task details.")

    if task_name in RHYTHMIC_RITES_MANUAL_TASKS:
        if task_name == "Abiding":
            return _redirect_to(safe_return_to, "Use the Abiding reflection popout to log this rite.")
        return _redirect_to(safe_return_to, f"'{task_name}' is tracked manually.")

    try:
        out = create_rite_signal_entry(task_name=task_name, rite_page_id=rite_page_id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _redirect_to(safe_return_to, detail)

    if out.get("skipped"):
        msg = f"'{task_name}' was already logged today."
    else:
        msg = f"Logged '{task_name}' in The Signal Field."
    return _redirect_to(safe_return_to, msg)


@app.get("/api/focus-blocks/context")
def focus_blocks_context_api(
    week_start: str | None = None,
    domain: str = "work",
):
    normalized_domain = _normalize_focus_block_domain(domain)
    week_start_date = _parse_focus_block_week_start(week_start)
    return build_focus_blocks_context(week_start_date, normalized_domain)


@app.post("/api/focus-blocks/save")
def focus_blocks_save(body: FocusBlockSignalIn):
    return save_focus_block_entry(body)


@app.get("/focus-blocks", response_class=HTMLResponse)
def focus_blocks_page(
    request: Request,
    week_start: str | None = None,
    domain: str = "work",
    msg: str | None = None,
):
    normalized_domain = _normalize_focus_block_domain(domain)
    week_start_date = _parse_focus_block_week_start(week_start)
    payload = build_focus_blocks_context(week_start_date, normalized_domain)
    context = {
        "request": request,
        "msg": msg,
        "focus_blocks_domain": normalized_domain,
        "focus_blocks_week_label": (
            f"{week_start_date.strftime('%b %-d')} - {(week_start_date + timedelta(days=6)).strftime('%b %-d')}"
        ),
        "focus_blocks_payload_json": json.dumps(payload),
    }
    return templates.TemplateResponse("focus_blocks.html", context)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, last_log: str | None = None, msg: str | None = None):
    log_preview = tail_log(last_log) if last_log else None

    # Signal status flags (safe if Notion fails: just show unknown/false)
    signal_done = {}
    try:
        today_iso = datetime.now(TZ).date().isoformat()
        daily_page_id = find_or_create_daily_page(today_iso)
        for name in RITES.keys():
            signal_done[name] = signal_logged_today(name, daily_page_id)
    except Exception:
        # don't break Aurora UI if Notion is down
        signal_done = {name: False for name in RITES.keys()}

    rhythmic_rites = []
    rhythmic_rites_error = None
    try:
        rhythmic_rites = get_active_rhythmic_rites()
    except Exception:
        rhythmic_rites_error = "Rhythmic Rites unavailable."

    quest_offers_context = build_today_quest_offers_context(auto_generate=True)
    echoform_context = build_daily_echoform_context()

    pneuma_scores = get_pneuma_scores()
    index_runtime = get_index_runtime(pneuma_scores)

    context = {
        "request": request,
        "msg": msg,
        "last_log": last_log,
        "log_preview": log_preview,
        "signal_done": signal_done,
        "rhythmic_rites": rhythmic_rites,
        "rhythmic_rites_pending_count": sum(1 for rite in rhythmic_rites if not rite["complete_today"]),
        "rhythmic_rites_error": rhythmic_rites_error,
        "quest_offers": quest_offers_context["offers"],
        "quest_offers_all_count": len(quest_offers_context["all_offers"]),
        "quest_offers_note": quest_offers_context["note"],
        "quest_offers_error": quest_offers_context["error"],
        "quest_focus_offer": quest_offers_context["focus_offer"],
        "quest_offers_state": quest_offers_context["state"],
        "quest_switch_options": quest_offers_context["switch_options"],
        "quest_completion_status_options": QUEST_COMPLETION_STATUS_OPTIONS,
        "quest_cost_felt_options": QUEST_COST_FELT_OPTIONS,
        "selected_echoform": echoform_context["selected_echoform"],
        "echoform_practiced": echoform_context["echoform_practiced"],
        "echoform_ranked": echoform_context["echoform_ranked"],
        "echoform_alternatives": echoform_context["echoform_alternatives"],
        "echoform_note": echoform_context["echoform_note"],
        "echoform_error": echoform_context["echoform_error"],
        "echoform_state": echoform_context["echoform_state"],
        "echoform_can_reselect": echoform_context["echoform_can_reselect"],
        "pneuma_scores": pneuma_scores,
        "index_runtime": index_runtime,
        "return_to": "/",
    }
    context.update(build_undercurrent_template_context())
    context.update(build_book_reflection_template_context())
    context.update(build_state_shift_template_context())
    return templates.TemplateResponse("index.html", context)
