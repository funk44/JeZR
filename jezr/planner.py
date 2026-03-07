import json
import sys
from datetime import date, timedelta

_MODEL = "claude-sonnet-4-20250514"


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _athlete_summary(athlete_context: dict) -> str:
    """Render key athlete fields as a compact text block for prompt injection."""
    name = athlete_context.get("name", "Athlete")
    age = athlete_context.get("age", "")
    threshold = athlete_context.get("threshold_pace_per_km", "")
    block = athlete_context.get("current_block") or {}
    phase = block.get("phase", "")
    weekly_km = block.get("weekly_volume_km", "")
    goals = athlete_context.get("goals") or {}
    primary = goals.get("primary") or {}
    race = primary.get("race", "")
    race_date = primary.get("date", "")
    target = primary.get("target_time", "")

    parts = [f"Athlete: {name}"]
    if age:
        parts.append(f"Age: {age}")
    if threshold:
        parts.append(f"Threshold pace: {threshold}/km")
    if phase:
        parts.append(f"Current block: {phase}")
    if weekly_km:
        parts.append(f"Target weekly volume: {weekly_km} km")
    if race:
        parts.append(f"Goal race: {race} ({race_date}) — target {target}")
    return "\n".join(parts)


def _format_actual(actual: dict) -> str:
    """Render a completed activity as a readable text block."""
    lines = []
    lines.append(f"Date: {actual.get('date', '?')}")
    lines.append(f"Sport: {actual.get('sport', '?')}")
    if actual.get("name"):
        lines.append(f"Name: {actual['name']}")
    if actual.get("distance_km"):
        lines.append(f"Distance: {actual['distance_km']} km")
    if actual.get("duration_min"):
        lines.append(f"Duration: {actual['duration_min']} min")
    if actual.get("avg_pace"):
        lines.append(f"Avg pace: {actual['avg_pace']} /km")
    if actual.get("avg_hr"):
        lines.append(f"Avg HR: {actual['avg_hr']} bpm")
    if actual.get("avg_power"):
        lines.append(f"Avg power: {actual['avg_power']} W")
    if actual.get("training_load"):
        lines.append(f"Training load: {actual['training_load']}")
    if actual.get("wx_temp_c") is not None:
        lines.append(f"Temperature: {actual['wx_temp_c']}°C")
    if actual.get("wx_humidity_pct") is not None:
        lines.append(f"Humidity: {actual['wx_humidity_pct']}%")
    return "\n".join(lines)


def _format_planned_brief(planned: dict) -> str:
    """Render a planned workout name + structure briefly."""
    lines = [f"Planned session: {planned.get('name', '?')} ({planned.get('date', '?')})"]
    plan_json = planned.get("plan_json")
    if plan_json:
        try:
            from jezr.workout_render import render_intervals_workout_text
            workout = json.loads(plan_json)
            lines.append(render_intervals_workout_text(workout))
        except Exception:
            pass
    return "\n".join(lines)


def _format_week_summary(week_summary: dict) -> str:
    """Render the week summary as a structured text block for prompts."""
    sections = []

    matched = week_summary.get("matched") or []
    if matched:
        sections.append("COMPLETED — MATCHED TO PLAN:")
        for pair in matched:
            p = pair["planned"]
            a = pair["actual"]
            sections.append(
                f"  {a.get('date')} {a.get('sport')} — {p.get('name')}\n"
                f"    Planned: {p.get('name')}\n"
                f"    Actual: {a.get('distance_km', '?')} km, "
                f"{a.get('duration_min', '?')} min, "
                f"pace {a.get('avg_pace', '?')}, "
                f"HR {a.get('avg_hr', '?')}, "
                f"load {a.get('training_load', '?')}"
                + (f", {a['wx_temp_c']}°C {a['wx_humidity_pct']}% humidity"
                   if a.get("wx_temp_c") is not None else "")
            )

    unmatched_actual = week_summary.get("unmatched_actual") or []
    if unmatched_actual:
        sections.append("COMPLETED — NOT IN PLAN:")
        for a in unmatched_actual:
            sections.append(
                f"  {a.get('date')} {a.get('sport')} — {a.get('name', '?')}: "
                f"{a.get('distance_km', '?')} km, "
                f"{a.get('duration_min', '?')} min, "
                f"pace {a.get('avg_pace', '?')}, "
                f"HR {a.get('avg_hr', '?')}"
            )

    unmatched_planned = week_summary.get("unmatched_planned") or []
    if unmatched_planned:
        sections.append("PLANNED — NOT COMPLETED:")
        for p in unmatched_planned:
            sections.append(f"  {p.get('date')} {p.get('sport')} — {p.get('name')}")

    return "\n\n".join(sections) if sections else "No sessions recorded this week."


