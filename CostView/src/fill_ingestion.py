"""
Fill Ingestion — wire FillFetch output into the raw fills SQLite database.

Reads Excel files from FillFetch, cleans them via fill_cleaner, and
upserts into raw_fills.db with duplicate detection via hashing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .fill_cleaner import clean_emsx_fills
from .processing_config import ProcessingConfig as Config
from .raw_fills_db import RawFillsDB, compute_fills_hash

logger = logging.getLogger(__name__)


def ingest_excel_file(
    file_path: Path,
    db: Optional[RawFillsDB] = None,
) -> Dict[str, Any]:
    """Ingest a single FillFetch Excel file into raw_fills.db.

    Steps:
        1. Read Excel → List[Dict]
        2. Compute hash for duplicate detection
        3. Check ingestion_log for prior ingestion with same date + hash
        4. Clean via clean_emsx_fills()
        5. Upsert into raw_fills table
        6. Record in ingestion_log

    Returns:
        Result dict with status, row counts, and any errors.
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
        # 1. Read Excel
        df_raw = pd.read_excel(file_path, engine="openpyxl")
        fills = df_raw.to_dict(orient="records")
        result["total_rows"] = len(fills)

        if not fills:
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Empty file: {file_path.name}")
            return result

        # 2. Compute hash
        hash_value = compute_fills_hash(fills)

        # 3. Extract source date from filename (fills_YYYYMMDD.xlsx)
        source_date = _extract_date_from_filename(file_path.name)

        # 4. Check for duplicate ingestion
        if source_date and db.check_ingestion_duplicate(source_date, hash_value):
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Duplicate detected for {file_path.name} (date={source_date}), skipping")
            return result

        # 5. Clean
        cleaned_df = clean_emsx_fills(fills)

        # 6. Upsert
        new_count = db.upsert_fills(cleaned_df)
        result["new_rows"] = new_count

        # 7. Record ingestion
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
    """Ingest all FillFetch Excel files from the data directory.

    Scans for fills_*.xlsx files and ingests them incrementally.
    Already-ingested files (same date + hash) are skipped.
    """
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

    # Summary
    ingested = sum(1 for r in results if r["success"] and not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    failed = sum(1 for r in results if not r["success"])
    total_new = sum(r["new_rows"] for r in results)

    logger.info(
        f"Ingestion summary: {ingested} ingested, {skipped} skipped, "
        f"{failed} failed, {total_new} new rows total"
    )
    return results


def _extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD date string from a fills_YYYYMMDD.xlsx filename."""
    # Expected format: fills_YYYYMMDD.xlsx
    stem = Path(filename).stem  # fills_YYYYMMDD
    parts = stem.split("_")
    if len(parts) >= 2:
        date_part = parts[-1]
        if len(date_part) == 8 and date_part.isdigit():
            return date_part
    return None
