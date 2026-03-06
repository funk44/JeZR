import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_DURATION_RE = re.compile(r"^\s*\d+(\.\d+)?\s*(m|km|s)\s*$", re.IGNORECASE)


def _format_duration_seconds(seconds: int) -> str:
    if seconds <= 0:
        raise ValueError("Duration seconds must be > 0.")
    minutes, secs = divmod(seconds, 60)
    if seconds < 60:
        return f"{seconds}s"
    if secs == 0:
        return f"{minutes}m"
    return f"{seconds}s"


def _format_duration(duration: Any) -> str:
    if isinstance(duration, int):
        return _format_duration_seconds(duration)
    if isinstance(duration, str):
        if not _DURATION_RE.match(duration):
            raise ValueError(f"Invalid duration string: {duration}")
        return duration.strip()
    raise ValueError(f"Invalid duration type: {type(duration).__name__}")


def _format_pace(pace: Any) -> str:
    if not isinstance(pace, int):
        raise ValueError(f"Invalid pace type: {type(pace).__name__}")
    if pace < 1 or pace > 150:
        raise ValueError(f"Invalid pace percentage: {pace}")
    return f"{pace}% Pace"


def _validate_step(step: Dict[str, Any], path: str) -> None:
    if "repeat" in step:
        repeat = step.get("repeat")
        if not isinstance(repeat, dict):
            raise ValueError(f"{path}.repeat must be an object")
        count = repeat.get("count")
        if not isinstance(count, int) or count < 1:
            raise ValueError(f"{path}.repeat.count must be an int >= 1")
        trainings = repeat.get("trainings")
        if not isinstance(trainings, list) or not trainings:
            raise ValueError(f"{path}.repeat.trainings must be a non-empty list")
        for idx, sub in enumerate(trainings):
            if not isinstance(sub, dict):
                raise ValueError(f"{path}.repeat.trainings[{idx}] must be an object")
            _validate_step(sub, f"{path}.repeat.trainings[{idx}]")
        return
    if "duration" not in step:
        raise ValueError(f"{path} missing duration")
    if "pace" not in step:
        raise ValueError(f"{path} missing pace")
    _format_duration(step.get("duration"))
    _format_pace(step.get("pace"))


def validate_planned_workout(planned_workout: Dict[str, Any]) -> None:
    trainings = planned_workout.get("trainings")
    sections = planned_workout.get("sections")
    has_sections = isinstance(sections, list) and sections
    if not has_sections and not isinstance(trainings, list):
        raise ValueError("planned workout must include 'trainings' or non-empty 'sections'")
    if has_sections:
        for sec_idx, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError(f"sections[{sec_idx}] must be an object")
            steps = section.get("trainings")
            if not isinstance(steps, list) or not steps:
                raise ValueError(f"sections[{sec_idx}].trainings must be a non-empty list")
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    raise ValueError(f"sections[{sec_idx}].trainings[{idx}] must be an object")
                _validate_step(step, f"sections[{sec_idx}].trainings[{idx}]")
        return
    if trainings is None:
        raise ValueError("planned workout missing 'trainings'")
    if not trainings:
        raise ValueError("trainings must be a non-empty list")
    for idx, step in enumerate(trainings):
        if not isinstance(step, dict):
            raise ValueError(f"trainings[{idx}] must be an object")
        _validate_step(step, f"trainings[{idx}]")


def _render_steps(trainings: Sequence[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for step in trainings:
        if "repeat" in step:
            repeat = step["repeat"]
            lines.append(f"{repeat['count']}x")
            lines.extend(_render_steps(repeat["trainings"]))
            continue
        duration = _format_duration(step["duration"])
        pace = _format_pace(step["pace"])
        description = (step.get("description") or "").strip()
        if description:
            lines.append(f"- {duration} {pace} {description}")
        else:
            lines.append(f"- {duration} {pace}")
    return lines


def _sections_from_metadata(planned_workout: Dict[str, Any]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    if isinstance(planned_workout.get("sections"), list) and planned_workout["sections"]:
        sections = []
        for section in planned_workout["sections"]:
            title = section.get("name") or section.get("title") or ""
            sections.append((title.strip(), section.get("trainings") or []))
        return sections

    ordered = []
    for key, title in (("warmup", "Warmup"), ("main_set", "Main set"), ("cooldown", "Cooldown")):
        steps = planned_workout.get(key)
        if isinstance(steps, list) and steps:
            ordered.append((title, steps))
    return ordered


def render_intervals_workout_text(planned_workout: Dict[str, Any]) -> str:
    validate_planned_workout(planned_workout)
    sections = _sections_from_metadata(planned_workout)
    lines: List[str] = []

    if sections:
        for idx, (title, steps) in enumerate(sections):
            if idx > 0:
                lines.append("")
            if title:
                lines.append(title)
            lines.extend(_render_steps(steps))
    else:
        lines.extend(_render_steps(planned_workout["trainings"]))

    return "\n".join(lines)
