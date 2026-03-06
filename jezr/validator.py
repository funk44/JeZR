import json
import sys

from jezr.workout_render import validate_planned_workout


# ── Stage 1: Hard schema validation ─────────────────────────────────────────

def validate_plan_schema(workouts: list[dict]) -> list[str]:
    """Run hard schema validation on a list of planned workout dicts.

    Uses workout_render.validate_planned_workout() on each workout.
    Returns a list of error strings (empty list = all valid).
    Does not raise — callers decide what to do with errors.
    """
    errors: list[str] = []
    for i, workout in enumerate(workouts):
        try:
            validate_planned_workout(workout)
        except ValueError as exc:
            name = workout.get("name", f"index {i}")
            date_str = workout.get("date", "?")
            errors.append(f"Workout '{name}' ({date_str}): {exc}")
    return errors


# ── Stage 2: AI sense check ──────────────────────────────────────────────────

_SENSE_CHECK_SYSTEM = """\
You are a running coach assistant reviewing a proposed training plan for an athlete.
Your job is to identify potential problems with the plan structure, not to rewrite it.
Respond ONLY with a JSON array of plain-English concern strings.
If there are no concerns, respond with an empty array: []
Do not include any explanation, preamble, or markdown — only the JSON array.
"""

_SENSE_CHECK_USER = """\
Athlete profile:
{athlete_context}

{narrative_section}
{previous_week_section}

Proposed plan (workouts as JSON):
{workouts_json}

Pace convention (integer % of threshold pace):
- Recovery: 65-70
- Easy / long run: 80-85
- Tempo: 95-100
- Intervals: 100-110
- Strides: 100-112

Check for:
1. Pace values that are valid integers but contextually wrong for the session type
   (e.g. 45% on a tempo run, 130% on a long run, recovery pace on an interval session)
2. Weekly volume that spikes more than ~10% from the previous week's actual volume (if known)
3. Back-to-back hard sessions (intervals, tempo, or long run on consecutive days)
4. Long run placed the day before or after a quality session
5. Any single session that looks disproportionate to the described training block phase
6. Total weekly structure that doesn't match the athlete's stated preferences

Return a JSON array of concern strings, or [] if none.
"""


def sense_check_plan(
    workouts: list[dict],
    athlete_context: dict,
    athlete_narrative: str,
    previous_week_summary: dict | None,
    api_key: str,
    debug: bool = False,
) -> list[str]:
    """Ask Claude to sense-check a proposed plan against athlete context and recent training.

    Returns a list of plain-English concern strings (empty list = no concerns).
    This check is advisory only — it never blocks the plan.
    """
    import anthropic

    narrative_section = ""
    if athlete_narrative:
        narrative_section = f"Athlete narrative:\n{athlete_narrative}"

    previous_week_section = ""
    if previous_week_summary:
        actual = previous_week_summary.get("actual", [])
        if actual:
            total_km = sum(a.get("distance_km") or 0 for a in actual)
            session_count = len(actual)
            previous_week_section = (
                f"Previous week summary: {session_count} sessions, "
                f"{total_km:.1f} km total actual volume."
            )

    user_prompt = _SENSE_CHECK_USER.format(
        athlete_context=json.dumps(athlete_context, indent=2),
        narrative_section=narrative_section,
        previous_week_section=previous_week_section,
        workouts_json=json.dumps(workouts, indent=2),
    )

    if debug:
        print("sense_check_plan: calling Claude API", file=sys.stderr)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SENSE_CHECK_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        if debug:
            print(f"sense_check_plan: raw response: {raw}", file=sys.stderr)
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"WARNING: sense_check_plan: failed to parse Claude response as JSON: {exc}",
            file=sys.stderr,
        )
        return []
    except Exception as exc:
        print(f"WARNING: sense_check_plan: Claude API error: {exc}", file=sys.stderr)
        return []


# ── Combined validator ────────────────────────────────────────────────────────

def validate_and_sense_check(
    workouts: list[dict],
    athlete_context: dict,
    athlete_narrative: str,
    previous_week_summary: dict | None,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Run both validation stages and return a combined result.

    Returns:
        {
            "schema_errors": list[str],     # hard failures — empty if all valid
            "sense_check_flags": list[str], # advisory concerns — empty if none
            "passed_schema": bool,
            "has_flags": bool,
        }
    """
    schema_errors = validate_plan_schema(workouts)
    passed_schema = len(schema_errors) == 0

    sense_check_flags: list[str] = []
    if passed_schema:
        sense_check_flags = sense_check_plan(
            workouts=workouts,
            athlete_context=athlete_context,
            athlete_narrative=athlete_narrative,
            previous_week_summary=previous_week_summary,
            api_key=api_key,
            debug=debug,
        )

    return {
        "schema_errors": schema_errors,
        "sense_check_flags": sense_check_flags,
        "passed_schema": passed_schema,
        "has_flags": len(sense_check_flags) > 0,
    }
