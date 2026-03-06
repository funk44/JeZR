import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from jezr import db as db_mod
from jezr import planner as planner_mod
from jezr.validator import validate_and_sense_check


# ── Plan formatting ───────────────────────────────────────────────────────────

def _format_plan_for_whatsapp(workouts: list[dict]) -> str:
    """Render a proposed plan as plain text suitable for WhatsApp.

    Example:
        Mon 9 Mar — Tempo Run
          Warmup: 25min easy (82%)
          Main: 6km tempo (97%)
          Cooldown: 10min easy (82%)
        Tue 10 Mar — Rest
    """
    if not workouts:
        return "(No workouts in plan)"

    # Build a full week grid (Mon–Sun) anchored to the earliest workout date
    all_dates = [date.fromisoformat(w["date"]) for w in workouts if w.get("date")]
    if not all_dates:
        return "(No valid dates in plan)"

    earliest = min(all_dates)
    monday = earliest - timedelta(days=earliest.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]

    by_date: dict[str, dict] = {w["date"]: w for w in workouts if w.get("date")}

    lines = []
    for day in week_days:
        day_str = day.isoformat()
        label = day.strftime("%a %-d %b")  # e.g. "Mon 9 Mar"
        workout = by_date.get(day_str)
        if workout is None:
            lines.append(f"{label} — Rest")
            continue

        name = workout.get("name", "Workout")
        lines.append(f"{label} — {name}")
        lines.extend(_render_workout_steps(workout))

    return "\n".join(lines)


def _render_workout_steps(workout: dict) -> list[str]:
    """Render workout sections/steps as indented plain-text lines."""
    lines = []
    sections = workout.get("sections")
    if sections:
        for section in sections:
            sec_name = section.get("name", "")
            steps = section.get("trainings") or []
            step_lines = _render_steps(steps)
            if sec_name and step_lines:
                # Prefix first step with section name
                lines.append(f"  {sec_name}: {step_lines[0]}")
                for sl in step_lines[1:]:
                    lines.append(f"  {sl}")
            else:
                for sl in step_lines:
                    lines.append(f"  {sl}")
    else:
        for sl in _render_steps(workout.get("trainings") or []):
            lines.append(f"  {sl}")
    return lines


def _render_steps(steps: list[dict]) -> list[str]:
    lines = []
    for step in steps:
        if "repeat" in step:
            repeat = step["repeat"]
            count = repeat.get("count", "?")
            inner = _render_steps(repeat.get("trainings") or [])
            inner_str = " / ".join(inner)
            lines.append(f"{count}x [{inner_str}]")
        else:
            duration = step.get("duration", "?")
            pace = step.get("pace", "?")
            desc = step.get("description", "")
            if desc:
                lines.append(f"{duration} @ {pace}% — {desc}")
            else:
                lines.append(f"{duration} @ {pace}%")
    return lines


# ── Week boundary helpers ─────────────────────────────────────────────────────

def _previous_week_bounds() -> tuple[str, str]:
    """Return (monday, sunday) of the most recently completed week."""
    today = date.today()
    # Monday of current week
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday.isoformat(), last_sunday.isoformat()


def _current_week_bounds() -> tuple[str, str]:
    """Return (monday, today) for the current week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), today.isoformat()


# ── Weekly review ─────────────────────────────────────────────────────────────

def run_weekly_review(
    db_path: str,
    athlete_context: dict,
    athlete_narrative: str,
    sample_plan: list,
    notifier,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Generate the weekly review and proposed next week plan.

    Flow:
    1. Query the previous week (Mon–Sun) from tbl_planned and tbl_actual
    2. Call planner.generate_weekly_review() with summary + context
    3. Run validator.validate_and_sense_check() on proposed plan
    4. Format and send WhatsApp message via notifier
    5. Write proposed plan to data/pending_plan.json
    6. Return structured result dict

    Returns:
        {
            "week_start": str,
            "week_end": str,
            "review_text": str,
            "proposed_plan": list,
            "schema_errors": list,
            "sense_check_flags": list,
            "pending_plan_path": str,
        }
    """
    week_start, week_end = _previous_week_bounds()

    db_mod.init_db(db_path)
    conn = db_mod.get_connection(db_path)
    try:
        week_summary = db_mod.get_week_summary(conn, week_start, week_end)
    finally:
        conn.close()

    # Generate review + proposed plan via Claude
    review = planner_mod.generate_weekly_review(
        week_summary=week_summary,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        sample_plan=sample_plan,
        api_key=api_key,
        debug=debug,
    )
    review_text = review["review_text"]
    proposed_plan = review["proposed_plan"]

    # Validate the proposed plan
    validation = validate_and_sense_check(
        workouts=proposed_plan,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        previous_week_summary=week_summary,
        api_key=api_key,
        debug=debug,
    )
    schema_errors = validation["schema_errors"]
    sense_check_flags = validation["sense_check_flags"]

    # Format human-readable plan
    plan_text = _format_plan_for_whatsapp(proposed_plan)

    # Build WhatsApp message
    msg_parts = [
        f"Week of {week_start}",
        "",
        review_text,
        "",
        "\u2015" * 17,
        "PROPOSED NEXT WEEK",
        "",
        plan_text,
    ]

    if schema_errors:
        msg_parts += [
            "",
            "\u2015" * 17,
            "SCHEMA ERRORS (must fix before uploading):",
        ]
        for err in schema_errors:
            msg_parts.append(f"  - {err}")

    if sense_check_flags:
        msg_parts += [
            "",
            "\u2015" * 17,
            "SENSE CHECK FLAGS (advisory):",
        ]
        for flag in sense_check_flags:
            msg_parts.append(f"  - {flag}")

    msg_parts += [
        "",
        "\u2015" * 17,
        "Reply YES to upload to Intervals.icu, or tell me what to change.",
        "(Or run: jezr upload --planned data/pending_plan.json)",
    ]

    message = "\n".join(msg_parts)
    notifier.send(message)

    # Save pending plan
    pending_path = Path(db_path).parent / "pending_plan.json"
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(
        json.dumps(proposed_plan, indent=2), encoding="utf-8"
    )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "review_text": review_text,
        "proposed_plan": proposed_plan,
        "schema_errors": schema_errors,
        "sense_check_flags": sense_check_flags,
        "pending_plan_path": str(pending_path),
    }


