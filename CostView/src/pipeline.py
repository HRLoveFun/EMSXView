"""
Pipeline Orchestrator — end-to-end EMSX fill data processing pipeline.

Coordinates all stages:
    1. Ingest raw Excel fills → raw_fills.db
    2. Process raw fills → processed_fills.db
    3. Aggregate (10s, 1min) → processed_fills.db
    4. Generate order labels → processed_fills.db
    5. (Optional) Fetch BDIB and integrate → processed_fills.db
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .fill_aggregator import generate_agg_fills_10s, generate_agg_fills_1min
from .fill_ingestion import ingest_all_excel_files
from .fill_processor import process_fills
from .order_label import generate_order_label_incremental
from .processed_fills_db import ProcessedFillsDB
from .processing_config import ProcessingConfig as Config
from .raw_fills_db import RawFillsDB

logger = logging.getLogger(__name__)


def run_ingest(excel_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Stage 1: Ingest all new Excel files into raw_fills.db."""
    logger.info("=" * 60)
    logger.info("STAGE 1: Ingest raw Excel fills → raw_fills.db")
    logger.info("=" * 60)
    Config.initialize_directories()

    raw_db = RawFillsDB()
    results = ingest_all_excel_files(excel_dir=excel_dir, db=raw_db)
    return results


