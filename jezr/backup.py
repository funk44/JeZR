import os
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path


def create_backup(
    base_dir: str,
    backup_dir: str,
    retain_weeks: int = 4,
    debug: bool = False,
) -> str:
    """Create a zip backup of athlete context, database, and plans.

    Args:
        base_dir: JeZR project root — all relative paths are resolved from here.
        backup_dir: Directory to write the zip file into.
        retain_weeks: Number of weeks of backups to keep locally.
        debug: If True, log skipped files to stderr.

    Returns:
        Absolute path to the created zip file.
    """
    base = Path(base_dir).resolve()
    out_dir = Path(backup_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    zip_path = out_dir / f"jezr_backup_{today}.zip"

    # Items to include
    items = [
        base / "context" / "athlete.json",
        base / "context" / "athlete.md",
        base / "data" / "jezr.db",
    ]
    plans_dir = base / "plans"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if item.exists():
                arcname = item.relative_to(base)
                zf.write(item, arcname)
                if debug:
                    print(f"  Added: {arcname}", file=sys.stderr)
            else:
                if debug:
                    print(f"  Skipped (not found): {item.relative_to(base)}", file=sys.stderr)

        if plans_dir.exists():
            for json_file in sorted(plans_dir.rglob("*.json")):
                arcname = json_file.relative_to(base)
                zf.write(json_file, arcname)
                if debug:
                    print(f"  Added: {arcname}", file=sys.stderr)
        else:
            if debug:
                print("  Skipped plans/ (directory not found)", file=sys.stderr)

    # Prune old backups
    cutoff = date.today() - timedelta(weeks=retain_weeks)
    pruned = 0
    for old_zip in sorted(out_dir.glob("jezr_backup_*.zip")):
        # Parse date from filename jezr_backup_YYYY-MM-DD.zip
        stem = old_zip.stem  # jezr_backup_YYYY-MM-DD
        date_part = stem[len("jezr_backup_"):]
        try:
            backup_date = date.fromisoformat(date_part)
        except ValueError:
            continue
        if backup_date < cutoff and old_zip != zip_path:
            old_zip.unlink()
            pruned += 1
            if debug:
                print(f"  Pruned: {old_zip.name}", file=sys.stderr)

    return str(zip_path), pruned


def run_backup(debug: bool = False) -> tuple[str, int]:
    """Read config from env vars and run create_backup().

    Reads:
        JEZR_BACKUP_DIR (default: ./backups)
        JEZR_BACKUP_RETAIN_WEEKS (default: 4)

    Returns:
        (zip_path, pruned_count)
    """
    base_dir = Path(__file__).parent.parent
    backup_dir = os.getenv("JEZR_BACKUP_DIR", str(base_dir / "backups"))
    try:
        retain_weeks = int(os.getenv("JEZR_BACKUP_RETAIN_WEEKS", "4"))
    except ValueError:
        retain_weeks = 4

    return create_backup(
        base_dir=str(base_dir),
        backup_dir=backup_dir,
        retain_weeks=retain_weeks,
        debug=debug,
    )
