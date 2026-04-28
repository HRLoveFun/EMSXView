"""
Sync CostView/data/market_mapping.json → ref_market_mapping table.

Idempotent (UPSERT). Run after editing market_mapping.json:
    python -m CostView.src.regime.sync_market_mapping
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Tuple

from CostView.src.regime.schema import connect, ensure_schema_current, REGIME_DB_PATH

_THIS = Path(__file__).resolve()
_COSTVIEW_ROOT = _THIS.parents[2]
DEFAULT_JSON_PATH = _COSTVIEW_ROOT / "data" / "market_mapping.json"


def _split_lunch(lunch) -> Tuple[str | None, str | None]:
    """Return (start, end) HH:MM strings, or (None, None) if no lunch."""
    if lunch is None:
        return (None, None)
    if isinstance(lunch, list) and len(lunch) == 2:
        return (str(lunch[0]), str(lunch[1]))
    raise ValueError(f"Bad lunch field: {lunch!r}; expected null or [HH:MM, HH:MM]")


def _validate_hhmm(value: str, field: str, market: str) -> None:
    if not (isinstance(value, str) and len(value) == 5 and value[2] == ":"
            and value[:2].isdigit() and value[3:].isdigit()):
        raise ValueError(f"Market {market}: bad {field}={value!r}; expected 'HH:MM'")


def sync(json_path: Path = DEFAULT_JSON_PATH, db_path: Path = REGIME_DB_PATH) -> int:
    """Sync json → ref_market_mapping. Returns number of rows upserted."""
    ensure_schema_current(db_path)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    schema_meta = raw.pop("_schema", {})
    source_version = schema_meta.get("version", "unknown")
    synced_at = dt.datetime.now().isoformat(timespec="seconds")

    rows = []
    for market_code, m in raw.items():
        session = m["session"]
        _validate_hhmm(session["open"], "session.open", market_code)
        _validate_hhmm(session["close"], "session.close", market_code)
        _validate_hhmm(session["closing_auction_start"], "session.closing_auction_start", market_code)
        lunch_start, lunch_end = _split_lunch(session.get("lunch"))
        rows.append((
            market_code,
            m["description"],
            m["currency"],
            m.get("vol_index"),
            m["benchmark"],
            session["open"],
            session["close"],
            lunch_start,
            lunch_end,
            session["closing_auction_start"],
            source_version,
            synced_at,
        ))

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """
            INSERT INTO ref_market_mapping (
                market_code, description, currency, vol_index, benchmark,
                session_open, session_close, lunch_start, lunch_end,
                closing_auction_start, source_file_version, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_code) DO UPDATE SET
                description           = excluded.description,
                currency              = excluded.currency,
                vol_index             = excluded.vol_index,
                benchmark             = excluded.benchmark,
                session_open          = excluded.session_open,
                session_close         = excluded.session_close,
                lunch_start           = excluded.lunch_start,
                lunch_end             = excluded.lunch_end,
                closing_auction_start = excluded.closing_auction_start,
                source_file_version   = excluded.source_file_version,
                synced_at             = excluded.synced_at
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
    parser = argparse.ArgumentParser(description="Sync market_mapping.json → ref_market_mapping")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--db", type=Path, default=REGIME_DB_PATH)
    args = parser.parse_args(argv)

    n = sync(args.json, args.db)
    print(f"[sync_market_mapping] upserted {n} markets from {args.json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
