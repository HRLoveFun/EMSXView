"""
Path configuration for the EMSX fill data pipeline.

All directory and file path constants are defined here.
Separated from processing_config.py as part of P2b config split.
"""

from __future__ import annotations

from pathlib import Path


class PathsConfig:
    """Path-related configuration constants.

    All directory paths, database locations, and file paths used by
    the EMSX data pipeline.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # BASE DIRECTORIES
    # ═══════════════════════════════════════════════════════════════════════

    ROOT_DIR: Path = Path(__file__).resolve().parents[2]               # DataPipeline/src/
    DATA_DIR: Path = ROOT_DIR / "data"
    LOGGING_DIR: Path = ROOT_DIR / "logs"

    # ═══════════════════════════════════════════════════════════════════════
    # RAW DATA
    # ═══════════════════════════════════════════════════════════════════════

    # [DEPRECATED] Excel files from legacy FillFetch output.
    # No longer used since fill_fetch.py writes directly to raw_fills.db via Bloomberg API.
    # Directory reference kept for backward-compat of ingest_excel_file().
    RAW_EXCEL_DIR: Path = DATA_DIR / "fills"

    # ═══════════════════════════════════════════════════════════════════════
    # SQLITE DATABASES
    # ═══════════════════════════════════════════════════════════════════════

    # Existing fetch-tracking database (from FillFetch)
    FETCH_HISTORY_DB: Path = DATA_DIR / "fill_fetch_history.db"

    # Raw fills database — cleaned EMSX fills with derived columns
    RAW_FILLS_DB: Path = DATA_DIR / "raw_fills.db"

    # Processed fills database — transformed fills + aggregations + order labels
    PROCESSED_FILLS_DB: Path = DATA_DIR / "processed_fills.db"

    # ── BDIB data pipeline (3-layer architecture) ──────────────────────────
    #
    # Layer 1: raw_bdib — Bloomberg-native OHLC/volume/num_trds/value only
    RAW_BDIB_DB: Path = DATA_DIR / "raw_bdib.db"
    # Layer 2: processed_raw_bdib — raw_bdib + derived (vwap, fluctuation, log_chg_pct_10s)
    PROCESSED_RAW_BDIB_DB: Path = DATA_DIR / "processed_raw_bdib.db"
    # Layer 3: fill_bdib — fills + processed_bdib integration + TCA metrics
    FILL_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"
    # Legacy alias for fill_bdib.db (backward compatibility)
    PROCESSED_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"

    # ═══════════════════════════════════════════════════════════════════════
    # LOG FILES
    # ═══════════════════════════════════════════════════════════════════════

    LOG_FILE: Path = LOGGING_DIR / "fillfetch.log"
    LOG_DEBUG_FILE: Path = LOGGING_DIR / "fillfetch_debug.log"

    # ═══════════════════════════════════════════════════════════════════════
    # DOWNSTREAM INTERFACE FILES
    # ═══════════════════════════════════════════════════════════════════════

    MARKET_FETCH_MANIFEST: Path = DATA_DIR / "market_fetch_manifest.json"
    OUTDATED_TICKERS_FILE: Path = DATA_DIR / "outdated_tickers.json"
