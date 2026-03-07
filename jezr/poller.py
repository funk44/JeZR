import json
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Optional

from jezr import db as db_mod
from jezr.weather import enrich_activities_with_weather


# ── Activity field mapping (based on export_week_intervals.py logic) ─────────

def _first_value(d: dict, keys: list[str]):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _raw_distance_km(activity: dict) -> Optional[float]:
    raw = _first_value(activity, ["distance", "distance_km", "dist"])
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # Intervals.icu returns distance in metres
    return round(value / 1000.0, 2) if value > 1000 else round(value, 2)


def _raw_duration_min(activity: dict) -> Optional[float]:
    raw = _first_value(activity, ["moving_time", "elapsed_time", "duration"])
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value / 60.0, 2)


def _avg_pace(distance_km: Optional[float], duration_min: Optional[float]) -> Optional[str]:
    if not distance_km or not duration_min or distance_km <= 0 or duration_min <= 0:
        return None
    minutes_per_km = duration_min / distance_km
    total_seconds = int(round(minutes_per_km * 60))
    mins = total_seconds // 60
    secs = total_seconds % 60
    return f"{mins}:{secs:02d}"


def _as_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _activity_date(activity: dict) -> Optional[str]:
    raw = _first_value(activity, ["start_date_local", "start_date"])
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)[:19]).date().isoformat()
    except (ValueError, TypeError):
        return None


def _is_run(activity: dict) -> bool:
    return activity.get("type") == "Run"


def _is_ride(activity: dict) -> bool:
    return activity.get("type") in {
        "Ride", "Virtual Ride", "VirtualRide", "E-Bike Ride",
        "Mountain Bike Ride", "Gravel Ride",
    }


def _map_activity(activity: dict) -> Optional[dict]:
    """Map an Intervals.icu activity to a tbl_actual row dict. Returns None if unsupported type."""
    if not (_is_run(activity) or _is_ride(activity)):
        return None

    act_date = _activity_date(activity)
    if not act_date:
        return None

    distance_km = _raw_distance_km(activity) if _is_run(activity) else None
    duration_min = _raw_duration_min(activity)
    avg_hr = _as_int(_first_value(activity, ["avg_hr", "average_heartrate", "average_hr"]))
    avg_power = (
        _as_int(_first_value(activity, ["avg_power", "average_watts", "average_power"]))
        if _is_ride(activity)
        else None
    )
    training_load = _as_int(_first_value(activity, ["icu_training_load", "training_load"]))

    # Weather fields may have been added by enrich_activities_with_weather()
    wx_temp_c = activity.get("wx_temp_start_c")
    wx_humidity_pct = activity.get("wx_rh_start_pct")

    return {
        "intervals_id": str(activity.get("id") or activity.get("activity_id", "")),
        "date": act_date,
        "name": activity.get("name"),
        "sport": activity.get("type"),
        "distance_km": distance_km,
        "duration_min": duration_min,
        "avg_pace": _avg_pace(distance_km, duration_min) if _is_run(activity) else None,
        "avg_hr": avg_hr,
        "avg_power": avg_power,
        "training_load": training_load,
        "wx_temp_c": wx_temp_c,
        "wx_humidity_pct": wx_humidity_pct,
        "matched_planned_id": None,
        "feedback_sent": 0,
        "raw_json": json.dumps(activity),
        "seen_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
    }


# ── Matching logic ────────────────────────────────────────────────────────────

def _week_bounds_for(act_date: str) -> tuple[str, str]:
    """Return (monday_iso, sunday_iso) for the week containing act_date."""
    d = date.fromisoformat(act_date)
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _match_planned(conn, activity: dict, mapped: dict) -> Optional[int]:
    """Return the tbl_planned id that best matches this activity, or None."""
    # Primary match: tbl_planned row whose intervals_id equals the activity's external_id
    ext_id = activity.get("external_id")
    if ext_id:
        row = db_mod.get_planned_by_external_id(conn, str(ext_id))
        if row:
            return row["id"]

    # Fallback: same sport + same week, closest date
    act_date = mapped.get("date")
    act_sport = mapped.get("sport")
    if not act_date or not act_sport:
        return None

    week_start, _ = _week_bounds_for(act_date)
    candidates = [
        p for p in db_mod.get_planned_for_week(conn, week_start)
        if p.get("sport") == act_sport
    ]
    if not candidates:
        return None

    date_sorted = sorted(
        candidates,
        key=lambda p: abs((date.fromisoformat(p["date"]) - date.fromisoformat(act_date)).days),
    )
    return date_sorted[0]["id"]


