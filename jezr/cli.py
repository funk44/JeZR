import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path


ATHLETE_TEMPLATE_PATH = Path(__file__).parent.parent / "context" / "athlete.template.json"
ATHLETE_TEMPLATE_MD_PATH = Path(__file__).parent.parent / "context" / "athlete.template.md"
ATHLETE_PROFILE_PATH = Path(__file__).parent.parent / "context" / "athlete.json"
ATHLETE_NARRATIVE_PATH = Path(__file__).parent.parent / "context" / "athlete.md"
SAMPLE_PLAN_PATH = Path(__file__).parent.parent / "context" / "sample_plan.json"

def _load_templates() -> tuple:
    """Load athlete.template.json and athlete.template.md from context/.

    Raises SystemExit clearly if either file is missing.
    Returns (template_json_dict, template_md_str).
    """
    if not ATHLETE_TEMPLATE_PATH.exists():
        print(f"ERROR: Template not found: {ATHLETE_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    if not ATHLETE_TEMPLATE_MD_PATH.exists():
        print(f"ERROR: Template not found: {ATHLETE_TEMPLATE_MD_PATH}", file=sys.stderr)
        sys.exit(1)

    with ATHLETE_TEMPLATE_PATH.open(encoding="utf-8") as f:
        template_json = json.load(f)
    template_md = ATHLETE_TEMPLATE_MD_PATH.read_text(encoding="utf-8")

    return template_json, template_md


SETUP_PROMPT = """\
You are helping me create my athlete profile for JeZR, a training intelligence system.

I will paste in the athlete profile template below. Please ask me the relevant questions
to fill in each field, then output a completed athlete.json file I can save.

Focus on:
- My primary race goal and target time
- My current training phase and weekly volume
- My threshold pace (this drives all pace zones)
- Any injury history or risk factors
- My preferred training days and any constraints
- Nutrition, heat tolerance, and workout format preferences

Here is the template:

[paste context/athlete.template.json here]
"""


def _cmd_setup_import(args: argparse.Namespace, import_file: str) -> None:
    """Import branch of jezr setup --import <file>."""
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()

    from jezr.planner import import_athlete_profile

    source_path = Path(import_file)
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        print("ERROR: CLAUDE_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    source_text = source_path.read_text(encoding="utf-8")
    print(f"Importing athlete profile from: {source_path}")
    print("Analysing content and restructuring — this may take a moment...")
    print()

    template_json, template_md = _load_templates()

    try:
        result = import_athlete_profile(
            source_text=source_text,
            athlete_template_json=template_json,
            athlete_template_md=template_md,
            api_key=api_key,
            debug=args.debug,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Write athlete.json
    athlete_json_data = result["athlete_json"]
    with ATHLETE_PROFILE_PATH.open("w", encoding="utf-8") as f:
        json.dump(athlete_json_data, f, indent=2)
    print(f"✓ athlete.json written to {ATHLETE_PROFILE_PATH}")

    # Write athlete.md
    athlete_md_text = result["athlete_md"]
    ATHLETE_NARRATIVE_PATH.write_text(athlete_md_text, encoding="utf-8")
    print(f"✓ athlete.md written to {ATHLETE_NARRATIVE_PATH}")
    print()

    # Report gaps
    gaps = result.get("gaps", [])
    if gaps:
        print("Gaps identified (fields to fill in manually):")
        for gap in gaps:
            print(f"  - {gap}")
    else:
        print("No gaps identified — profile looks complete.")
    print()

    # Validate athlete.json against template keys
    required_keys = {k for k in template_json if not k.startswith("_")}
    missing = required_keys - set(athlete_json_data.keys())
    if missing:
        print(f"WARNING: athlete.json is missing template fields: {', '.join(sorted(missing))}")
        print()

    print("Run 'jezr profile' to review your profile.")
    print()
    cmd_profile(args)


def cmd_setup(args: argparse.Namespace) -> None:
    import_file = getattr(args, "import_file", None)

    if import_file:
        _cmd_setup_import(args, import_file)
        return

    print("=" * 60)
    print("JeZR — Athlete Profile Setup")
    print("=" * 60)
    print()
    print("Copy the prompt below and paste it into your AI assistant.")
    print("Save the output as context/athlete.json, then return here.")
    print()
    print("-" * 60)
    print(SETUP_PROMPT)
    print("-" * 60)
    print()
    input("Press Enter once you have saved context/athlete.json ...")
    print()

    if not ATHLETE_PROFILE_PATH.exists():
        print("ERROR: context/athlete.json not found. Please save the file and try again.")
        sys.exit(1)

    try:
        with ATHLETE_PROFILE_PATH.open(encoding="utf-8") as f:
            profile = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"ERROR: context/athlete.json is not valid JSON: {exc}")
        sys.exit(1)

    if not ATHLETE_TEMPLATE_PATH.exists():
        print("WARNING: athlete.template.json not found, skipping schema validation.")
    else:
        with ATHLETE_TEMPLATE_PATH.open(encoding="utf-8") as f:
            template = json.load(f)

        required_keys = {k for k in template if not k.startswith("_")}
        missing = required_keys - set(profile.keys())
        if missing:
            print(f"WARNING: athlete.json is missing fields: {', '.join(sorted(missing))}")
        else:
            print("athlete.json validated successfully.")

    print()
    print("Setup complete. Run 'jezr profile' to review your profile.")
    print()

    # Phase 2: OpenClaw wiring
    _setup_openclaw()


_HEARTBEAT_BLOCK = """\

# JeZR
## Weekly review and backup (Sunday 9pm)
- schedule: every Sunday at 21:00
- run: {jezr_cmd} review
- run: {jezr_cmd} backup

## Poller keepalive (every 5 minutes)
- schedule: every 5 minutes
- check_process: {jezr_cmd} poll
- start_if_stopped: {jezr_cmd} poll
"""

_AGENT_BLOCK = """\

# JeZR
## Training plan approval
If the user sends a message that is exactly "YES" after receiving a training plan:
- run: {jezr_cmd} upload --planned data/pending_plan.json
- reply with the result

If the user sends any other reply after receiving a training plan:
- run: {jezr_cmd} review --feedback "{{message}}"
- send the revised plan for approval
"""

_JEZR_MARKER = "# JeZR"


def _setup_openclaw() -> None:
    """Phase 2 of setup: auto-wire JeZR blocks into OpenClaw HEARTBEAT.md and AGENT.md."""
    answer = input("Do you want to configure OpenClaw integration now? (yes/no): ").strip().lower()
    if answer not in ("yes", "y"):
        _print_openclaw_blocks_manual()
        return

    openclaw_dir_str = os.getenv("JEZR_OPENCLAW_DIR", "").strip()
    if not openclaw_dir_str:
        openclaw_dir_str = input(
            "Enter your OpenClaw directory path (e.g. /home/user/openclaw): "
        ).strip()

    openclaw_dir = Path(openclaw_dir_str).expanduser()
    heartbeat = openclaw_dir / "HEARTBEAT.md"
    agent = openclaw_dir / "AGENT.md"

    if not openclaw_dir.is_dir() or not heartbeat.exists() or not agent.exists():
        print(f"WARNING: OpenClaw directory not found or missing HEARTBEAT.md / AGENT.md at: {openclaw_dir}")
        print()
        _print_openclaw_blocks_manual()
        return

    jezr_cmd = shutil.which("jezr") or "jezr"

    heartbeat_content = heartbeat.read_text(encoding="utf-8")
    if _JEZR_MARKER in heartbeat_content:
        print("HEARTBEAT.md already contains JeZR configuration — skipping.")
    else:
        heartbeat.write_text(
            heartbeat_content + _HEARTBEAT_BLOCK.format(jezr_cmd=jezr_cmd),
            encoding="utf-8",
        )
        print("HEARTBEAT.md updated.")

    agent_content = agent.read_text(encoding="utf-8")
    if _JEZR_MARKER in agent_content:
        print("AGENT.md already contains JeZR configuration — skipping.")
    else:
        agent.write_text(
            agent_content + _AGENT_BLOCK.format(jezr_cmd=jezr_cmd),
            encoding="utf-8",
        )
        print("AGENT.md updated.")

    if shutil.which("jezr") is None:
        print()
        print("WARNING: 'jezr' not found on PATH. Ensure it is installed and accessible.")
        print("  The blocks above use 'jezr' — update them if your install path differs.")

    print()
    print("OpenClaw is now configured for JeZR.")
    print("See docs/openclaw.md for next steps.")


def _print_openclaw_blocks_manual() -> None:
    """Print HEARTBEAT and AGENT blocks to stdout for manual installation."""
    jezr_cmd = shutil.which("jezr") or "jezr"
    print()
    print("Add the following block to your OpenClaw HEARTBEAT.md:")
    print("-" * 60)
    print(_HEARTBEAT_BLOCK.format(jezr_cmd=jezr_cmd))
    print("-" * 60)
    print()
    print("Add the following block to your OpenClaw AGENT.md:")
    print("-" * 60)
    print(_AGENT_BLOCK.format(jezr_cmd=jezr_cmd))
    print("-" * 60)
    print()
    print("See docs/openclaw.md for detailed instructions.")


def cmd_profile(args: argparse.Namespace) -> None:
    if not ATHLETE_PROFILE_PATH.exists():
        print("WARNING: context/athlete.json not found.")
        print("Run 'jezr setup' to create your athlete profile.")
        return

    try:
        with ATHLETE_PROFILE_PATH.open(encoding="utf-8") as f:
            profile = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"ERROR: context/athlete.json is not valid JSON: {exc}")
        sys.exit(1)

    last_reviewed_str = profile.get("last_reviewed", "")
    if last_reviewed_str and last_reviewed_str != "YYYY-MM-DD":
        try:
            last_reviewed = date.fromisoformat(last_reviewed_str)
            days_since = (date.today() - last_reviewed).days
            if days_since > 90:
                print(f"WARNING: Athlete profile was last reviewed {days_since} days ago.")
                print("Consider updating it at the start of each training block.")
                print()
        except ValueError:
            pass

    print("=" * 60)
    print("Athlete Profile")
    print("=" * 60)

    def _show(label: str, value: object) -> None:
        if value and value != "YYYY-MM-DD":
            print(f"  {label}: {value}")

    _show("Name", profile.get("name"))
    _show("Age", profile.get("age"))
    _show("Last reviewed", profile.get("last_reviewed"))

    goals = profile.get("goals") or {}
    primary = goals.get("primary") or {}
    if primary:
        print()
        print("  Primary goal:")
        _show("    Race", primary.get("race"))
        _show("    Date", primary.get("date"))
        _show("    Distance", primary.get("distance"))
        _show("    Target time", primary.get("target_time"))
    _show("  Long-term goal", goals.get("long_term"))

    block = profile.get("current_block") or {}
    if block:
        print()
        print("  Current block:")
        _show("    Phase", block.get("phase"))
        _show("    Weekly volume (km)", block.get("weekly_volume_km"))
        _show("    Longest run (km)", block.get("longest_run_km"))

    _show("  Threshold pace/km", profile.get("threshold_pace_per_km"))

    paces = profile.get("pace_conventions") or {}
    if any(v for k, v in paces.items() if not k.startswith("_")):
        print()
        print("  Pace conventions (% of threshold):")
        for zone, value in paces.items():
            if not zone.startswith("_"):
                print(f"    {zone}: {value}%")

    injuries = profile.get("injury_history") or []
    if injuries:
        print()
        print("  Injury history:")
        for item in injuries:
            print(f"    - {item}")

    flags = profile.get("risk_flags") or []
    if flags:
        print()
        print("  Risk flags:")
        for flag in flags:
            print(f"    - {flag}")

    training_days = profile.get("preferred_training_days")
    if training_days:
        print()
        if isinstance(training_days, dict):
            print("  Preferred training days:")
            max_len = max(len(day.title()) for day in training_days)
            for day, desc in training_days.items():
                label = day.title()
                print(f"    {label:<{max_len}}  {desc}")
        else:
            print(f"  Preferred training days: {training_days}")

    fuelling = profile.get("fuelling")
    if fuelling:
        print()
        if isinstance(fuelling, dict):
            print("  Fuelling:")
            max_len = max(len(k.replace("_", " ").title()) for k in fuelling)
            for key, val in fuelling.items():
                label = key.replace("_", " ").title()
                print(f"    {label:<{max_len}}  {val}")
        else:
            print(f"  Fuelling: {fuelling}")

    _show("  Heat tolerance", profile.get("heat_tolerance"))
    _show("  Notes", profile.get("notes"))


def cmd_log(args: argparse.Namespace) -> None:
    from jezr import db as db_mod

    db_path = os.getenv("JEZR_DB_PATH", "./data/jezr.db")
    if not Path(db_path).exists():
        print("No log database found. Run the poller or a review first.")
        return

    n = getattr(args, "n", 50)
    level = getattr(args, "level", None)
    source = getattr(args, "source", None)
    debug = getattr(args, "debug", False)

    conn = db_mod.get_connection(db_path)
    try:
        entries = db_mod.get_log_entries(conn, n=n, level=level, source=source)
    finally:
        conn.close()

    if not entries:
        print("No log entries found.")
        return

    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120

    # Column widths: timestamp(19) level(7) source(8) event(16) — rest is message
    fixed = 19 + 1 + 7 + 1 + 8 + 1 + 16 + 2
    msg_width = max(20, term_width - fixed)

    for entry in entries:
        ts = entry.get("created_at", "")[:19].replace("T", " ")
        lvl = (entry.get("level") or "").ljust(7)
        src = (entry.get("source") or "").ljust(8)
        evt = (entry.get("event") or "").ljust(16)
        msg = entry.get("message") or ""
        if len(msg) > msg_width:
            msg = msg[:msg_width - 1] + "…"
        print(f"{ts}  {lvl}  {src}  {evt}  {msg}")

        if debug and entry.get("extra_json"):
            try:
                import json as _json
                extra = _json.loads(entry["extra_json"])
                tb = extra.get("traceback")
                if tb:
                    for line in tb.rstrip().splitlines():
                        print(f"    {line}")
            except Exception:
                pass


def cmd_backup(args: argparse.Namespace) -> None:
    from jezr.backup import run_backup

    zip_path, pruned = run_backup(debug=args.debug)
    print(f"Backup created: {zip_path}")
    retain = int(os.getenv("JEZR_BACKUP_RETAIN_WEEKS", "4"))
    print(f"Pruned {pruned} old backup(s) (keeping last {retain} weeks)")


def cmd_poll(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()

    from jezr.config import load_intervals_env, load_claude_env
    from jezr.intervals_client import IntervalsClient
    from jezr.notifier import get_notifier
    from jezr.poller import run_poller

    env = load_intervals_env()
    claude_env = load_claude_env()
    db_path = os.getenv("JEZR_DB_PATH", "./data/jezr.db")
    interval = getattr(args, "interval", 300)

    athlete_context = {}
    athlete_narrative = ""
    if ATHLETE_PROFILE_PATH.exists():
        with ATHLETE_PROFILE_PATH.open(encoding="utf-8") as f:
            athlete_context = json.load(f)
    if ATHLETE_NARRATIVE_PATH.exists():
        athlete_narrative = ATHLETE_NARRATIVE_PATH.read_text(encoding="utf-8")

    print("Poller started. Press Ctrl+C to stop.")
    client = IntervalsClient(api_key=env.api_key, athlete_id=env.athlete_id)
    notifier = get_notifier()
    try:
        run_poller(
            db_path=db_path,
            intervals_client=client,
            notifier=notifier,
            api_key=claude_env.api_key,
            athlete_context=athlete_context,
            athlete_narrative=athlete_narrative,
            poll_interval_seconds=interval,
            debug=args.debug,
        )
    finally:
        client.close()


def cmd_review(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()

    from jezr.config import load_claude_env
    from jezr.notifier import get_notifier
    from jezr.review import run_weekly_review, run_week_to_date_summary, run_feedback_revision

    if not ATHLETE_PROFILE_PATH.exists():
        print("ERROR: context/athlete.json not found. Run 'jezr setup' first.")
        sys.exit(1)

    with ATHLETE_PROFILE_PATH.open(encoding="utf-8") as f:
        athlete_context = json.load(f)

    athlete_narrative = ""
    if ATHLETE_NARRATIVE_PATH.exists():
        athlete_narrative = ATHLETE_NARRATIVE_PATH.read_text(encoding="utf-8")

    claude_env = load_claude_env()
    db_path = os.getenv("JEZR_DB_PATH", "./data/jezr.db")
    notifier = get_notifier()

    feedback = getattr(args, "feedback", None)
    week_to_date = getattr(args, "week_to_date", False)

    if feedback:
        sample_plan: list = []
        if SAMPLE_PLAN_PATH.exists():
            with SAMPLE_PLAN_PATH.open(encoding="utf-8") as f:
                sample_plan = json.load(f).get("workouts", [])

        result = run_feedback_revision(
            feedback=feedback,
            db_path=db_path,
            athlete_context=athlete_context,
            athlete_narrative=athlete_narrative,
            sample_plan=sample_plan,
            notifier=notifier,
            api_key=claude_env.api_key,
            debug=args.debug,
        )
        print("Revised plan sent.")
        if result["schema_errors"]:
            print(f"  Schema errors: {len(result['schema_errors'])}")
        if result["sense_check_flags"]:
            print(f"  Sense check flags: {len(result['sense_check_flags'])}")
        print(f"  Pending plan saved to: {result['pending_plan_path']}")
        return

    if week_to_date:
        summary = run_week_to_date_summary(
            db_path=db_path,
            athlete_context=athlete_context,
            athlete_narrative=athlete_narrative,
            notifier=notifier,
            api_key=claude_env.api_key,
            debug=args.debug,
        )
        print(f"Week-to-date summary sent ({len(summary)} chars).")
        return

    sample_plan = []
    if SAMPLE_PLAN_PATH.exists():
        with SAMPLE_PLAN_PATH.open(encoding="utf-8") as f:
            sample_plan = json.load(f).get("workouts", [])

    result = run_weekly_review(
        db_path=db_path,
        athlete_context=athlete_context,
        athlete_narrative=athlete_narrative,
        sample_plan=sample_plan,
        notifier=notifier,
        api_key=claude_env.api_key,
        debug=args.debug,
    )

    print(f"Review sent for week of {result['week_start']}.")
    if result["schema_errors"]:
        print(f"  Schema errors in proposed plan: {len(result['schema_errors'])}")
    if result["sense_check_flags"]:
        print(f"  Sense check flags: {len(result['sense_check_flags'])}")
    print(f"  Pending plan saved to: {result['pending_plan_path']}")
    print(f"  To upload: jezr upload --planned {result['pending_plan_path']}")


def _load_workouts_from_file(path: str) -> list:
    plan_file = Path(path)
    if not plan_file.exists():
        print(f"ERROR: File not found: {plan_file}", file=sys.stderr)
        sys.exit(1)
    with plan_file.open(encoding="utf-8") as f:
        plan_data = json.load(f)
    return plan_data if isinstance(plan_data, list) else plan_data.get("workouts", [])


def _run_validate(
    workouts: list,
    skip_sense_check: bool = False,
    debug: bool = False,
) -> bool:
    """Validate workouts and print results. Returns True if schema passes."""
    from jezr.validator import validate_plan_schema, sense_check_plan

    # Stage 1: hard schema check
    errors = validate_plan_schema(workouts)
    for workout in workouts:
        status = "FAIL" if any(workout.get("name", "") in e for e in errors) else "OK"
        print(f"  {status}  {workout.get('date', '?')}  {workout.get('name', '?')}")

    if errors:
        print(f"\nValidation FAILED ({len(errors)} error(s)):")
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return False

    print(f"\nSchema validation passed. {len(workouts)} workout(s) OK.")

    # Stage 2: AI sense check (advisory)
    if skip_sense_check:
        print("(Sense check skipped.)")
        return True

    api_key = os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        print("(Sense check skipped — CLAUDE_API_KEY not set.)")
        return True

    print("Running sense check via Claude API...")
    flags = sense_check_plan(
        workouts=workouts,
        athlete_context=_load_athlete_context(),
        athlete_narrative="",
        previous_week_summary=None,
        api_key=api_key,
        debug=debug,
    )
    if flags:
        print(f"\nSense check flags ({len(flags)}):")
        for flag in flags:
            print(f"  ⚠  {flag}")
    else:
        print("Sense check passed — no concerns.")

    return True  # Sense check flags are advisory; schema pass is what matters


def _load_athlete_context() -> dict:
    if ATHLETE_PROFILE_PATH.exists():
        try:
            with ATHLETE_PROFILE_PATH.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def cmd_upload(args: argparse.Namespace) -> None:
    workouts = _load_workouts_from_file(args.planned)

    validate_only = getattr(args, "validate_only", False)
    if validate_only:
        ok = _run_validate(workouts, skip_sense_check=True, debug=args.debug)
        sys.exit(0 if ok else 1)

    from dotenv import load_dotenv  # type: ignore
    load_dotenv()

    # Schema validation only — sense check already ran during jezr review
    ok = _run_validate(workouts, skip_sense_check=True, debug=args.debug)
    if not ok:
        sys.exit(1)

    from jezr.config import load_intervals_env
    from jezr.intervals_client import IntervalsClient
    from jezr.upload import upload_plan

    env = load_intervals_env()
    db_path = os.getenv("JEZR_DB_PATH", "./data/jezr.db")
    plans_dir = os.getenv("PLANS_DIR", "./plans")
    client = IntervalsClient(api_key=env.api_key, athlete_id=env.athlete_id)
    try:
        result = upload_plan(
            workouts=workouts,
            db_path=db_path,
            intervals_client=client,
            plans_dir=plans_dir,
            adhoc=args.adhoc,
            debug=args.debug,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()

    print(f"Uploaded:      {result['uploaded']} workout(s)")
    print(f"IDs matched:   {result['ids_matched']}")
    print(f"IDs missing:   {len(result['ids_missing'])}")
    if result["ids_missing"]:
        for eid in result["ids_missing"]:
            print(f"  - {eid}")
    print(f"Skipped:       {result['skipped_non_run']} non-Run workout(s)")
    if result["archived_to"]:
        print(f"Archived to:   {result['archived_to']}")


def cmd_validate(args: argparse.Namespace) -> None:
    workouts = _load_workouts_from_file(args.planned)
    skip_sense_check = getattr(args, "skip_sense_check", False)
    ok = _run_validate(workouts, skip_sense_check=skip_sense_check, debug=args.debug)
    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jezr",
        description="JeZR — training intelligence for endurance athletes",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    setup_parser = subparsers.add_parser("setup", help="Generate athlete profile via AI prompt")
    setup_parser.add_argument(
        "--import", dest="import_file", metavar="FILE",
        help="Import athlete profile from existing text or markdown file",
    )

    subparsers.add_parser("profile", help="Display athlete profile summary")

    subparsers.add_parser("backup", help="Create a backup zip of athlete context, database, and plans")

    log_parser = subparsers.add_parser("log", help="Show recent log entries")
    log_parser.add_argument("--n", type=int, default=50, metavar="N",
                            help="Number of entries to show (default: 50)")
    log_parser.add_argument("--level", metavar="LEVEL",
                            help="Filter by level: INFO, WARNING, ERROR")
    log_parser.add_argument("--source", metavar="SOURCE",
                            help="Filter by source: poller, review, upload, backup")

    poll_parser = subparsers.add_parser("poll", help="Start the activity poller (runs until interrupted)")
    poll_parser.add_argument(
        "--interval", type=int, default=300, metavar="SECONDS",
        help="Poll interval in seconds (default: 300)",
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Generate weekly review and proposed plan (default: previous week)",
    )
    review_parser.add_argument(
        "--week-to-date", action="store_true", dest="week_to_date",
        help="Generate a mid-week check-in summary instead of the full weekly review",
    )
    review_parser.add_argument(
        "--feedback", metavar="TEXT",
        help="Revise the pending plan based on athlete feedback and re-send for approval",
    )

    upload_parser = subparsers.add_parser("upload", help="Validate and upload a plan to Intervals.icu")
    upload_parser.add_argument("--planned", required=True, metavar="FILE", help="Plan JSON file to upload")
    upload_parser.add_argument("--adhoc", action="store_true", help="Skip archiving the plan")
    upload_parser.add_argument("--validate-only", action="store_true", dest="validate_only", help="Validate without uploading")

    validate_parser = subparsers.add_parser("validate", help="Validate a plan JSON file without uploading")
    validate_parser.add_argument("--planned", required=True, metavar="FILE", help="Plan JSON file to validate")
    validate_parser.add_argument("--skip-sense-check", action="store_true", dest="skip_sense_check", help="Skip AI sense check")

    args = parser.parse_args()

    dispatch = {
        "setup": cmd_setup,
        "profile": cmd_profile,
        "log": cmd_log,
        "backup": cmd_backup,
        "poll": cmd_poll,
        "review": cmd_review,
        "upload": cmd_upload,
        "validate": cmd_validate,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