# ── Week-to-date check-in ─────────────────────────────────────────────────────

def run_week_to_date_summary(
    db_path: str,
    athlete_context: dict,
    athlete_narrative: str,
    notifier,
    api_key: str,
    debug: bool = False,
) -> str:
    """Generate and send a mid-week check-in summary.

    Queries tbl_actual and tbl_planned for the current week (Monday to today),
    calls planner.generate_week_to_date_summary(), sends via notifier.

    Returns:
        The summary string.
    """
    week_start, week_end = _current_week_bounds()

    db_mod.init_db(db_path)
    conn = db_mod.get_connection(db_path)
    try:
        week_summary = db_mod.get_week_summary(conn, week_start, week_end)
    finally:
        conn.close()

    summary = planner_mod.generate_week_to_date_summary(
        week_summary=week_summary,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        api_key=api_key,
        debug=debug,
    )
    notifier.send(summary)
    return summary


# ── Plan revision (feedback loop) ─────────────────────────────────────────────

def run_feedback_revision(
    feedback: str,
    db_path: str,
    athlete_context: dict,
    athlete_narrative: str,
    sample_plan: list,
    notifier,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Revise the pending plan based on athlete feedback and re-send for approval.

    Flow:
    1. Load data/pending_plan.json — raises FileNotFoundError if missing
    2. Call planner.revise_plan() with current plan + feedback
    3. Validate and sense-check the revised plan
    4. Format and send revised plan via notifier
    5. Overwrite data/pending_plan.json with revised plan
    6. Return same result dict shape as run_weekly_review()

    Returns:
        {
            "review_text": str,
            "proposed_plan": list,
            "schema_errors": list,
            "sense_check_flags": list,
            "pending_plan_path": str,
        }

    Raises:
        FileNotFoundError: If data/pending_plan.json does not exist.
    """
    pending_path = Path(db_path).parent / "pending_plan.json"
    if not pending_path.exists():
        raise FileNotFoundError(
            f"No pending plan found at {pending_path}. "
            "Run 'jezr review' first to generate a plan for approval."
        )

    current_plan = json.loads(pending_path.read_text(encoding="utf-8"))

    # Revise via Claude
    revision = planner_mod.revise_plan(
        current_plan=current_plan,
        feedback=feedback,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        sample_plan=sample_plan,
        api_key=api_key,
        debug=debug,
    )
    review_text = revision["review_text"]
    proposed_plan = revision["proposed_plan"]

    # Validate the revised plan
    from jezr.validator import validate_and_sense_check
    validation = validate_and_sense_check(
        workouts=proposed_plan,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        previous_week_summary=None,
        api_key=api_key,
        debug=debug,
    )
    schema_errors = validation["schema_errors"]
    sense_check_flags = validation["sense_check_flags"]

    # Format revised plan for WhatsApp
    plan_text = _format_plan_for_whatsapp(proposed_plan)

    msg_parts = [
        review_text,
        "",
        "\u2015" * 17,
        "REVISED PLAN",
        "",
        plan_text,
    ]

    if schema_errors:
        msg_parts += [
            "",
            "\u2015" * 17,
            "SCHEMA ERRORS (must fix before uploading):",
        ]
        for err in schema_errors:
            msg_parts.append(f"  - {err}")

    if sense_check_flags:
        msg_parts += [
            "",
            "\u2015" * 17,
            "SENSE CHECK FLAGS (advisory):",
        ]
        for flag in sense_check_flags:
            msg_parts.append(f"  - {flag}")

    msg_parts += [
        "",
        "\u2015" * 17,
        "Reply YES to upload to Intervals.icu, or tell me what to change.",
        "(Or run: jezr upload --planned data/pending_plan.json)",
    ]

    message = "\n".join(msg_parts)
    notifier.send(message)

    # Overwrite pending plan
    pending_path.write_text(json.dumps(proposed_plan, indent=2), encoding="utf-8")

    return {
        "review_text": review_text,
        "proposed_plan": proposed_plan,
        "schema_errors": schema_errors,
        "sense_check_flags": sense_check_flags,
        "pending_plan_path": str(pending_path),
    }
