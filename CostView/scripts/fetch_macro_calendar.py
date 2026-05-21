"""
Auto-fetch macro economic events from Bloomberg → ref_macro_event_calendar.

Covers 7 event types per project spec:
  - FOMC rate decisions               (US, FDTR Index)
  - US CPI YoY                        (US, CPI YOY Index)
  - US Non-Farm Payrolls              (US, NFP TCH Index)
  - ECB rate decisions                (EU, EURR002W Index)
  - BOJ policy rate                   (JP, BOJDTR Index)
  - UK CPI YoY                        (LN, UKRPCJYR Index)   [LN = UK in project conv]
  - Eurozone HICP YoY                 (EU, ECCPEMUY Index)

Method
------
For each (event_type, market_code, ticker), call:
  1) blp.bdh(ticker, 'ECO_RELEASE_DT', start, end)
     → historical release dates (values are YYYYMMDD floats)
  2) blp.bds(ticker, 'ECO_RELEASE_DT_LIST')
     → forward-looking scheduled release dates (values are YYYYMMDD strings)
Both sources are merged, de-duplicated, clamped to [start, end], and upserted
into ref_macro_event_calendar with severity/window_days from
ref_macro_event_dict.

Idempotent (INSERT OR IGNORE on PK (event_date, market_code, event_type)).

Run
---
    python -m CostView.scripts.fetch_macro_calendar --start 2025-09-01 --end 2026-12-31
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from DataPipeline.analysis.regime.schema import REGIME_DB_PATH

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EcoIndicator:
    event_type: str        # FK to ref_macro_event_dict.event_type
    market_code: str       # FK to ref_market_mapping.market_code
    ticker: str            # Bloomberg security identifier
    description: str


# Order matters only for log readability.
INDICATORS: tuple[EcoIndicator, ...] = (
    EcoIndicator("fomc", "US", "FDTR Index",      "FOMC rate decision (Fed Funds Target)"),
    EcoIndicator("cpi",  "US", "CPI YOY Index",   "US CPI YoY headline release"),
    EcoIndicator("nfp",  "US", "NFP TCH Index",   "US Non-Farm Payrolls release"),
    EcoIndicator("ecb",  "EU", "EURR002W Index",  "ECB Main Refi Rate decision"),
    EcoIndicator("boj",  "JP", "BOJDTR Index",    "BOJ Policy Rate decision"),
    EcoIndicator("cpi",  "LN", "UKRPCJYR Index",  "UK CPI YoY release"),
    EcoIndicator("cpi",  "EU", "ECCPEMUY Index",  "Eurozone HICP YoY release"),
)

SOURCE_VERSION_PREFIX = "macro.bbg_eco/"


def _import_xbbg():
    try:
        from xbbg import blp  # type: ignore
        return blp
    except ImportError:
        logger.error("xbbg not available; cannot fetch Bloomberg ECO calendar")
        return None


def _coerce_yyyymmdd(value) -> Optional[dt.date]:
    """Parse Bloomberg release-date encodings into a datetime.date.

    Accepts: float/int 20251017.0, str '20251017', str '2025-10-17', or pandas
    Timestamp. Returns None on failure.
    """
    import pandas as pd

    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            s = str(int(value))
        else:
            s = str(value).strip()
        if not s:
            return None
        if len(s) == 8 and s.isdigit():
            return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return pd.Timestamp(s).date()
    except (ValueError, TypeError):
        return None


def _fetch_release_dates(blp, ticker: str, start: dt.date, end: dt.date) -> List[dt.date]:
    """Return list of release dates for an ECO indicator within [start, end].

    Combines two sources:
      1) ``blp.bdh(ticker, 'ECO_RELEASE_DT', start, end)`` — historical
         release dates encoded as YYYYMMDD floats in the value column.
      2) ``blp.bds(ticker, 'ECO_RELEASE_DT_LIST')`` — forward-looking
         scheduled release dates as YYYYMMDD strings.

    Both sources are merged, de-duplicated, sorted ascending, and clamped to
    [start, end].
    """
    candidate_dates: set[dt.date] = set()
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    # Source 1: historical ECO_RELEASE_DT.
    try:
        df = blp.bdh(ticker, "ECO_RELEASE_DT", start_s, end_s)
    except Exception as e:
        logger.debug(f"  [{ticker}] bdh ECO_RELEASE_DT failed: {e}")
        df = None
    if df is not None and len(df) > 0:
        # Single-column DataFrame; iterate values.
        s = df.iloc[:, 0]
        for v in s.dropna().tolist():
            d = _coerce_yyyymmdd(v)
            if d is not None:
                candidate_dates.add(d)

    # Source 2: forward-looking ECO_RELEASE_DT_LIST.
    try:
        ds = blp.bds(ticker, "ECO_RELEASE_DT_LIST")
    except Exception as e:
        logger.debug(f"  [{ticker}] bds ECO_RELEASE_DT_LIST failed: {e}")
        ds = None
    if ds is not None and len(ds) > 0:
        # First column holds the date strings.
        s = ds.iloc[:, 0]
        for v in s.dropna().tolist():
            d = _coerce_yyyymmdd(v)
            if d is not None:
                candidate_dates.add(d)

    return sorted(d for d in candidate_dates if start <= d <= end)


def _load_event_dict(db_path: Path) -> dict[str, Tuple[str, int]]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT event_type, default_severity, default_window_days FROM ref_macro_event_dict"
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: (r[1], int(r[2])) for r in rows}


def _upsert_events(
    db_path: Path,
    indicator: EcoIndicator,
    dates: Iterable[dt.date],
    event_dict: dict[str, Tuple[str, int]],
    source_version: str,
) -> int:
    severity, window_days = event_dict.get(indicator.event_type, ("medium", 1))
    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = [
        (
            d.isoformat(),
            indicator.market_code,
            indicator.event_type,
            severity,
            window_days,
            f"{indicator.description} ({d.isoformat()})",
            source_version,
            now,
        )
        for d in dates
    ]
    if not rows:
        return 0
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executemany(
            """INSERT OR IGNORE INTO ref_macro_event_calendar
               (event_date, market_code, event_type, severity, window_days,
                description, source_file_version, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()


def fetch_and_sync(
    start: dt.date,
    end: dt.date,
    db_path: Path = REGIME_DB_PATH,
    indicators: tuple[EcoIndicator, ...] = INDICATORS,
    dry_run: bool = False,
) -> dict[str, int]:
    blp = _import_xbbg()
    if blp is None:
        return {}
    event_dict = _load_event_dict(db_path)
    source_version = f"{SOURCE_VERSION_PREFIX}{dt.date.today().isoformat()}/v1"

    summary: dict[str, int] = {}
    for ind in indicators:
        try:
            dates = _fetch_release_dates(blp, ind.ticker, start, end)
        except Exception as e:
            logger.warning(f"  [{ind.ticker}] fetch failed: {e}")
            summary[f"{ind.event_type}/{ind.market_code}"] = -1
            continue
        key = f"{ind.event_type}/{ind.market_code} ({ind.ticker})"
        if dry_run:
            logger.info(f"  {key}: {len(dates)} dates [dry-run]")
            summary[key] = len(dates)
            continue
        n = _upsert_events(db_path, ind, dates, event_dict, source_version)
        logger.info(f"  {key}: {len(dates)} dates fetched, {n} rows changed in DB")
        summary[key] = len(dates)
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="ISO YYYY-MM-DD (inclusive)")
    parser.add_argument("--end",   required=True, help="ISO YYYY-MM-DD (inclusive)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + log without DB writes")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        print(f"--end {end} earlier than --start {start}", file=sys.stderr)
        return 2

    summary = fetch_and_sync(start, end, dry_run=args.dry_run)
    if not summary:
        print("fetch_macro_calendar: no indicators processed", file=sys.stderr)
        return 1
    total = sum(v for v in summary.values() if v >= 0)
    print(f"fetch_macro_calendar: {total} release dates across {len(summary)} indicators "
          f"[{args.start}..{args.end}]")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