def run_process(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Stage 2: Process raw fills → processed fills.

    If dates is None, processes all dates that haven't been processed yet.
    If force=True, reprocesses all dates.
    """
    logger.info("=" * 60)
    logger.info("STAGE 2: Process raw fills → processed_fills.db")
    logger.info("=" * 60)

    raw_db = RawFillsDB()
    proc_db = ProcessedFillsDB()

    # Determine which dates to process
    all_raw_dates = raw_db.get_all_dates()
    if not all_raw_dates:
        logger.info("No dates in raw_fills.db to process")
        return pd.DataFrame()

    if dates:
        target_dates = [d for d in dates if d in all_raw_dates]
    elif force:
        target_dates = all_raw_dates
    else:
        target_dates = proc_db.get_unprocessed_dates(all_raw_dates, stage="processed")

    if not target_dates:
        logger.info("All dates already processed")
        return pd.DataFrame()

    logger.info(f"Processing {len(target_dates)} dates: {target_dates}")

    all_processed = []
    for date_str in target_dates:
        try:
            logger.info(f"  Processing date {date_str}...")

            # Read raw fills for this date
            raw_df = raw_db.get_fills_for_date(date_str)
            if raw_df.empty:
                logger.info(f"  No raw fills for {date_str}, skipping")
                continue

            # Process
            processed_df = process_fills(raw_df)

            # Store processed fills
            proc_db.upsert_processed_fills(processed_df)
            proc_db.update_ticker_date_mapping(processed_df)

            # Mark date as processed
            proc_db.mark_date_processed(date_str, stage="processed", row_count=len(processed_df))

            all_processed.append(processed_df)
            logger.info(f"  Processed {date_str}: {len(processed_df)} rows")

        except Exception as e:
            logger.error(f"  Error processing date {date_str}: {e}")

    if all_processed:
        return pd.concat(all_processed, ignore_index=True)
    return pd.DataFrame()


def run_aggregate(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Stage 3: Generate 10s and 1min aggregations."""
    logger.info("=" * 60)
    logger.info("STAGE 3: Aggregate processed fills (10s + 1min)")
    logger.info("=" * 60)

    proc_db = ProcessedFillsDB()

    # Determine dates
    if dates:
        target_dates = dates
    elif force:
        target_dates = proc_db.get_processed_dates(stage="processed")
    else:
        processed_dates = proc_db.get_processed_dates(stage="processed")
        target_dates = proc_db.get_unprocessed_dates(processed_dates, stage="aggregated")

    if not target_dates:
        logger.info("No dates to aggregate")
        return

    logger.info(f"Aggregating {len(target_dates)} dates")

    for date_str in target_dates:
        try:
            processed_df = proc_db.get_processed_fills_for_date(date_str)
            if processed_df.empty:
                continue

            # 10-second aggregation
            agg_10s = generate_agg_fills_10s(processed_df)
            if not agg_10s.empty:
                proc_db.upsert_agg_fills(agg_10s)

            # 1-minute aggregation
            agg_1min = generate_agg_fills_1min(agg_10s)
            if not agg_1min.empty:
                proc_db.upsert_1min_fills(agg_1min)

            proc_db.mark_date_processed(date_str, stage="aggregated", row_count=len(agg_10s))
            logger.info(f"  Aggregated {date_str}: {len(agg_10s)} 10s rows, {len(agg_1min)} 1min rows")

        except Exception as e:
            logger.error(f"  Error aggregating date {date_str}: {e}")


def run_order_labels(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Stage 4: Generate order labels."""
    logger.info("=" * 60)
    logger.info("STAGE 4: Generate order labels")
    logger.info("=" * 60)

    proc_db = ProcessedFillsDB()

    # Get all processed fills (or for specific dates)
    if dates:
        dfs = [proc_db.get_processed_fills_for_date(d) for d in dates]
        processed_fills = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    else:
        processed_fills = proc_db.get_all_processed_fills()

    if processed_fills.empty:
        logger.info("No processed fills for order label generation")
        return pd.DataFrame()

    # Load existing labels if not forcing rebuild
    existing_labels = None if force else proc_db.get_order_labels()

    order_labels = generate_order_label_incremental(processed_fills, existing_labels)

    if not order_labels.empty:
        proc_db.upsert_order_labels(order_labels)

    logger.info(f"Order labels: {len(order_labels)} orders")
    return order_labels


def run_bdib_integration(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Stage 5: Fetch BDIB data and integrate with fills.

    This is optional and requires Bloomberg terminal access.
    """
    logger.info("=" * 60)
    logger.info("STAGE 5: BDIB Integration (requires Bloomberg)")
    logger.info("=" * 60)

    from .fill_bdib_integrated import integrate_fills_bdib_for_date

    proc_db = ProcessedFillsDB()

    # Determine dates
    if dates:
        target_dates = dates
    elif force:
        target_dates = proc_db.get_processed_dates(stage="aggregated")
    else:
        agg_dates = proc_db.get_processed_dates(stage="aggregated")
        target_dates = proc_db.get_unprocessed_dates(agg_dates, stage="bdib_integrated")

    if not target_dates:
        logger.info("No dates for BDIB integration")
        return

    logger.info(f"BDIB integration for {len(target_dates)} dates")

    for date_str in target_dates:
        try:
            agg_df = proc_db.get_agg_fills_for_date(date_str)
            if agg_df.empty:
                continue

            integrated_df = integrate_fills_bdib_for_date(agg_df, date_str)

            if not integrated_df.empty:
                # Store as a separate integration — could be extended to a dedicated table
                proc_db.mark_date_processed(date_str, stage="bdib_integrated", row_count=len(integrated_df))
                logger.info(f"  Integrated {date_str}: {len(integrated_df)} rows")

        except Exception as e:
            logger.error(f"  Error in BDIB integration for {date_str}: {e}")


def run_full_pipeline(
    excel_dir: Optional[Path] = None,
    dates: Optional[List[str]] = None,
    force: bool = False,
    skip_bdib: bool = True,
) -> Dict[str, Any]:
    """Run the complete pipeline: ingest → process → aggregate → labels → (optional) BDIB.

    Args:
        excel_dir: Directory containing Excel fill files
        dates: Specific dates to process (None = all new dates)
        force: Force reprocessing of all dates
        skip_bdib: Skip BDIB integration stage (default True, requires Bloomberg)

    Returns:
        Summary dict with counts for each stage
    """
    logger.info("=" * 60)
    logger.info("EMSX Fill Processing Pipeline — Full Run")
    logger.info("=" * 60)

    Config.initialize_directories()
    summary: Dict[str, Any] = {}

    # Stage 1: Ingest
    ingestion_results = run_ingest(excel_dir=excel_dir)
    summary["ingestion"] = {
        "files_processed": len(ingestion_results),
        "new_rows": sum(r.get("new_rows", 0) for r in ingestion_results),
        "skipped": sum(1 for r in ingestion_results if r.get("skipped")),
    }

    # Stage 2: Process
    processed_df = run_process(dates=dates, force=force)
    summary["processing"] = {
        "rows_processed": len(processed_df),
    }

    # Stage 3: Aggregate
    run_aggregate(dates=dates, force=force)
    summary["aggregation"] = {"completed": True}

    # Stage 4: Order Labels
    order_labels = run_order_labels(dates=dates, force=force)
    summary["order_labels"] = {
        "orders": len(order_labels),
    }

    # Stage 5: BDIB (optional)
    if not skip_bdib:
        run_bdib_integration(dates=dates, force=force)
        summary["bdib"] = {"completed": True}
    else:
        summary["bdib"] = {"skipped": True}

    logger.info("=" * 60)
    logger.info(f"Pipeline complete: {summary}")
    logger.info("=" * 60)

    return summary


def run_incremental(
    excel_dir: Optional[Path] = None,
    skip_bdib: bool = True,
) -> Dict[str, Any]:
    """Run incremental pipeline — only process new/changed data."""
    return run_full_pipeline(
        excel_dir=excel_dir,
        dates=None,
        force=False,
        skip_bdib=skip_bdib,
    )


def get_pipeline_status() -> Dict[str, Any]:
    """Get current status of the processing pipeline."""
    status: Dict[str, Any] = {}

    # Raw fills DB
    try:
        raw_db = RawFillsDB()
        status["raw_fills"] = {
            "total_rows": raw_db.get_row_count(),
            "dates": raw_db.get_all_dates(),
            "date_counts": raw_db.get_date_row_counts(),
        }
    except Exception as e:
        status["raw_fills"] = {"error": str(e)}

    # Processed fills DB
    try:
        proc_db = ProcessedFillsDB()
        stats = proc_db.get_processing_stats()
        status["processed_fills"] = stats
    except Exception as e:
        status["processed_fills"] = {"error": str(e)}

    return status
