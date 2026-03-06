import json
import re
import sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional

from jezr import db as db_mod
from jezr.workout_render import validate_planned_workout, render_intervals_workout_text
from jezr import plan_archive


def _slugify(text: str) -> str:
    """Lowercase the text and replace non-alphanumeric runs with hyphens."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _external_id(workout: dict) -> str:
    """Build the canonical external_id for a planned workout."""
    sport = (workout.get("sport") or "run").lower()
    date_str = workout.get("date", "")
    name = workout.get("name", "")
    slug = _slugify(name) if name else "workout"
    return f"planned-{sport}-{date_str}-{slug}"


def _week_start_for(workouts: list[dict]) -> str:
    """Return the ISO date of the Monday of the earliest workout date."""
    dates = [date.fromisoformat(w["date"]) for w in workouts if w.get("date")]
    if not dates:
        raise ValueError("No valid dates found in workouts.")
    earliest = min(dates)
    monday = earliest - timedelta(days=earliest.weekday())
    return monday.isoformat()


def _build_event(workout: dict, external_id: str) -> dict:
    """Convert a planned workout dict into an Intervals.icu event payload."""
    description = render_intervals_workout_text(workout)
    return {
        "category": "WORKOUT",
        "start_date_local": f"{workout['date']}T06:00:00",
        "type": workout.get("sport", "Run"),
        "name": workout.get("name", "Workout"),
        "description": description,
        "external_id": external_id,
    }


def upload_plan(
    workouts: list[dict],
    db_path: str,
    intervals_client,
    plans_dir: str,
    adhoc: bool = False,
    debug: bool = False,
) -> dict:
    """Validate, upload, and store a planned workout week.

    Steps:
    1. Validate each workout via workout_render.validate_planned_workout()
    2. Upload Run workouts to Intervals.icu via intervals_client.upsert_events()
    3. Fetch back events for that week via intervals_client.list_events()
    4. Match returned events by external_id to capture intervals_id
    5. Insert all planned workouts into tbl_planned, update intervals_id where found
    6. Archive plan via plan_archive.archive_plan() unless adhoc=True

    Returns:
        {
            "uploaded": int,
            "ids_matched": int,
            "ids_missing": list[str],
            "skipped_non_run": int,
            "archived_to": str | None,
        }
    """
    if not workouts:
        raise ValueError("No workouts provided.")

    # 1. Validate all before touching any external systems.
    for i, workout in enumerate(workouts):
        try:
            validate_planned_workout(workout)
        except ValueError as exc:
            name = workout.get("name", f"index {i}")
            date_str = workout.get("date", "?")
            raise ValueError(
                f"Validation failed for workout '{name}' ({date_str}): {exc}"
            ) from exc

    # Split into runs (to upload) and others (counted only).
    run_workouts = [w for w in workouts if w.get("sport", "Run") == "Run"]
    skipped_non_run = len(workouts) - len(run_workouts)

    # Build events with external_ids.
    events_with_ids: list[tuple[dict, str]] = []
    for workout in run_workouts:
        ext_id = _external_id(workout)
        event = _build_event(workout, ext_id)
        events_with_ids.append((event, ext_id))

    # 2. Upload to Intervals.icu.
    events = [e for e, _ in events_with_ids]
    if events:
        intervals_client.upsert_events(events)

    # 3. Fetch back events for the week to get Intervals-assigned IDs.
    week_start = _week_start_for(run_workouts) if run_workouts else _week_start_for(workouts)
    week_start_date = date.fromisoformat(week_start)
    week_end = (week_start_date + timedelta(days=6)).isoformat()

    returned_events: list[dict] = []
    if events:
        try:
            returned_events = intervals_client.list_events(after=week_start, before=week_end)
        except Exception as exc:
            _warn(f"Failed to fetch back events from Intervals.icu: {exc}", debug)

    # 4. Build a map of external_id -> intervals_id from returned events.
    intervals_id_map: dict[str, str] = {}
    for ev in returned_events:
        ext = ev.get("external_id")
        iid = ev.get("id")
        if ext and iid:
            intervals_id_map[str(ext)] = str(iid)

    # 5. Insert all workouts into DB.
    created_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    ids_matched = 0
    ids_missing: list[str] = []

    db_mod.init_db(db_path)
    conn = db_mod.get_connection(db_path)
    try:
        for workout in run_workouts:
            ext_id = _external_id(workout)
            intervals_id = intervals_id_map.get(ext_id)

            row = {
                "external_id": ext_id,
                "intervals_id": intervals_id,
                "date": workout["date"],
                "name": workout.get("name", ""),
                "sport": workout.get("sport", "Run"),
                "plan_json": json.dumps(workout),
                "week_start": week_start,
                "created_at": created_at,
            }
            planned_id = db_mod.insert_planned(conn, row)

            if intervals_id:
                ids_matched += 1
            else:
                ids_missing.append(ext_id)
    finally:
        conn.close()

    # 6. Archive unless adhoc.
    archived_to: Optional[str] = None
    if not adhoc and run_workouts:
        archive_path = plan_archive.archive_plan(
            workouts=run_workouts,
            source_file="upload",
            plans_dir=Path(plans_dir),
        )
        if archive_path:
            archived_to = str(archive_path)

    return {
        "uploaded": len(events),
        "ids_matched": ids_matched,
        "ids_missing": ids_missing,
        "skipped_non_run": skipped_non_run,
        "archived_to": archived_to,
    }


def _warn(message: str, debug: bool) -> None:
    print(f"WARNING: {message}", file=sys.stderr)
