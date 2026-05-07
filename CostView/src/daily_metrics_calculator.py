"""Daily metrics calculator for CostView Stage 7.

Bloomberg daily history is the source of truth for:
    - total_volume      <- PX_VOLUME
    - daily_volatility  <- VOLATILITY_30D
    - daily_close       <- PX_LAST
    - adv_5d / adv_20d  <- rolling mean of PX_VOLUME

The original intraday-volatility logic is preserved separately by computing
annualized volatility from raw 10-second BDIB bars and storing it in the
`intraday_volatility` column.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .db.connection import AccessTier
from .outdated_tickers import load_outdated_ticker_set
from .processed_fills_db import ProcessedFillsDB
from .processing_config import ProcessingConfig as Config
from .raw_bdib_db import RawBDIBDB

logger = logging.getLogger(__name__)

# Annualization factor for 10-second bars:
#   252 trading days * 6.5 trading hours * 3600s/hr / 10s per bar
BARS_PER_YEAR = 252 * 6.5 * 3600 / 10  # ≈ 589,680
DAILY_HISTORY_FIELDS = ["PX_VOLUME", "VOLATILITY_30D", "PX_LAST"]
LOOKBACK_CALENDAR_DAYS = 60
DEFAULT_HISTORY_CHUNK_SIZE = 50


class CalculateDailyMetrics:
    """Compute and persist Bloomberg daily metrics plus intraday carry-over metrics."""

    def __init__(
        self,
        db: Optional[RawBDIBDB] = None,
        proc_db: Optional[ProcessedFillsDB] = None,
        history_chunk_size: int = DEFAULT_HISTORY_CHUNK_SIZE,
    ):
        self._db = db or RawBDIBDB()
        self._proc_db = proc_db or ProcessedFillsDB(access_tier=AccessTier.READ)
        self._history_chunk_size = history_chunk_size

    # ── Public API ────────────────────────────────────────────────────────────

    def run_for_date(self, trade_date: str) -> int:
        """Compute and upsert metrics for all tickers active on trade_date.

        Args:
            trade_date: YYYYMMDD string.

        Returns:
            Number of rows upserted into bdib_daily_summary.
        """
        logger.info(f"CalculateDailyMetrics: processing date {trade_date}")

        tickers = self._get_active_tickers_for_date(trade_date)
        if not tickers:
            logger.info(f"No active equity tickers for {trade_date}; skipping daily metrics.")
            return 0

        daily_history_df = self._fetch_daily_history(tickers, trade_date)
        if daily_history_df.empty:
            logger.warning(f"No Bloomberg daily history found for {trade_date}; skipping daily metrics.")
            return 0

        bars_df = self._load_bars_for_date(trade_date)
        logger.info(f"  Tickers with daily history on {trade_date}: {len(tickers)}")

        rows: list[dict] = []
        for ticker in tickers:
            ticker_history = daily_history_df[
                daily_history_df["equ_ticker"] == ticker
            ].copy()
            ticker_bars = bars_df[bars_df["equ_ticker"] == ticker].copy()
            stats = self._build_summary_row(ticker, trade_date, ticker_history, ticker_bars)
            if stats:
                rows.append(stats)

        upserted = self._db.upsert_daily_summary(rows)

        logger.info(f"CalculateDailyMetrics: upserted {upserted} rows for {trade_date}")
        return upserted

    def run_all_dates(self) -> int:
        """Compute and upsert metrics for every active order date."""
        ticker_dates = self._proc_db.get_ticker_dates("equ_ticker")
        dates = sorted({date_str for date_list in ticker_dates.values() for date_str in date_list})
        if not dates:
            logger.info("processed_fills has no active equity ticker dates; nothing to compute.")
            return 0

        logger.info(f"CalculateDailyMetrics: processing {len(dates)} dates")
        total = 0
        for trade_date in dates:
            try:
                total += self.run_for_date(trade_date)
            except Exception as exc:
                logger.error(f"  Error computing metrics for {trade_date}: {exc}")
        return total

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_bars_for_date(self, trade_date: str) -> pd.DataFrame:
        """Return all raw_bdib bars for a given date (all tickers)."""
        import sqlite3
        conn = sqlite3.connect(str(self._db.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            df = pd.read_sql_query(
                f"SELECT equ_ticker, mkt_timestamp, close, volume "
                f"FROM {Config.RAW_BDIB_TABLE} "
                "WHERE order_as_of_date = ? "
                "ORDER BY equ_ticker, mkt_timestamp",
                conn,
                params=[trade_date],
            )
        finally:
            conn.close()
        return df

    def _get_active_tickers_for_date(self, trade_date: str) -> list[str]:
        ticker_dates = self._proc_db.get_ticker_dates("equ_ticker")
        outdated = load_outdated_ticker_set()
        return sorted(
            {
                ticker
                for ticker, dates in ticker_dates.items()
                if ticker not in outdated and trade_date in dates
            }
        )

    def _fetch_daily_history(self, tickers: list[str], trade_date: str) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame()

        try:
            from xbbg import blp
        except ImportError:
            logger.warning("xbbg not available; skipping Bloomberg daily history fetch")
            return pd.DataFrame()

        trade_dt = datetime.strptime(trade_date, "%Y%m%d").date()
        start_date = (trade_dt - timedelta(days=LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")
        end_date = trade_dt.strftime("%Y-%m-%d")

        parts: list[pd.DataFrame] = []
        for offset in range(0, len(tickers), self._history_chunk_size):
            chunk = tickers[offset : offset + self._history_chunk_size]
            part = self._fetch_daily_history_chunk(blp, chunk, start_date, end_date)
            if not part.empty:
                parts.append(part)

        if not parts:
            return pd.DataFrame()

        return (
            pd.concat(parts, ignore_index=True)
            .drop_duplicates(subset=["equ_ticker", "trade_date"], keep="last")
            .sort_values(["equ_ticker", "trade_date"])
            .reset_index(drop=True)
        )

    def _fetch_daily_history_chunk(
        self,
        blp: object,
        tickers: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        try:
            history_df = blp.bdh(
                tickers=tickers,
                flds=DAILY_HISTORY_FIELDS,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            if len(tickers) > 1:
                logger.warning(
                    f"Daily history chunk failed for {len(tickers)} tickers; retrying one-by-one: {exc}"
                )
                parts = [
                    self._fetch_daily_history_chunk(blp, [ticker], start_date, end_date)
                    for ticker in tickers
                ]
                parts = [part for part in parts if not part.empty]
                if parts:
                    return pd.concat(parts, ignore_index=True)
                return pd.DataFrame()

            logger.warning(f"Daily history fetch failed for {tickers[0]}: {exc}")
            return pd.DataFrame()

        return self._normalize_daily_history(history_df, tickers)

    @staticmethod
    def _normalize_daily_history(history_df: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
        if history_df is None or history_df.empty:
            return pd.DataFrame()

        df = history_df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            level0 = {str(col[0]).upper() for col in df.columns}
            level1 = {str(col[1]).upper() for col in df.columns}

            if set(DAILY_HISTORY_FIELDS) & level1:
                long_df = df.stack(0).reset_index()
                long_df.rename(columns={"level_1": "equ_ticker"}, inplace=True)
            elif set(DAILY_HISTORY_FIELDS) & level0:
                long_df = df.stack(1).reset_index()
                long_df.rename(columns={"level_1": "equ_ticker"}, inplace=True)
            else:
                return pd.DataFrame()
        else:
            long_df = df.reset_index()
            long_df["equ_ticker"] = tickers[0] if tickers else None

        if "trade_date" not in long_df.columns:
            long_df.rename(columns={long_df.columns[0]: "trade_date"}, inplace=True)

        normalized = long_df.copy()
        normalized["trade_date"] = pd.to_datetime(
            normalized["trade_date"], errors="coerce"
        ).dt.strftime("%Y%m%d")

        for bloomberg_field, column_name in (
            ("PX_VOLUME", "total_volume"),
            ("VOLATILITY_30D", "daily_volatility"),
            ("PX_LAST", "daily_close"),
        ):
            source_col = next(
                (col for col in normalized.columns if str(col).upper() == bloomberg_field),
                None,
            )
            normalized[column_name] = (
                pd.to_numeric(normalized[source_col], errors="coerce")
                if source_col is not None
                else np.nan
            )

        return normalized[
            ["equ_ticker", "trade_date", "total_volume", "daily_volatility", "daily_close"]
        ].dropna(subset=["equ_ticker", "trade_date"])

    def _build_summary_row(
        self,
        ticker: str,
        trade_date: str,
        ticker_history: pd.DataFrame,
        ticker_bars: pd.DataFrame,
    ) -> Optional[dict]:
        if ticker_history.empty:
            return None

        ticker_history = ticker_history.sort_values("trade_date")
        today_rows = ticker_history[ticker_history["trade_date"] == trade_date]
        if today_rows.empty:
            logger.warning(f"Daily history for {ticker} does not include {trade_date}; skipping")
            return None

        today = today_rows.iloc[-1]
        volumes = ticker_history["total_volume"].dropna()
        intraday_stats = self._compute_intraday_stats(ticker_bars)

        return {
            "equ_ticker": ticker,
            "trade_date": trade_date,
            "total_volume": self._to_optional_float(today.get("total_volume")),
            "daily_vwap": intraday_stats["daily_vwap"],
            "daily_close": self._to_optional_float(today.get("daily_close")),
            "daily_volatility": self._to_optional_float(today.get("daily_volatility")),
            "intraday_volatility": intraday_stats["intraday_volatility"],
            "adv_5d": float(volumes.iloc[-5:].mean()) if len(volumes) >= 2 else None,
            "adv_20d": float(volumes.iloc[-20:].mean()) if len(volumes) >= 2 else None,
        }

    @staticmethod
    def _compute_intraday_stats(bars: pd.DataFrame) -> dict[str, Optional[float]]:
        total_volume = float(bars["volume"].sum()) if "volume" in bars.columns and not bars.empty else None

        if total_volume and total_volume > 0 and "close" in bars.columns:
            daily_vwap = float((bars["close"] * bars["volume"]).sum() / total_volume)
        else:
            daily_vwap = None

        intraday_volatility = None
        closes = bars["close"].dropna() if "close" in bars.columns else pd.Series(dtype=float)
        if len(closes) >= 2:
            log_returns = np.log(closes / closes.shift(1)).dropna()
            if len(log_returns) >= 2:
                std_10s = float(log_returns.std())
                intraday_volatility = std_10s * math.sqrt(BARS_PER_YEAR)

        return {
            "daily_vwap": daily_vwap,
            "intraday_volatility": intraday_volatility,
        }

    @staticmethod
    def _to_optional_float(value: object) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        return float(value)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(_ROOT))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Compute Bloomberg daily metrics for CostView")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="YYYYMMDD — process a single date")
    group.add_argument("--all", action="store_true", help="Process all dates in raw_bdib")
    args = parser.parse_args()

    calc = CalculateDailyMetrics()
    if args.all:
        total = calc.run_all_dates()
    else:
        total = calc.run_for_date(args.date)
    print(f"Done — {total} rows upserted into bdib_daily_summary.")
