"""
Fill Ingestion — bridge between raw fetched data and the processing pipeline.

Provides two modes:

    Mode 1 (DEPRECATED): Excel -> clean -> raw_fills.db
        ingest_excel_file() / ingest_all_excel_files()
        Reads pre-existing FillFetch Excel output files into raw_fills.db.
        **No longer needed** since fill_fetch.py writes directly to raw_fills.db
        via the Bloomberg API. Kept for backward compatibility with historical
        Excel archives.

    Mode 2 (ACTIVE): raw_fills.db -> clean -> process -> processed_fills.db
        process_raw_fills_for_date()
        LAYER 1 entry point: reads raw_fills from DB, runs cleaning + enrichment,
        upserts to processed_fills.db with a fixed 27-column schema.

"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

RawFillsDB = Any  # backward compat alias; was CostView/src/raw_fills_db.py

import pandas as pd

from DataPipeline.processing.fill_cleaner import clean_emsx_fills
from DataPipeline.processing.fill_processor import process_fills
from DataPipeline.config import Config
from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository
from DataPipeline.storage.facade import DatabaseFacade
from DataPipeline.storage.repositories.fetch_history import compute_data_hash

logger = logging.getLogger(__name__)

def _first_non_empty(series: pd.Series) -> Optional[str]:
    for value in series:
        if pd.isna(value) or value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            continue
        return text
    return None

def _weighted_average(frame: pd.DataFrame, value_col: str, weight_col: str) -> Optional[float]:
    if value_col not in frame.columns or weight_col not in frame.columns:
        return None
    values = pd.to_numeric(frame[value_col], errors="coerce")
    weights = pd.to_numeric(frame[weight_col], errors="coerce")
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return None
    total_weight = float(weights[valid].sum())
    if total_weight <= 0:
        return None
    return float((values[valid] * weights[valid]).sum() / total_weight)

def _first_last_event_time(group: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    candidates: list[str] = []
    for column in ("local_fill_datetime", "DateTimeOfFill"):
        if column not in group.columns:
            continue
        values = [
            str(value).strip()
            for value in group[column]
            if value is not None and not pd.isna(value) and str(value).strip()
        ]
        if values:
            candidates = values
            break
    if not candidates:
        return None, None
    return min(candidates), max(candidates)

def _build_execution_history_frames(
    processed_df: pd.DataFrame,
    route_reg_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    route_attrs = route_reg_df[["OrderId", "RouteId", "equ_ticker", "ccy_ticker", "Side"]].drop_duplicates()
    enriched_df = processed_df.merge(route_attrs, on=["OrderId", "RouteId"], how="left")

    refreshed_at = datetime.utcnow().isoformat(timespec="seconds")
    order_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["orders"])
    route_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["routes"])
    event_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["route_events"])

    order_records: list[dict[str, Any]] = []
    for (order_id, order_as_of_date), group in enriched_df.groupby(["OrderId", "order_as_of_date"], dropna=False, sort=False):
        first_fill_time, last_fill_time = _first_last_event_time(group)
        order_records.append(
            {
                "OrderId": str(order_id),
                "order_as_of_date": str(order_as_of_date),
                "equ_ticker": _first_non_empty(group.get("equ_ticker", pd.Series(dtype=object))),
                "ccy_ticker": _first_non_empty(group.get("ccy_ticker", pd.Series(dtype=object))),
                "Side": _first_non_empty(group.get("Side", pd.Series(dtype=object))),
                "Broker": _first_non_empty(group.get("Broker", pd.Series(dtype=object))),
                "algo": _first_non_empty(group.get("algo", pd.Series(dtype=object))),
                "TraderName": _first_non_empty(group.get("TraderName", pd.Series(dtype=object))),
                "Exchange": _first_non_empty(group.get("Exchange", pd.Series(dtype=object))),
                "route_count": int(group["RouteId"].astype(str).nunique()),
                "fill_count": int(group["FillId"].astype(str).nunique()),
                "total_fill_shares": pd.to_numeric(group.get("FillShares"), errors="coerce").sum(min_count=1),
                "order_amount": pd.to_numeric(group.get("Amount"), errors="coerce").max(),
                "average_fill_price": _weighted_average(group, "FillPrice", "FillShares"),
                "first_fill_time": first_fill_time,
                "last_fill_time": last_fill_time,
                "primary_source": Config.EXECUTION_HISTORY_SOURCE_POLICY["orders"][0],
                "source_priority": order_lineage,
                "refresh_strategy": Config.EXECUTION_HISTORY_REFRESH_POLICY["orders"],
                "source_refreshed_at": refreshed_at,
                "source_lineage": "processed_fills -> order_history",
            }
        )

    route_records: list[dict[str, Any]] = []
    for (order_id, route_id, order_as_of_date), group in enriched_df.groupby(["OrderId", "RouteId", "order_as_of_date"], dropna=False, sort=False):
        first_fill_time, last_fill_time = _first_last_event_time(group)
        route_records.append(
            {
                "OrderId": str(order_id),
                "RouteId": str(route_id),
                "order_as_of_date": str(order_as_of_date),
                "equ_ticker": _first_non_empty(group.get("equ_ticker", pd.Series(dtype=object))),
                "ccy_ticker": _first_non_empty(group.get("ccy_ticker", pd.Series(dtype=object))),
                "Side": _first_non_empty(group.get("Side", pd.Series(dtype=object))),
                "Broker": _first_non_empty(group.get("Broker", pd.Series(dtype=object))),
                "algo": _first_non_empty(group.get("algo", pd.Series(dtype=object))),
                "TraderName": _first_non_empty(group.get("TraderName", pd.Series(dtype=object))),
                "Exchange": _first_non_empty(group.get("Exchange", pd.Series(dtype=object))),
                "fill_count": int(group["FillId"].astype(str).nunique()),
                "total_fill_shares": pd.to_numeric(group.get("FillShares"), errors="coerce").sum(min_count=1),
                "order_amount": pd.to_numeric(group.get("Amount"), errors="coerce").max(),
                "route_shares": pd.to_numeric(group.get("RouteShares"), errors="coerce").max(),
                "average_fill_price": _weighted_average(group, "FillPrice", "FillShares"),
                "first_fill_time": first_fill_time,
                "last_fill_time": last_fill_time,
                "primary_source": Config.EXECUTION_HISTORY_SOURCE_POLICY["routes"][0],
                "source_priority": route_lineage,
                "refresh_strategy": Config.EXECUTION_HISTORY_REFRESH_POLICY["routes"],
                "source_refreshed_at": refreshed_at,
                "source_lineage": "processed_fills -> route_history",
            }
        )

    event_records: list[dict[str, Any]] = []
    for row in enriched_df.itertuples(index=False):
        row_map = row._asdict()
        order_id = str(row_map.get("OrderId"))
        route_id = str(row_map.get("RouteId"))
        fill_id = str(row_map.get("FillId"))
        order_as_of_date = str(row_map.get("order_as_of_date"))
        event_timestamp = row_map.get("local_fill_datetime") or row_map.get("DateTimeOfFill")
        event_records.append(
            {
                "event_id": f"fill:{order_id}:{route_id}:{fill_id}:{order_as_of_date}",
                "OrderId": order_id,
                "RouteId": route_id,
                "FillId": fill_id,
                "order_as_of_date": order_as_of_date,
                "event_timestamp": None if event_timestamp is None or pd.isna(event_timestamp) else str(event_timestamp),
                "event_type": "FILL",
                "event_source": Config.EXECUTION_HISTORY_SOURCE_POLICY["route_events"][0],
                "event_action": row_map.get("ExecType") or "FILL",
                "ExecType": row_map.get("ExecType"),
                "Broker": row_map.get("Broker"),
                "algo": row_map.get("algo"),
                "TraderName": row_map.get("TraderName"),
                "Exchange": row_map.get("Exchange"),
                "equ_ticker": row_map.get("equ_ticker"),
                "ccy_ticker": row_map.get("ccy_ticker"),
                "Side": row_map.get("Side"),
                "FillPrice": row_map.get("FillPrice"),
                "FillShares": row_map.get("FillShares"),
                "Amount": row_map.get("Amount"),
                "RouteShares": row_map.get("RouteShares"),
                "source_refreshed_at": refreshed_at,
                "refresh_strategy": Config.EXECUTION_HISTORY_REFRESH_POLICY["route_events"],
                "source_lineage": event_lineage,
            }
        )

    return (
        pd.DataFrame(order_records),
        pd.DataFrame(route_records),
        pd.DataFrame(event_records),
    )

# -- Legacy: Excel -> raw_fills.db (kept for backward compatibility) --

def _extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD date from filename like fills_20260408.xlsx."""
    if not filename:
        return None
    parts = Path(filename).stem.split("_")
    for p in parts:
        if p.isdigit() and len(p) == 8:
            return p
    return None