# ── State file ────────────────────────────────────────────────────────────────

_MAX_LOOKBACK_DAYS = 7


def _load_state(state_path: Path) -> datetime:
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            last_seen = datetime.fromisoformat(data["last_seen"])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_MAX_LOOKBACK_DAYS)
            if last_seen < cutoff:
                print(
                    f"WARNING: last_seen is more than {_MAX_LOOKBACK_DAYS} days ago "
                    f"({last_seen.date()}) — capping to {cutoff.date()}.",
                    file=sys.stderr,
                )
                return cutoff
            return last_seen
        except (KeyError, ValueError, json.JSONDecodeError):
            pass
    return datetime.now(tz=timezone.utc) - timedelta(days=_MAX_LOOKBACK_DAYS)


def _save_state(state_path: Path, last_seen: datetime) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"last_seen": last_seen.replace(microsecond=0).isoformat()}),
        encoding="utf-8",
    )


# ── Main poller loop ──────────────────────────────────────────────────────────

def _log(message: str) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {message}")


def _db_log(
    db_path: str,
    level: str,
    source: str,
    event: str,
    message: str,
    activity_id: str | None = None,
    extra: dict | None = None,
    conn=None,
) -> None:
    """Log to tbl_log. Uses provided conn if given, otherwise opens a brief one."""
    try:
        if conn is not None:
            db_mod.log_event(conn, level, source, event, message, activity_id, extra)
        else:
            c = db_mod.get_connection(db_path)
            try:
                db_mod.log_event(c, level, source, event, message, activity_id, extra)
            finally:
                c.close()
    except Exception:
        pass  # Never let logging failures crash the poller


