"""
Sync CostView/data/macro_event_dict.json → ref_macro_event_dict table.

Idempotent (UPSERT). Run after editing the json:
    python -m CostView.src.regime.sync_macro_event_dict
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from CostView.src.regime.schema import connect, ensure_schema_current, REGIME_DB_PATH

_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]
DEFAULT_JSON_PATH = _COSTVIEW_ROOT / "data" / "macro_event_dict.json"

_VALID_SEVERITY = {"low", "medium", "high"}


def sync(json_path: Path = DEFAULT_JSON_PATH, db_path: Path = REGIME_DB_PATH) -> int:
    ensure_schema_current(db_path)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    events = raw.get("events", {})
    rows = []
    for event_type, m in events.items():
        sev = m["default_severity"]
        if sev not in _VALID_SEVERITY:
            raise ValueError(f"event_type={event_type}: bad default_severity={sev!r}")
        win = int(m["default_window_days"])
        if win < 0:
            raise ValueError(f"event_type={event_type}: default_window_days must be >= 0")
        rows.append((event_type, sev, win, m["description"]))

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """
            INSERT INTO ref_macro_event_dict (event_type, default_severity, default_window_days, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_type) DO UPDATE SET
                default_severity    = excluded.default_severity,
                default_window_days = excluded.default_window_days,
                description         = excluded.description
            """,
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync macro_event_dict.json → ref_macro_event_dict")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--db", type=Path, default=REGIME_DB_PATH)
    args = parser.parse_args(argv)
    n = sync(args.json, args.db)
    print(f"[sync_macro_event_dict] upserted {n} event types from {args.json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