def ingest_excel_file(
    file_path: Path,
    db: Optional[RawFillsDB] = None,
) -> Dict[str, Any]:
    """Ingest a single FillFetch Excel file into raw_fills.db (legacy).

    Steps:
        1. Read Excel -> List[Dict]
        2. Compute hash for duplicate detection
        3. Check ingestion_log for prior ingestion with same date + hash
        4. Clean via clean_emsx_fills()
        5. Upsert into raw_fills table
        6. Record in ingestion_log
    """
    file_path = Path(file_path)
    result: Dict[str, Any] = {
        "file": str(file_path),
        "success": False,
        "skipped": False,
        "total_rows": 0,
        "new_rows": 0,
        "error": None,
    }

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    if db is None:
        db = DatabaseFacade().raw_db

    try:
        df_raw = pd.read_excel(file_path, engine="openpyxl")
        fills = df_raw.to_dict(orient="records")
        result["total_rows"] = len(fills)

        if not fills:
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Empty file: {file_path.name}")
            return result

        hash_value = compute_data_hash(fills)
        source_date = _extract_date_from_filename(file_path.name)

        if source_date and db.check_ingestion_duplicate(source_date, hash_value):
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Duplicate detected for {file_path.name} (date={source_date}), skipping")
            return result

        cleaned_df = clean_emsx_fills(fills)
        new_count = db.upsert_fills(cleaned_df)
        result["new_rows"] = new_count

        if source_date:
            db.add_ingestion_record(
                source_date=source_date,
                row_count=len(cleaned_df),
                new_row_count=new_count,
                hash_value=hash_value,
                source_file=file_path.name,
            )

        result["success"] = True
        logger.info(
            f"Ingested {file_path.name}: {len(cleaned_df)} rows "
            f"({new_count} new)"
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error ingesting {file_path.name}: {e}")

    return result

def ingest_all_excel_files(
    excel_dir: Optional[Path] = None,
    db: Optional[RawFillsDB] = None,
) -> List[Dict[str, Any]]:
    """Ingest all FillFetch Excel files from a directory (legacy)."""
    if excel_dir is None:
        excel_dir = Path(Config.DATA_DIR)
    else:
        excel_dir = Path(excel_dir)

    if db is None:
        db = DatabaseFacade().raw_db

    if not excel_dir.exists():
        logger.warning(f"Excel directory not found: {excel_dir}")
        return []

    files = sorted(excel_dir.glob("fills_*.xlsx"))
    if not files:
        logger.info(f"No FillFetch Excel files found in {excel_dir}")
        return []

    results = []
    for file_path in files:
        result = ingest_excel_file(file_path, db)
        results.append(result)

    return results

# -- Active: raw_fills.db -> processed_fills.db --

def process_raw_fills_for_date(
    date_str: str,
    db: Optional[DatabaseFacade] = None,
    raw_db: Optional[SqliteRawFillReadRepository] = None,
    skip_if_processed: bool = True,
) -> Dict[str, Any]:
    """Read raw fills for date, clean+process, upsert to processed_fills.db.

    This is the LAYER 1 entry point of the processing pipeline.

    Args:
        date_str: YYYYMMDD date string.
        db: DatabaseFacade facade (or None to create default).
        raw_db: RawFillsDB instance (or None to use db.raw_db).
        skip_if_processed: If True, skip dates that already have processed data.

    Returns:
        Dict with keys: date, success, rows_read, rows_cleaned, rows_processed,
        error (if any).
    """
    if db is None:
        db = DatabaseFacade()
    if raw_db is None:
        raw_db = SqliteRawFillReadRepository()

    result: Dict[str, Any] = {
        "date": date_str,
        "success": False,
        "rows_read": 0,
        "rows_cleaned": 0,
        "rows_processed": 0,
        "error": None,
    }

    try:
        # Step 1: Read raw fills
        raw_fills = raw_db.get_fills_for_date(date_str)
        if raw_fills is None or raw_fills.empty:
            logger.info(f"No raw fills found for {date_str}")
            result["success"] = True
            return result

        result["rows_read"] = len(raw_fills)

        # Step 2: Clean
        cleaned = clean_emsx_fills(raw_fills)
        result["rows_cleaned"] = len(cleaned)

        if cleaned.empty:
            logger.warning(f"All fills filtered out during cleaning for {date_str}")
            result["success"] = True
            return result

        # Step 3: Process (enrich)
        processed = process_fills(cleaned)
        result["rows_processed"] = len(processed)

        # Step 4: Upsert to processed_fills.db
        db.fills_write.upsert_processed_fills(processed)
        db.fills_write.upsert_route_registry(processed)
        db.fills_write.mark_date_processed(
            date_str=date_str, stage="processed",
            row_count=len(processed),
        )

        # Populate execution history tables
        route_reg_df = db.fills_write.get_route_registry_for_date(date_str)
        order_df, route_df, event_df = _build_execution_history_frames(processed, route_reg_df)
        db.fills_write.upsert_execution_history(order_df, route_df, event_df)

        result["success"] = True
        logger.info(
            f"Processed {date_str}: {len(processed)} rows "
            f"(from {len(raw_fills)} raw)"
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error processing {date_str}: {e}")

    return result
