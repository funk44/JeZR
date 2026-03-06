import os
import sqlite3
from pathlib import Path
from typing import Optional


_DEFAULT_DB_PATH = os.getenv("JEZR_DB_PATH", "./data/jezr.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tbl_planned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    intervals_id TEXT,
    date TEXT NOT NULL,
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    week_start TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tbl_actual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intervals_id TEXT NOT NULL UNIQUE,
    date TEXT NOT NULL,
    name TEXT,
    sport TEXT,
    distance_km REAL,
    duration_min REAL,
    avg_pace TEXT,
    avg_hr INTEGER,
    avg_power INTEGER,
    training_load INTEGER,
    wx_temp_c REAL,
    wx_humidity_pct REAL,
    matched_planned_id INTEGER REFERENCES tbl_planned(id),
    feedback_sent INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL,
    seen_at TEXT NOT NULL
);
"""


def get_connection(db_path: str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory and foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = _DEFAULT_DB_PATH) -> None:
    """Create the database file (and parent dirs) and both tables if they don't exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── tbl_planned ─────────────────────────────────────────────────────────────

def insert_planned(conn: sqlite3.Connection, workout: dict) -> int:
    """Insert a planned workout row. Returns the new row id."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO tbl_planned
                (external_id, intervals_id, date, name, sport, plan_json, week_start, created_at)
            VALUES
                (:external_id, :intervals_id, :date, :name, :sport, :plan_json, :week_start, :created_at)
            """,
            workout,
        )
    return cur.lastrowid


def update_planned_intervals_id(
    conn: sqlite3.Connection, planned_id: int, intervals_id: str
) -> None:
    """Set intervals_id on an existing tbl_planned row."""
    with conn:
        conn.execute(
            "UPDATE tbl_planned SET intervals_id = ? WHERE id = ?",
            (intervals_id, planned_id),
        )


def get_planned_by_external_id(
    conn: sqlite3.Connection, external_id: str
) -> Optional[dict]:
    """Return the tbl_planned row matching external_id, or None."""
    row = conn.execute(
        "SELECT * FROM tbl_planned WHERE external_id = ?", (external_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_planned_for_week(conn: sqlite3.Connection, week_start: str) -> list[dict]:
    """Return all tbl_planned rows for a given week_start, ordered by date."""
    rows = conn.execute(
        "SELECT * FROM tbl_planned WHERE week_start = ? ORDER BY date",
        (week_start,),
    ).fetchall()
    return _rows_to_dicts(rows)


# ── tbl_actual ───────────────────────────────────────────────────────────────

def insert_actual(conn: sqlite3.Connection, activity: dict) -> int:
    """Insert a completed activity. Returns the row id.

    If intervals_id already exists (UNIQUE constraint), returns the existing id
    without raising.
    """
    existing = get_actual_by_intervals_id(conn, activity["intervals_id"])
    if existing is not None:
        return existing["id"]
    with conn:
        cur = conn.execute(
            """
            INSERT INTO tbl_actual
                (intervals_id, date, name, sport, distance_km, duration_min,
                 avg_pace, avg_hr, avg_power, training_load,
                 wx_temp_c, wx_humidity_pct,
                 matched_planned_id, feedback_sent, raw_json, seen_at)
            VALUES
                (:intervals_id, :date, :name, :sport, :distance_km, :duration_min,
                 :avg_pace, :avg_hr, :avg_power, :training_load,
                 :wx_temp_c, :wx_humidity_pct,
                 :matched_planned_id, :feedback_sent, :raw_json, :seen_at)
            """,
            activity,
        )
    return cur.lastrowid


def get_actual_by_intervals_id(
    conn: sqlite3.Connection, intervals_id: str
) -> Optional[dict]:
    """Return the tbl_actual row matching intervals_id, or None."""
    row = conn.execute(
        "SELECT * FROM tbl_actual WHERE intervals_id = ?", (intervals_id,)
    ).fetchone()
    return _row_to_dict(row)


def update_actual_match(
    conn: sqlite3.Connection, actual_id: int, planned_id: int
) -> None:
    """Set matched_planned_id on a tbl_actual row."""
    with conn:
        conn.execute(
            "UPDATE tbl_actual SET matched_planned_id = ? WHERE id = ?",
            (planned_id, actual_id),
        )


def update_actual_feedback_sent(conn: sqlite3.Connection, actual_id: int) -> None:
    """Set feedback_sent = 1 on a tbl_actual row."""
    with conn:
        conn.execute(
            "UPDATE tbl_actual SET feedback_sent = 1 WHERE id = ?",
            (actual_id,),
        )


def get_actuals_pending_feedback(conn: sqlite3.Connection) -> list[dict]:
    """Return all tbl_actual rows where feedback_sent = 0, ordered by date."""
    rows = conn.execute(
        "SELECT * FROM tbl_actual WHERE feedback_sent = 0 ORDER BY date"
    ).fetchall()
    return _rows_to_dicts(rows)


# ── weekly summary ───────────────────────────────────────────────────────────

def get_week_summary(
    conn: sqlite3.Connection, week_start: str, week_end: str
) -> dict:
    """Return a structured summary of planned vs actual for the given week range.

    Returns:
        {
            "week_start": str,
            "week_end": str,
            "planned": [tbl_planned rows],
            "actual": [tbl_actual rows],
            "matched": [{"planned": row, "actual": row}],
            "unmatched_planned": [planned rows with no matching actual],
            "unmatched_actual": [actual rows with no matched_planned_id],
        }
    """
    planned = _rows_to_dicts(
        conn.execute(
            "SELECT * FROM tbl_planned WHERE date BETWEEN ? AND ? ORDER BY date",
            (week_start, week_end),
        ).fetchall()
    )
    actual = _rows_to_dicts(
        conn.execute(
            "SELECT * FROM tbl_actual WHERE date BETWEEN ? AND ? ORDER BY date",
            (week_start, week_end),
        ).fetchall()
    )

    planned_by_id = {p["id"]: p for p in planned}
    matched_planned_ids = set()
    matched = []
    unmatched_actual = []

    for a in actual:
        pid = a.get("matched_planned_id")
        if pid is not None and pid in planned_by_id:
            matched.append({"planned": planned_by_id[pid], "actual": a})
            matched_planned_ids.add(pid)
        else:
            unmatched_actual.append(a)

    unmatched_planned = [p for p in planned if p["id"] not in matched_planned_ids]

    return {
        "week_start": week_start,
        "week_end": week_end,
        "planned": planned,
        "actual": actual,
        "matched": matched,
        "unmatched_planned": unmatched_planned,
        "unmatched_actual": unmatched_actual,
    }
