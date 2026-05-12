"""
Raw Fills Database Validation Script — fill share integrity checker.

Validates that SUM(FillShares) grouped by OrderId equals the Amount field
for each order. This ensures data completeness and accuracy after fetching
from Bloomberg EMSX API.

Migrated from CostView/src/validate_raw_fills.py (2026-05-11).

Note: raw_fills.db uses composite PRIMARY KEY (OrderId, RouteId, FillId).
Bloomberg may send multiple corrections for the same (OrderId, FillId) on
different routes; the triple-key preserves all versions so that
SUM(FillShares) accurately reflects total executed volume.

Usage modes:
    1. Standalone CLI: python -m DataPipeline.processing.validate_raw_fills [--date YYYYMMDD] [--output DIR]
    2. Library import:  validate_raw_fills_db(db_path, source_date=None)
    3. In-memory:       validate_fill_data(fills_list) — for pre-insert checks

Output:
    - Console report of pass/fail counts
    - Excel file with anomalous orders (OrderId where SUM(FillShares) != Amount)
    - Returns ValidationResult for programmatic use
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Result Data Structures
# ═══════════════════════════════════════════════════════════════════════

class ValidationResult:
    """Immutable container for validation results."""

    __slots__ = (
        "total_orders", "passed_orders", "failed_orders",
        "anomalies_df", "checked_at", "source_date",
        "tolerance", "error_message",
    )

    def __init__(
        self,
        total_orders: int = 0,
        passed_orders: int = 0,
        failed_orders: int = 0,
        anomalies_df: Optional[pd.DataFrame] = None,
        checked_at: Optional[str] = None,
        source_date: Optional[str] = None,
        tolerance: float = 0.01,
        error_message: Optional[str] = None,
    ):
        self.total_orders = total_orders
        self.passed_orders = passed_orders
        self.failed_orders = failed_orders
        self.anomalies_df = anomalies_df if anomalies_df is not None else pd.DataFrame()
        self.checked_at = checked_at or datetime.now().isoformat()
        self.source_date = source_date
        self.tolerance = tolerance
        self.error_message = error_message

    @property
    def success(self) -> bool:
        """True if no anomalies found AND no errors."""
        return self.failed_orders == 0 and self.error_message is None

    @property
    def pass_rate(self) -> float:
        """Pass rate as a fraction [0.0, 1.0]."""
        if self.total_orders == 0:
            return 1.0
        return self.passed_orders / self.total_orders

    @property
    def summary(self) -> Dict[str, Any]:
        """Dict summary suitable for logging."""
        return {
            "source_date": self.source_date,
            "total_orders": self.total_orders,
            "passed": self.passed_orders,
            "failed": self.failed_orders,
            "pass_rate": f"{self.pass_rate:.2%}",
            "tolerance": self.tolerance,
            "success": self.success,
            "error": self.error_message,
        }

    def to_log_string(self) -> str:
        """Human-readable summary for log output."""
        parts = []
        if self.source_date:
            parts.append(f"date={self.source_date}")
        parts.append(f"orders={self.total_orders}")
        parts.append(f"passed={self.passed_orders}")
        parts.append(f"failed={self.failed_orders}")
        parts.append(f"rate={self.pass_rate:.2%}")
        if self.error_message:
            parts.append(f"error={self.error_message}")
        return ", ".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Core Validation Logic
# ═══════════════════════════════════════════════════════════════════════

def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip()
        if s == "" or s.lower() in ("nan", "none", "null"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _compute_aggregation(
    df: pd.DataFrame,
    tolerance: float = 0.01,
) -> pd.DataFrame:
    """Group by OrderId, compute SUM(FillShares), compare to Amount.

    Args:
        df: DataFrame containing at least ['OrderId', 'FillShares', 'Amount'].
        tolerance: Absolute numeric tolerance for floating-point comparison.

    Returns:
        DataFrame with columns: OrderId, Amount, SumFillShares, Diff, Status.
    """
    # Convert columns to numeric, coercing invalid values to NaN
    df = df.copy()
    df["_fs"] = df["FillShares"].apply(_safe_float)
    df["_amt"] = df["Amount"].apply(_safe_float)

    # Drop rows where critical fields are missing
    valid = df.dropna(subset=["OrderId", "_fs", "_amt"])

    if valid.empty:
        return pd.DataFrame(
            columns=["OrderId", "Amount", "SumFillShares", "Diff", "Status"]
        )

    # Group by OrderId: SUM(FillShares), take Amount (constant per order)
    aggregated = (
        valid.groupby("OrderId")
        .agg(
            Amount=("_amt", "first"),          # Amount is constant per order
            SumFillShares=("_fs", "sum"),
            fill_count=("_fs", "count"),
        )
        .reset_index()
    )

    # Compute difference and determine status
    aggregated["Diff"] = aggregated["SumFillShares"] - aggregated["Amount"]

    def _status(row):
        if abs(row["Diff"]) <= tolerance:
            return "PASS"
        else:
            return "FAIL"

    aggregated["Status"] = aggregated.apply(_status, axis=1)

    result = aggregated[
        ["OrderId", "Amount", "SumFillShares", "Diff", "Status"]
    ].copy()

    return result


def validate_fill_data(
    fills: List[Dict[str, Any]],
    tolerance: float = 0.01,
    source_date: Optional[str] = None,
) -> ValidationResult:
    """Validate fill data from an in-memory list of dicts.

    This is the primary entry point for pre-insert validation in fill_fetch.py.
    Called after Bloomberg download, before writing to raw_fills.db.

    Args:
        fills: List of fill record dicts (each must have 'OrderId', 'FillShares', 'Amount').
        tolerance: Absolute numeric tolerance for comparison.
        source_date: Optional date string for logging context.

    Returns:
        ValidationResult with anomaly details.
    """
    if not fills:
        return ValidationResult(
            total_orders=0,
            checked_at=datetime.now().isoformat(),
            source_date=source_date,
            tolerance=tolerance,
        )

    try:
        df = pd.DataFrame(fills)

        required = {"OrderId", "FillShares", "Amount"}
        missing = required - set(df.columns)
        if missing:
            return ValidationResult(
                total_orders=0,
                error_message=f"Missing required columns: {missing}",
                source_date=source_date,
                tolerance=tolerance,
            )

        agg_result = _compute_aggregation(df, tolerance=tolerance)

        total = len(agg_result)
        passed = len(agg_result[agg_result["Status"] == "PASS"])
        failed = len(agg_result[agg_result["Status"] == "FAIL"])
        anomalies = agg_result[agg_result["Status"] == "FAIL"].copy()

        result = ValidationResult(
            total_orders=total,
            passed_orders=passed,
            failed_orders=failed,
            anomalies_df=anomalies.reset_index(drop=True),
            source_date=source_date,
            tolerance=tolerance,
        )

        logger.info(f"Validation complete: {result.to_log_string()}")
        return result

    except Exception as e:
        logger.error(f"Validation error: {e}", exc_info=True)
        return ValidationResult(
            error_message=str(e),
            source_date=source_date,
            tolerance=tolerance,
        )


def validate_raw_fills_db(
    db_path: Optional[str] = None,
    source_date: Optional[str] = None,
    tolerance: float = 0.01,
) -> ValidationResult:
    """Validate existing data in raw_fills.db.

    Reads from the SQLite database and performs the aggregation check.
    Optionally filters by source_date.

    Args:
        db_path: Path to raw_fills.db (default: from ProcessingConfig).
        source_date: If set, only validate rows matching this source_date (YYYYMMDD).
        tolerance: Absolute numeric tolerance for comparison.

    Returns:
        ValidationResult with anomaly details.
    """
    db_path = Path(db_path or Config.RAW_FILLS_DB)

    if not db_path.exists():
        return ValidationResult(
            error_message=f"Database not found: {db_path}",
            source_date=source_date,
            tolerance=tolerance,
        )

    conn = ConnectionManager(path_overrides={"raw_fills": db_path} if db_path else {}).get_connection("raw_fills", AccessTier.READ).raw_connection
    try:
        table = Config.RAW_FILLS_TABLE

        # Build query with optional date filter
        if source_date:
            query = f"""
                SELECT OrderId, FillShares, Amount
                FROM {table}
                WHERE source_date = ?
                  AND FillShares IS NOT NULL AND FillShares != ''
                  AND Amount IS NOT NULL AND Amount != ''
                """
            df = pd.read_sql_query(query, conn, params=[source_date])
        else:
            query = f"""
                SELECT OrderId, FillShares, Amount
                FROM {table}
                WHERE FillShares IS NOT NULL AND FillShares != ''
                  AND Amount IS NOT NULL AND Amount != ''
            """
            df = pd.read_sql_query(query, conn)

        if df.empty:
            msg = f"No data found"
            if source_date:
                msg += f" for source_date={source_date}"
            logger.warning(msg)
            return ValidationResult(
                total_orders=0,
                error_message=msg,
                source_date=source_date,
                tolerance=tolerance,
            )

        agg_result = _compute_aggregation(df, tolerance=tolerance)

        total = len(agg_result)
        passed = len(agg_result[agg_result["Status"] == "PASS"])
        failed = len(agg_result[agg_result["Status"] == "FAIL"])
        anomalies = agg_result[agg_result["Status"] == "FAIL"].copy()

        result = ValidationResult(
            total_orders=total,
            passed_orders=passed,
            failed_orders=failed,
            anomalies_df=anomalies.reset_index(drop=True),
            source_date=source_date,
            tolerance=tolerance,
        )

        logger.info(f"DB Validation complete: {result.to_log_string()}")
        return result

    except Exception as e:
        logger.error(f"DB validation error: {e}", exc_info=True)
        return ValidationResult(
            error_message=str(e),
            source_date=source_date,
            tolerance=tolerance,
        )
    finally:
        conn.close()


def save_anomaly_report(
    result: ValidationResult,
    output_dir: Optional[str] = None,
) -> Optional[Path]:
    """Save the anomaly report to an Excel file.

    Args:
        result: ValidationResult with anomaly data.
        output_dir: Directory to save to (default: Config.DATA_DIR).

    Returns:
        Path to saved file, or None if nothing to save.
    """
    if result.anomalies_df.empty:
        logger.info("No anomalies to save")
        return None

    output_dir = Path(output_dir or Config.DATA_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{result.source_date}" if result.source_date else ""
    filename = f"validation_anomalies{suffix}_{ts}.xlsx"
    filepath = output_dir / filename

    # Build report workbook with summary sheet + detail sheet
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        # Summary sheet
        summary_data = {
            "Metric": [
                "Checked At",
                "Source Date",
                "Tolerance",
                "Total Orders",
                "Passed",
                "Failed",
                "Pass Rate",
                "Success",
            ],
            "Value": [
                result.checked_at,
                result.source_date or "(all dates)",
                str(result.tolerance),
                result.total_orders,
                result.passed_orders,
                result.failed_orders,
                f"{result.pass_rate:.2%}",
                "YES" if result.success else "NO",
            ],
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # Anomaly detail sheet
        result.anomalies_df.to_excel(writer, sheet_name="Anomalous Orders", index=False)

    logger.info(f"Anomaly report saved: {filepath} ({len(result.anomalies_df)} orders)")
    return filepath


# ═══════════════════════════════════════════════════════════════════════
# Reporting & Display Helpers
# ═══════════════════════════════════════════════════════════════════════

def print_validation_report(result: ValidationResult) -> None:
    """Print a formatted validation report to console."""
    sep = "=" * 64
    print(f"\n{sep}")
    print("  RAW FILLS VALIDATION REPORT")
    print(sep)

    if result.error_message:
        print(f"  ERROR: {result.error_message}")
        print(sep)
        return

    date_label = f"Date: {result.source_date}" if result.source_date else "Date: (all dates)"
    print(f"  {date_label}")
    print(f"  Checked At:   {result.checked_at}")
    print(f"  Tolerance:    +/-{result.tolerance}")
    print("-" * 64)
    print(f"  Total Orders: {result.total_orders:>8}")
    print(f"  Passed:       {result.passed_orders:>8}")
    print(f"  Failed:       {result.failed_orders:>8}")
    print(f"  Pass Rate:    {result.pass_rate:>8.2%}")
    print(sep)

    if not result.anomalies_df.empty:
        print(f"\n  ANOMALOUS ORDERS ({len(result.anomalies_df)}):")
        print("-" * 64)
        display_cols = ["OrderId", "Amount", "SumFillShares", "Diff", "Status"]
        display_df = result.anomalies_df[display_cols]
        # Format for readability
        pd.set_option("display.max_rows", 500)
        pd.set_option("display.max_columns", 10)
        pd.set_option("display.width", 120)
        print(display_df.to_string(index=False))
        print(sep)

    status = "PASS" if result.success else "FAIL"
    icon = "OK" if result.success else "** CHECK REQUIRED **"
    print(f"\n  Overall Status: [{status}] {icon}\n")


# ═══════════════════════════════════════════════════════════════════════
# Batch Date Validation (scan all dates in DB)
# ═══════════════════════════════════════════════════════════════════════

def validate_all_dates(
    db_path: Optional[str] = None,
    tolerance: float = 0.01,
    output_dir: Optional[str] = None,
) -> List[ValidationResult]:
    """Validate every source_date present in raw_fills.db.

    Args:
        db_path: Path to raw_fills.db.
        tolerance: Numeric tolerance per-order check.
        output_dir: If set, save individual anomaly reports per failing date.

    Returns:
        List of ValidationResult, one per date.
    """
    db_path = Path(db_path or Config.RAW_FILLS_DB)
    conn = ConnectionManager(path_overrides={"raw_fills": db_path} if db_path else {}).get_connection("raw_fills", AccessTier.READ).raw_connection
    try:
        cursor = conn.execute(f"""
            SELECT DISTINCT source_date FROM {Config.RAW_FILLS_TABLE}
            WHERE source_date IS NOT NULL AND source_date != ''
            ORDER BY source_date
        """)
        dates = [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

    if not dates:
        logger.info("No dates found in raw_fills.db")
        return []

    logger.info(f"Validating {len(dates)} dates...")
    results = []

    for date_str in dates:
        result = validate_raw_fills_db(
            db_path=db_path, source_date=date_str, tolerance=tolerance
        )
        results.append(result)

        if not result.success and not result.anomalies_df.empty and output_dir:
            save_anomaly_report(result, output_dir=output_dir)

    return results


def print_batch_summary(results: List[ValidationResult]) -> None:
    """Print a consolidated summary across all validated dates."""
    sep = "=" * 72
    print(f"\n{sep}")
    print("  BATCH VALIDATION SUMMARY (ALL DATES)")
    print(sep)

    total_o = sum(r.total_orders for r in results)
    total_p = sum(r.passed_orders for r in results)
    total_f = sum(r.failed_orders for r in results)
    fail_dates = [r for r in results if not r.success]

    print(f"  Dates Validated: {len(results):>6}")
    print(f"  Total Orders:     {total_o:>6}")
    print(f"  Total Passed:     {total_p:>6}")
    print(f"  Total Failed:     {total_f:>6}")
    print(f"  Overall Pass Rate:{(total_p/total_o if total_o > 0 else 1):>7.2%}")
    print(f"  Failing Dates:    {len(fail_dates):>6}")

    if fail_dates:
        print("\n  FAILING DATE DETAILS:")
        print("-" * 72)
        print(f"  {'Date':<14} {'Orders':>8} {'Failed':>8} {'Rate':>10}  Status")
        print("-" * 72)
        for r in fail_dates:
            flag = "ERROR" if r.error_message else "ANOMALIES"
            print(
                f"  {(r.source_date or '?'):<14} "
                f"{r.total_orders:>8} "
                f"{r.failed_orders:>8} "
                f"{r.pass_rate:>9.2%}  {flag}"
            )

    print(sep)


# ═══════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point for standalone validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate raw_fills.db: check SUM(FillShares)==Amount per OrderId.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate entire database
  python -m DataPipeline.processing.validate_raw_fills

  # Validate specific date
  python -m DataPipeline.processing.validate_raw_fills --date 20260327

  # Validate all dates with reports saved
  python -m DataPipeline.processing.validate_raw_fills --all-dates --output ./reports

  # Custom tolerance
  python -m DataPipeline.processing.validate_raw_fills --tolerance 0.001
        """,
    )
    parser.add_argument(
        "--db-path", type=str, default=None,
        help="Path to raw_fills.db (default: from config)",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Validate only this source_date (YYYYMMDD)",
    )
    parser.add_argument(
        "--all-dates", action="store_true",
        help="Validate ALL dates individually and show batch summary",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.01,
        help="Absolute tolerance for SUM(FillShares) vs Amount comparison (default: 0.01)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output directory for anomaly reports",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    if args.all_dates:
        results = validate_all_dates(
            db_path=args.db_path,
            tolerance=args.tolerance,
            output_dir=args.output,
        )
        print_batch_summary(results)
    else:
        result = validate_raw_fills_db(
            db_path=args.db_path,
            source_date=args.date,
            tolerance=args.tolerance,
        )
        print_validation_report(result)
        if not result.anomalies_df.empty and args.output:
            save_anomaly_report(result, output_dir=args.output)

    return 0 if (result.success if not args.all_dates else all(r.success for r in results)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