def run_poller(
    db_path: str,
    intervals_client,
    notifier,
    api_key: str,
    athlete_context: dict,
    athlete_narrative: str,
    poll_interval_seconds: int = 300,
    debug: bool = False,
) -> None:
    """Run the polling loop until interrupted (KeyboardInterrupt).

    On 3+ consecutive Intervals.icu failures, backs off to 2x the poll interval.
    Resets backoff after a successful poll.
    Logs each poll cycle: timestamp, activities found, any new ones processed.
    """
    from jezr import planner as planner_mod

    db_mod.init_db(db_path)
    state_path = Path(db_path).parent / "poller_state.json"
    last_seen = _load_state(state_path)

    _log(f"Poller started. Last seen: {last_seen.date()}. Poll interval: {poll_interval_seconds}s.")
    _db_log(db_path, "INFO", "poller", "poller_start",
            f"Poller started. Last seen: {last_seen.date()}. Poll interval: {poll_interval_seconds}s.")
    consecutive_failures = 0

    while True:
        now = datetime.now(tz=timezone.utc)
        oldest = last_seen.strftime("%Y-%m-%d")
        newest = now.strftime("%Y-%m-%d")

        try:
            activities = intervals_client.list_activities(oldest=oldest, newest=newest)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            _log(f"ERROR polling Intervals.icu: {exc}")
            _db_log(db_path, "ERROR", "poller", "poll_error",
                    f"Intervals.icu poll failed: {exc}",
                    extra={"traceback": traceback.format_exc(), "failure_count": consecutive_failures})
            sleep_s = poll_interval_seconds * (2 if consecutive_failures >= 3 else 1)
            _log(f"Backing off {sleep_s}s (failure #{consecutive_failures})")
            time.sleep(sleep_s)
            continue

        # Filter to activities strictly newer than last_seen timestamp
        new_activities = []
        for a in activities:
            raw_date = a.get("start_date_local") or a.get("start_date") or ""
            try:
                act_dt = datetime.fromisoformat(raw_date[:19]).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if act_dt > last_seen:
                new_activities.append(a)

        if new_activities:
            # Enrich all with weather before writing to DB
            try:
                enrich_activities_with_weather(new_activities, debug=debug)
            except Exception as exc:
                _log(f"WARNING: weather enrichment failed: {exc}")
                _db_log(db_path, "WARNING", "poller", "weather_failed",
                        f"Weather enrichment failed: {exc}",
                        extra={"traceback": traceback.format_exc()})

            new_count = 0
            conn = db_mod.get_connection(db_path)
            try:
                for activity in new_activities:
                    mapped = _map_activity(activity)
                    if mapped is None:
                        act_type = activity.get("type", "unknown")
                        if debug:
                            _log(f"Skipping unsupported type: {act_type}")
                        _db_log(db_path, "INFO", "poller", "activity_skipped",
                                f"Skipped unsupported activity type: {act_type}",
                                activity_id=str(activity.get("id", "")),
                                conn=conn)
                        continue

                    # Duplicate guard — intervals_id is the stable unique key
                    act_intervals_id = mapped.get("intervals_id", "")
                    existing = db_mod.get_actual_by_intervals_id(conn, mapped["intervals_id"])
                    if existing is not None:
                        if existing.get("feedback_sent", 1) == 0:
                            # Already in DB but feedback not yet sent — send it now
                            actual_id = existing["id"]
                            planned_row = None
                            mid = existing.get("matched_planned_id")
                            if mid is not None:
                                planned_row = db_mod.get_planned_by_id(conn, mid)
                            try:
                                feedback = planner_mod.generate_workout_feedback(
                                    actual=existing,
                                    planned=planned_row,
                                    athlete_context=athlete_context,
                                    athlete_narrative=athlete_narrative,
                                    api_key=api_key,
                                )
                                if feedback:
                                    notifier.send(feedback)
                                db_mod.update_actual_feedback_sent(conn, actual_id)
                                _db_log(db_path, "INFO", "poller", "feedback_sent",
                                        f"{existing.get('name', act_intervals_id)} (retry)",
                                        activity_id=act_intervals_id, conn=conn)
                            except Exception as exc:
                                _log(f"WARNING: feedback retry failed for {act_intervals_id}: {exc}")
                                _db_log(db_path, "ERROR", "poller", "feedback_failed",
                                        f"Feedback retry failed for {act_intervals_id}: {exc}",
                                        activity_id=act_intervals_id,
                                        extra={"traceback": traceback.format_exc()},
                                        conn=conn)
                        elif debug:
                            _log(f"Already seen: {act_intervals_id} — skipping")
                        continue

                    new_count += 1
                    actual_id = db_mod.insert_actual(conn, mapped)
                    _db_log(db_path, "INFO", "poller", "activity_fetched",
                            f"{mapped.get('name', 'Activity')} (intervals_id: {act_intervals_id})",
                            activity_id=act_intervals_id,
                            conn=conn)

                    planned_id = _match_planned(conn, activity, mapped)
                    if planned_id is not None:
                        db_mod.update_actual_match(conn, actual_id, planned_id)

                    # Backlog: activity predates today — mark sent without notifying
                    activity_date = mapped.get("date", "")
                    today = date.today().isoformat()
                    if activity_date < today:
                        db_mod.update_actual_feedback_sent(conn, actual_id)
                        _log(f"Backlog: {mapped.get('name', activity_date)} ({activity_date}) — marked sent silently")
                        _db_log(db_path, "INFO", "poller", "feedback_backlog",
                                f"Backlog activity marked sent: {mapped.get('name', act_intervals_id)}",
                                activity_id=act_intervals_id,
                                conn=conn)
                        continue

                    # Real-time: generate and send feedback
                    planned_row: Optional[dict] = None
                    if planned_id is not None:
                        planned_row = db_mod.get_planned_by_external_id(
                            conn, activity.get("external_id", "")
                        )

                    try:
                        feedback = planner_mod.generate_workout_feedback(
                            actual=mapped,
                            planned=planned_row,
                            athlete_context=athlete_context,
                            athlete_narrative=athlete_narrative,
                            api_key=api_key,
                        )
                        if feedback:
                            notifier.send(feedback)
                        db_mod.update_actual_feedback_sent(conn, actual_id)
                        _db_log(db_path, "INFO", "poller", "feedback_sent",
                                f"{mapped.get('name', act_intervals_id)}",
                                activity_id=act_intervals_id,
                                conn=conn)
                    except Exception as exc:
                        _log(
                            f"WARNING: feedback generation failed for "
                            f"{mapped.get('intervals_id')}: {exc}"
                        )
                        _db_log(db_path, "ERROR", "poller", "feedback_failed",
                                f"Feedback generation failed for {act_intervals_id}: {exc}",
                                activity_id=act_intervals_id,
                                extra={"traceback": traceback.format_exc()},
                                conn=conn)
            finally:
                conn.close()

            _log(f"Poll: {len(activities)} fetched, {new_count} new")
        else:
            _log(f"Poll: {len(activities)} fetched, 0 new")

        last_seen = now
        _save_state(state_path, last_seen)

        try:
            time.sleep(poll_interval_seconds)
        except KeyboardInterrupt:
            _log("Interrupted. Saving state and exiting.")
            _save_state(state_path, last_seen)
            return
