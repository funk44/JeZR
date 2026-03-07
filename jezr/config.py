import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv  # type: ignore

# Safe fallback — no-op if env vars are already loaded (e.g. via cli.py entry point)
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


LOCAL_TIMEZONE_DEFAULT = "Australia/Melbourne"


@dataclass
class IntervalsEnv:
    api_key: str
    athlete_id: int = 0


@dataclass
class ClaudeEnv:
    api_key: str


def load_intervals_env() -> IntervalsEnv:
    api_key = os.getenv("INTERVALS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing required environment variable: INTERVALS_API_KEY")
    athlete_id_raw = os.getenv("INTERVALS_ATHLETE_ID", "0")
    try:
        athlete_id = int(athlete_id_raw)
    except ValueError as exc:
        raise RuntimeError("INTERVALS_ATHLETE_ID must be an integer") from exc
    return IntervalsEnv(api_key=api_key, athlete_id=athlete_id)


def load_claude_env() -> ClaudeEnv:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing required environment variable: CLAUDE_API_KEY. "
            "Set it in your .env file or shell environment."
        )
    return ClaudeEnv(api_key=api_key)


def load_local_timezone() -> ZoneInfo:
    name = os.getenv("LOCAL_TIMEZONE")
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            print(
                f"Invalid LOCAL_TIMEZONE='{name}' - falling back to {LOCAL_TIMEZONE_DEFAULT}"
            )
    return ZoneInfo(LOCAL_TIMEZONE_DEFAULT)