# ── 1a. Post-workout feedback ─────────────────────────────────────────────────

_FEEDBACK_SYSTEM = """\
You are an AI training coach delivering immediate post-workout feedback to an athlete via WhatsApp.
Be direct, specific, and data-driven. No generic encouragement. No emojis. No sign-off.
Reference the athlete's context and history where relevant.
Keep it to 2-4 sentences maximum.
"""


def generate_workout_feedback(
    actual: dict,
    planned: dict | None,
    athlete_context: dict,
    athlete_narrative: str,
    api_key: str,
    debug: bool = False,
) -> str:
    """Call Claude to generate 2-4 sentence post-workout WhatsApp feedback.

    Args:
        actual: Completed activity row dict (from tbl_actual).
        planned: Matched planned workout row dict (from tbl_planned), or None.
        athlete_context: Athlete profile dict.
        athlete_narrative: Full coaching context markdown string.
        api_key: Anthropic API key.
        debug: If True, print debug info to stderr.

    Returns:
        2-4 sentence feedback string.
    """
    import anthropic

    athlete_block = _athlete_summary(athlete_context)
    activity_block = _format_actual(actual)

    if planned:
        plan_block = _format_planned_brief(planned)
        comparison = (
            "Compare the actual performance against the planned session "
            "and comment on execution quality."
        )
    else:
        plan_block = "No planned session matched — feedback based on actuals only."
        comparison = "No planned session to compare against."

    # Flag hot/humid conditions
    temp = actual.get("wx_temp_c")
    humidity = actual.get("wx_humidity_pct")
    weather_note = ""
    if temp is not None and humidity is not None:
        if temp > 25 and humidity > 70:
            weather_note = (
                f"Note: conditions were hot and humid ({temp}°C, {humidity}%). "
                "Factor this in when assessing pace or HR."
            )

    user_prompt = "\n\n".join(filter(None, [
        athlete_block,
        athlete_narrative or None,
        activity_block,
        plan_block,
        comparison,
        weather_note or None,
    ]))

    if debug:
        print(f"generate_workout_feedback: user prompt:\n{user_prompt}", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_FEEDBACK_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


# ── 1b. Weekly review + plan ──────────────────────────────────────────────────

_REVIEW_SYSTEM = """\
You are an AI training coach generating a weekly training review and proposing next week's plan.

Your review should be honest, specific, and grounded in the data. Note what went well,
what was missed, and any patterns worth flagging (fatigue, weather impact, load spikes).

Your proposed plan must:
- Be realistic given what actually happened this week
- Match the athlete's stated training structure and preferences
- Use only Run workouts (Rides are noted but not planned via this tool)
- Output pace values as integers (percentage of threshold pace) — never floats
- Match the schema of the sample plan provided exactly

Respond ONLY with a JSON object in this exact format:
{
  "review_text": "<3-5 sentence review>",
  "proposed_plan": [<array of workout objects matching sample plan schema>]
}
No preamble, no markdown, no explanation outside the JSON.
"""

_PACE_CONVENTIONS = """\
Pace convention (integer % of threshold pace):
- Recovery: 65-70
- Easy / long run: 80-85
- Tempo: 95-100
- Intervals: 100-110
- Strides: 100-112
"""


def generate_weekly_review(
    week_summary: dict,
    athlete_context: dict,
    athlete_narrative: str,
    sample_plan: list,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Call Claude to generate a weekly review and propose next week's training plan.

    Args:
        week_summary: Structured summary from db.get_week_summary().
        athlete_context: Athlete profile dict.
        athlete_narrative: Full coaching context markdown string.
        sample_plan: List of sample workout dicts showing the required output schema.
        api_key: Anthropic API key.
        debug: If True, print raw API response to stderr on parse failure.

    Returns:
        {"review_text": str, "proposed_plan": list}

    Raises:
        ValueError: If the Claude response cannot be parsed as JSON.
    """
    import anthropic

    athlete_block = _athlete_summary(athlete_context)
    week_block = _format_week_summary(week_summary)
    sample_block = json.dumps(sample_plan, indent=2)

    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    next_monday = today + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)

    user_prompt = f"""{athlete_block}

{athlete_narrative or ""}

WEEK {week_summary.get('week_start')} — {week_summary.get('week_end')}:
{week_block}

{_PACE_CONVENTIONS}

PROPOSED PLAN TARGET WEEK: {next_monday.isoformat()} to {next_sunday.isoformat()}
All workout dates in proposed_plan MUST fall within this range. Do not use dates outside this range.

Sample plan schema (your proposed_plan array must match this exactly — field names, pace as integers, duration format):
{sample_block}
"""

    if debug:
        print(f"generate_weekly_review: user prompt:\n{user_prompt}", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_REVIEW_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text.strip()

    if debug:
        print(f"generate_weekly_review: raw response:\n{raw}", file=sys.stderr)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse weekly review response from Claude: {exc}\n\nRaw response:\n{raw}"
        ) from exc

    return {
        "review_text": result.get("review_text", ""),
        "proposed_plan": result.get("proposed_plan", []),
    }


# ── 1c. Mid-week check-in ─────────────────────────────────────────────────────

_WTD_SYSTEM = """\
You are an AI training coach providing a mid-week check-in summary for an athlete.
Be concise and direct. 3-5 sentences. Focus on what's been done, what's still ahead,
and any load or pattern worth noting before the week is out.
No emojis. No sign-off.
"""


def generate_week_to_date_summary(
    week_summary: dict,
    athlete_context: dict,
    athlete_narrative: str,
    api_key: str,
    debug: bool = False,
) -> str:
    """Call Claude to generate a 3-5 sentence mid-week check-in summary.

    Args:
        week_summary: Partial week summary from db.get_week_summary() (Monday to today).
        athlete_context: Athlete profile dict.
        athlete_narrative: Full coaching context markdown string.
        api_key: Anthropic API key.
        debug: If True, print debug info to stderr.

    Returns:
        Plain-text summary string.
    """
    import anthropic

    athlete_block = _athlete_summary(athlete_context)
    week_block = _format_week_summary(week_summary)

    completed_count = len(week_summary.get("actual") or [])
    remaining = week_summary.get("unmatched_planned") or []

    user_prompt = f"""{athlete_block}

{athlete_narrative or ""}

Week to date ({week_summary.get('week_start')} — today):
{week_block}

Sessions completed so far: {completed_count}
Sessions still planned: {len(remaining)}
{("Remaining: " + ", ".join(p.get("name", "?") for p in remaining)) if remaining else ""}

Provide a brief check-in: what's been done, how it looks, anything to watch for the rest of the week.
"""

    if debug:
        print(f"generate_week_to_date_summary: user prompt:\n{user_prompt}", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_WTD_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


# ── 1d. Plan revision based on athlete feedback ───────────────────────────────

_REVISE_SYSTEM = """\
You are an AI training coach revising a proposed weekly training plan based on athlete feedback.

The athlete has reviewed the proposed plan and provided specific feedback.
Revise the plan to address their feedback while maintaining training integrity.
Do not make changes beyond what the feedback requests.

Your revised review_text should briefly acknowledge what was changed and why, e.g.:
"Moved Wednesday's tempo to Thursday as requested. Rest of the week unchanged."

Respond ONLY with a JSON object in this exact format:
{
  "review_text": "<1-3 sentence acknowledgement of the change>",
  "proposed_plan": [<array of workout objects matching sample plan schema>]
}
No preamble, no markdown, no explanation outside the JSON.
"""


def revise_plan(
    current_plan: list,
    feedback: str,
    athlete_context: dict,
    athlete_narrative: str,
    sample_plan: list,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Revise a proposed plan based on athlete feedback.

    Args:
        current_plan: The currently pending proposed plan (list of workout dicts).
        feedback: Athlete's feedback text verbatim.
        athlete_context: Athlete profile dict.
        athlete_narrative: Full coaching context markdown string.
        sample_plan: List of sample workout dicts showing the required output schema.
        api_key: Anthropic API key.
        debug: If True, print debug info to stderr.

    Returns:
        {"review_text": str, "proposed_plan": list}

    Raises:
        ValueError: If the Claude response cannot be parsed as JSON.
    """
    import anthropic

    athlete_block = _athlete_summary(athlete_context)
    current_plan_json = json.dumps(current_plan, indent=2)
    sample_block = json.dumps(sample_plan, indent=2)

    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    next_monday = today + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)

    user_prompt = f"""{athlete_block}

{athlete_narrative or ""}

Current proposed plan (JSON):
{current_plan_json}

Athlete feedback:
{feedback}

{_PACE_CONVENTIONS}

PROPOSED PLAN TARGET WEEK: {next_monday.isoformat()} to {next_sunday.isoformat()}
All workout dates in proposed_plan MUST fall within this range. Do not use dates outside this range.

Sample plan schema (your proposed_plan array must match this exactly — field names, pace as integers, duration format):
{sample_block}
"""

    if debug:
        print(f"revise_plan: user prompt:\n{user_prompt}", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_REVISE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text.strip()

    if debug:
        print(f"revise_plan: raw response:\n{raw}", file=sys.stderr)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse plan revision response from Claude: {exc}\n\nRaw response:\n{raw}"
        ) from exc

    return {
        "review_text": result.get("review_text", ""),
        "proposed_plan": result.get("proposed_plan", []),
    }


# ── 2. Athlete profile import ─────────────────────────────────────────────────

_IMPORT_SYSTEM = """\
You are helping restructure existing athlete context into a standardised training profile
for JeZR, an AI training coach system.

The user has provided existing notes, documents, or conversation history containing
athlete information. Your job is to:
1. Extract all relevant information from the source text
2. Restructure it into the two required output formats
3. Identify anything important that is missing or unclear

Be faithful to what is actually in the source text. Do not invent details.
For missing fields, use null in the JSON and note the gap.
"""


def import_athlete_profile(
    source_text: str,
    athlete_template_json: dict,
    athlete_template_md: str,
    api_key: str,
    debug: bool = False,
) -> dict:
    """Read existing athlete context in any format and restructure it into
    the two JeZR athlete profile files.

    Returns:
        {
            "athlete_json": dict,   # structured profile matching athlete.template.json
            "athlete_md": str,      # narrative context matching athlete.template.md structure
            "gaps": list[str],      # fields that could not be inferred and need manual completion
        }

    Raises:
        ValueError: If the Claude response cannot be parsed as JSON.
    """
    import anthropic

    today = date.today().isoformat()
    template_json_str = json.dumps(athlete_template_json, indent=2)

    user_prompt = f"""SOURCE TEXT:
{source_text}

---

STEP 1 — JSON PROFILE

Populate this JSON with information from the source text.
Use null for any field that cannot be inferred.
Remove all _comment and _note fields from the output.
Set "last_reviewed" to "{today}".

{template_json_str}

---

STEP 2 — NARRATIVE CONTEXT (athlete.md)

Write the narrative sections based on the source text using the template structure below.
Where the source text is rich on a topic, use that detail.
Where it is sparse or silent, write a brief placeholder and add the section name to the gaps list.

{athlete_template_md}

---

Respond ONLY with a JSON object in this exact format — no preamble, no markdown fences around the outer object:
{{
  "athlete_json": {{ <populated athlete.json> }},
  "athlete_md": "<full athlete.md content as a string>",
  "gaps": ["<field or section name>", ...]
}}"""

    if debug:
        print(f"import_athlete_profile: user prompt:\n{user_prompt}", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_IMPORT_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text.strip()

    if debug:
        print(f"import_athlete_profile: raw response:\n{raw}", file=sys.stderr)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Failed to parse import response from Claude: {exc}"
        if debug:
            msg += f"\n\nRaw response:\n{raw}"
        raise ValueError(msg) from exc

    return {
        "athlete_json": result.get("athlete_json", {}),
        "athlete_md": result.get("athlete_md", "").replace("\\n", "\n"),
        "gaps": result.get("gaps", []),
    }
