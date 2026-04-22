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
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .fill_cleaner import clean_emsx_fills
from .fill_processor import process_fills
from .processing_config import ProcessingConfig as Config
from .raw_fills_db import RawFillsDB, compute_fills_hash

logger = logging.getLogger(__name__)


# -- Legacy: Excel -> raw_fills.db (kept for backward compatibility) --


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
        db = RawFillsDB()

    try:
        df_raw = pd.read_excel(file_path, engine="openpyxl")
        fills = df_raw.to_dict(orient="records")
        result["total_rows"] = len(fills)

        if not fills:
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Empty file: {file_path.name}")
            return result

        hash_value = compute_fills_hash(fills)
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
    """Ingest all FillFetch Excel files from the data directory (legacy)."""
    excel_dir = Path(excel_dir or Config.RAW_EXCEL_DIR)
    if db is None:
        db = RawFillsDB()

    files = sorted(excel_dir.glob("fills_*.xlsx"))
    if not files:
        logger.info(f"No Excel files found in {excel_dir}")
        return []

    logger.info(f"Found {len(files)} Excel files to check in {excel_dir}")
    results = []
    for file_path in files:
        result = ingest_excel_file(file_path, db=db)
        results.append(result)

    ingested = sum(1 for r in results if r["success"] and not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    failed = sum(1 for r in results if not r["success"])
    total_new = sum(r["new_rows"] for r in results)

    logger.info(
        f"Ingestion summary: {ingested} ingested, {skipped} skipped, "
        f"{failed} failed, {total_new} new rows total"
    )
    return results


# -- New: raw_fills.db -> clean -> process -> processed_fills.db (LAYER 1) --


def process_raw_fills_for_date(
    date_str: str,
    raw_db: Optional[RawFillsDB] = None,
    proc_db=None,
) -> Dict[str, Any]:
    """Process raw fills for a single date: clean -> enrich -> upsert processed.

    This is the LAYER 1 (Cleaning & Filtering) entry point:
        1. Read raw fills from raw_fills.db (by source_date or order_as_of_date)
        2. clean_emsx_fills() — filter DFD, derive times, normalize
        3. process_fills() — add algo/ccy/ticker/mkt_timestamp
        4. Split data into route_registry and processed_fills, then upsert
        5. Update ticker-date mapping

    Args:
        date_str: Date in YYYYMMDD format.
        raw_db: RawFillsDB instance (created if None).
        proc_db: ProcessedFillsDB instance (created if None).

    Returns:
        Dict with 'rows_processed', 'success', 'error'.
    """
    result: Dict[str, Any] = {
        "date": date_str,
        "success": False,
        "rows_processed": 0,
        "error": None,
    }

    if raw_db is None:
        raw_db = RawFillsDB()
    if proc_db is None:
        from .processed_fills_db import ProcessedFillsDB
        proc_db = ProcessedFillsDB()

    try:
        # 1. Read raw fills
        raw_df = raw_db.get_fills_for_date(date_str)
        if raw_df.empty:
            logger.info(f"  No raw fills for {date_str}, skipping")
            result["success"] = True
            return result

        # 2. Clean (filter DFD, derive times, normalize)
        cleaned_df = clean_emsx_fills(raw_df)
        if cleaned_df.empty:
            logger.info(f"  All fills filtered for {date_str}")
            result["success"] = True
            return result

        # 3. Process (add algo/ccy/ticker/mkt_timestamp)
        processed_df = process_fills(cleaned_df)
        if processed_df.empty:
            logger.warning(f"  Processing produced empty result for {date_str}")
            result["success"] = True
            return result

        # 4. Split into processed_fills fact table and route_registry dimension table, then upsert
        # Calculate route summaries for dimension table
        route_reg_df = processed_df.groupby(["OrderId", "RouteId"]).agg(
            equ_ticker=("equ_ticker", "first"),
            Exchange=("Exchange", "first"),
            ccy_ticker=("ccy_ticker", "first"),
            Side=("Side", "first"),
            count_fill=("FillId", "count"),
            count_broker=("Broker", "nunique"),
            count_algo=("algo", "nunique"),
            count_trader=("TraderName", "nunique"),
        ).reset_index()

        # Wrap all DB writes in a single transaction for atomicity:
        # if any step fails, all changes are rolled back together.
        txn_conn = proc_db._get_admin_conn()
        try:
            proc_db.upsert_route_registry(route_reg_df, conn=txn_conn)
            proc_db.upsert_processed_fills(processed_df, conn=txn_conn)
            proc_db.update_ticker_date_mapping(processed_df, conn=txn_conn)
            proc_db.update_ticker_registries(processed_df, conn=txn_conn)

            # 5. Mark as processed (inside same transaction)
            proc_db.mark_date_processed(
                date_str, stage="processed", row_count=len(processed_df),
                conn=txn_conn,
            )
            txn_conn.commit()
        except Exception:
            txn_conn.rollback()
            raise
        finally:
            txn_conn.close()

        result["rows_processed"] = len(processed_df)
        result["success"] = True
        logger.info(f"  Processed {date_str}: {len(processed_df)} rows")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Error processing {date_str}: {e}")

    return result


def _extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD date string from a fills_YYYYMMDD.xlsx filename."""
    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) >= 2:
        date_part = parts[-1]
        if len(date_part) == 8 and date_part.isdigit():
            return date_part
    return None
