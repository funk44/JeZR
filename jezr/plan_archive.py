import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional


def compute_week_start_iso(workouts: List[Dict]) -> str:
    earliest = min(date.fromisoformat(w["date"]) for w in workouts)
    week_start = earliest - timedelta(days=earliest.weekday())
    return week_start.isoformat()


def archive_plan(
    workouts: List[Dict], source_file: str, plans_dir: Path
) -> Optional[Path]:
    if not workouts:
        return None
    plans_dir.mkdir(parents=True, exist_ok=True)
    week_start = compute_week_start_iso(workouts)
    payload = {
        "week_start": week_start,
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "source_file": source_file,
        "workouts": workouts,
    }
    out_path = plans_dir / f"plan_{week_start}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path
