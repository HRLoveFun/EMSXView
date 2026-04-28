"""
Validate CostView/data/macro_calendar.csv before sync.

Reports row-level errors (with file line numbers) for:
  - missing required fields
  - bad date format (must be YYYY-MM-DD, real calendar date)
  - market_code not in ref_market_mapping
  - event_type not in ref_macro_event_dict
  - severity not in {low, medium, high} (when provided)
  - window_days negative or non-integer (when provided)
  - duplicate (event_date, market_code, event_type)

Exit code: 0 if clean, 1 if any errors. Prints all errors before exiting.

Usage:
    python -m CostView.src.regime.validate_macro_calendar
    python -m CostView.src.regime.validate_macro_calendar --csv path/to/file.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple

from CostView.src.regime.schema import connect, ensure_schema_current, REGIME_DB_PATH

_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]
DEFAULT_CSV_PATH = _COSTVIEW_ROOT / "data" / "macro_calendar.csv"

REQUIRED_COLUMNS = ["event_date", "market_code", "event_type", "severity",
                    "window_days", "description"]
_VALID_SEVERITY = {"low", "medium", "high"}


def _load_ref_sets(db_path: Path) -> Tuple[Set[str], Set[str]]:
    """Return (markets, event_types) currently in regime.db ref tables."""
    conn = connect(db_path)
    try:
        markets = {row[0] for row in conn.execute("SELECT market_code FROM ref_market_mapping")}
        events = {row[0] for row in conn.execute("SELECT event_type FROM ref_macro_event_dict")}
    finally:
        conn.close()
    return markets, events


def _read_version(csv_path: Path) -> str:
    """Extract `version: <x>` from leading comment block, or 'unknown'."""
    with csv_path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s.startswith("#"):
                break
            if "version:" in s:
                return s.split("version:", 1)[1].strip()
    return "unknown"


def _iter_data_rows(csv_path: Path) -> Iterable[Tuple[int, dict]]:
    """Yield (file_line_number, row_dict) skipping comment lines and the header."""
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        # Strip leading comment lines first; keep track of file line number.
        non_comment_lines: List[Tuple[int, str]] = []
        for lineno, raw in enumerate(f, start=1):
            if raw.startswith("#"):
                continue
            non_comment_lines.append((lineno, raw))
    if not non_comment_lines:
        return
    header_lineno, header_raw = non_comment_lines[0]
    reader = csv.DictReader([line for _, line in non_comment_lines])
    line_iter = iter(non_comment_lines[1:])
    for row in reader:
        file_lineno, _raw = next(line_iter)
        yield file_lineno, row


def validate(csv_path: Path = DEFAULT_CSV_PATH,
             db_path: Path = REGIME_DB_PATH) -> List[str]:
    """Return a list of error messages (empty = clean)."""
    errors: List[str] = []
    if not csv_path.exists():
        return [f"FILE NOT FOUND: {csv_path}"]

    ensure_schema_current(db_path)
    markets, events = _load_ref_sets(db_path)
    if not markets:
        errors.append("ref_market_mapping is empty — run sync_market_mapping first")
    if not events:
        errors.append("ref_macro_event_dict is empty — run sync_macro_event_dict first")
    if errors:
        return errors

    seen: Set[Tuple[str, str, str]] = set()
    saw_data = False

    # Header check
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        header_raw = None
        for raw in f:
            if not raw.startswith("#"):
                header_raw = raw.rstrip("\r\n")
                break
    if header_raw is None:
        return [f"{csv_path}: no header line found"]
    header_cols = [c.strip() for c in header_raw.split(",")]
    if header_cols != REQUIRED_COLUMNS:
        errors.append(
            f"{csv_path}: header mismatch.\n  expected: {REQUIRED_COLUMNS}\n  got:      {header_cols}"
        )
        return errors

    for lineno, row in _iter_data_rows(csv_path):
        saw_data = True
        prefix = f"{csv_path.name}:{lineno}"
        ed = (row.get("event_date") or "").strip()
        mc = (row.get("market_code") or "").strip()
        et = (row.get("event_type") or "").strip()
        sev = (row.get("severity") or "").strip()
        wd = (row.get("window_days") or "").strip()

        if not ed:
            errors.append(f"{prefix}: event_date is required")
        else:
            try:
                dt.date.fromisoformat(ed)
            except ValueError:
                errors.append(f"{prefix}: bad event_date={ed!r}; expected YYYY-MM-DD")
        if not mc:
            errors.append(f"{prefix}: market_code is required")
        elif mc not in markets:
            errors.append(f"{prefix}: unknown market_code={mc!r}; not in ref_market_mapping")
        if not et:
            errors.append(f"{prefix}: event_type is required")
        elif et not in events:
            errors.append(f"{prefix}: unknown event_type={et!r}; not in ref_macro_event_dict")
        if sev and sev not in _VALID_SEVERITY:
            errors.append(f"{prefix}: bad severity={sev!r}; must be one of {sorted(_VALID_SEVERITY)} or blank")
        if wd:
            try:
                if int(wd) < 0:
                    errors.append(f"{prefix}: window_days={wd!r} must be >= 0")
            except ValueError:
                errors.append(f"{prefix}: window_days={wd!r} must be integer or blank")

        key = (ed, mc, et)
        if key in seen:
            errors.append(f"{prefix}: duplicate (event_date, market_code, event_type)={key}")
        seen.add(key)

    if not saw_data:
        errors.append(f"{csv_path}: no data rows after header")

    return errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate macro_calendar.csv")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--db", type=Path, default=REGIME_DB_PATH)
    args = parser.parse_args(argv)

    errs = validate(args.csv, args.db)
    if errs:
        print(f"[validate_macro_calendar] {len(errs)} error(s):", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"[validate_macro_calendar] {args.csv.name} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
