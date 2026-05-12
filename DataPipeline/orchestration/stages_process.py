"""
BDIB & metrics computation stages (S5–S7).

S5  IntegrateBDIBStage       — BDIB market data integration
S6  WriteManifestStage       — MarketFetch manifest
S7  CalculateDailyMetricsStage  — ADV + volatility
"""

from __future__ import annotations

import gc
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.config import Config

from .base import BaseStage, _to_iso_safe
from .context import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# S5: IntegrateBDIBStage
# ═══════════════════════════════════════════════════════════════
class IntegrateBDIBStage(BaseStage):
    """Stage 5: Fetch BDIB data and integrate with fills."""
    @property
    def name(self) -> str: return "5. Integrate BDIB Market Data"

    @staticmethod
    def _get_previous_weekday(today: Optional[date] = None) -> date:
        ref = today or datetime.now().date()
        candidate = ref - timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    @classmethod
    def _get_latest_safe_bdib_date(cls, now: Optional[datetime] = None) -> date:
        ref_dt = now or datetime.now()
        safe_date = cls._get_previous_weekday(ref_dt.date())
        if safe_date == ref_dt.date() - timedelta(days=1) and ref_dt.hour < Config.BDIB_LATEST_READY_HOUR_LOCAL:
            safe_date = cls._get_previous_weekday(safe_date)
        return safe_date

    @staticmethod
    def _expand_weekdays(start: date, end: date) -> List[str]:
        if start > end:
            return []
        dates: List[str] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                dates.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return dates

    def process(self, context: PipelineContext) -> bool:
        try:
            from DataPipeline.acquisition.bdib_fetcher import fetch_bdib_for_fills
            from DataPipeline.processing.fill_bdib_integrated import integrate_fills_bdib_for_date
        except ImportError as e:
            logger.warning(f"Skipping BDIB Integration due to ImportError: {e}")
            context.summary["bdib"] = {"skipped": True, "error": str(e)}
            return True

        from DataPipeline.storage.repositories.market_data import (
            SqliteMarketDataWriteRepository,
        )
        cm = context.get_connection_manager()
        market_write = SqliteMarketDataWriteRepository(connection_manager=cm) if cm else context.db.market_data_write
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write

        latest_safe_bdib_date = self._get_latest_safe_bdib_date()
        latest_safe_bdib_str = latest_safe_bdib_date.strftime("%Y%m%d")

        if context.target_dates:
            all_candidate_dates = sorted({str(d) for d in context.target_dates if str(d)})
            unsafe_dates = [d for d in all_candidate_dates if d > latest_safe_bdib_str]
            if unsafe_dates:
                logger.info(
                    f"Skipping {len(unsafe_dates)} unsafe BDIB target date(s) newer than "
                    f"{latest_safe_bdib_str}: {unsafe_dates[:5]}"
                )
                all_candidate_dates = [d for d in all_candidate_dates if d <= latest_safe_bdib_str]
        else:
            latest_raw = context.db.market_data_read.get_latest_order_as_of_date()
            if context.force or not latest_raw:
                start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)
            else:
                try:
                    latest_dt = datetime.strptime(latest_raw, "%Y%m%d").date()
                    start_dt = latest_dt + timedelta(days=1)
                except ValueError:
                    start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)

        if not all_candidate_dates:
            logger.info("No dates for BDIB integration")
            context.summary["bdib"] = {"completed": True, "dates": 0}
            return True

        latest_raw_date = context.db.market_data_read.get_latest_order_as_of_date()
        latest_proc_raw_date = context.db.market_data_read.get_latest_order_as_of_date()
        try:
            already_integrated = set(fills_reader.get_processed_dates(stage="bdib_integrated") or [])
        except Exception:
            already_integrated = set()

        bdid_exchange = [str(e).strip().upper() for e in Config.BDID_EXCHANGE if str(e).strip()]
        ticker_exchange_map_all = fills_reader.get_ticker_exchange_map(exchanges=bdid_exchange)
        if not ticker_exchange_map_all:
            context.summary["bdib"] = {
                "completed": True, "dates": len(all_candidate_dates),
                "raw_bdib_rows": 0, "processed_raw_bdib_rows": 0, "fill_bdib_rows": 0,
            }
            return True

        total_raw_bdib_rows = 0
        total_processed_raw_bdib_rows = 0
        total_fill_bdib_rows = 0
        skipped_raw = 0; skipped_proc_raw = 0; skipped_fill = 0

        # Chunk tickers to avoid loading ALL BDIB data into memory at once
        all_tickers = list(ticker_exchange_map_all.keys())
        ticker_chunk_size = 50
        logger.info("BDIB: %d tickers, processing in chunks of %d", len(all_tickers), ticker_chunk_size)

        for date_str in all_candidate_dates:
            try:
                if not context.force and latest_raw_date and date_str <= latest_raw_date:
                    skipped_raw += 1; continue
                if not context.force and latest_proc_raw_date and date_str <= latest_proc_raw_date:
                    skipped_proc_raw += 1; continue
                if not context.force and date_str in already_integrated:
                    skipped_fill += 1; continue

                date_raw_rows = 0
                date_proc_raw_rows = 0
                bdib_enriched_chunks = []

                # ── Phase A+B: Chunked BDIB fetch + write ──
                for chunk_i in range(0, len(all_tickers), ticker_chunk_size):
                    chunk_tickers = all_tickers[chunk_i:chunk_i + ticker_chunk_size]
                    chunk_ticker_dates = {t: [date_str] for t in chunk_tickers}
                    try:
                        chunk_map = fetch_bdib_for_fills(chunk_ticker_dates, interval=10, ticker_exchange_map=ticker_exchange_map_all)
                        if not chunk_map:
                            continue
                        chunk_dfs = [df for key, df in chunk_map.items() if key.endswith(f"|{date_str}")]
                        if not chunk_dfs:
                            continue
                        chunk_bdib_df = pd.concat(chunk_dfs, ignore_index=True)
                        if chunk_bdib_df.empty:
                            continue

                        # Write raw BDIB
                        date_raw_rows += market_write.upsert_bdib_data(chunk_bdib_df, date_str=date_str)

                        # Compute derived fields
                        enriched = market_write.compute_derived_fields(chunk_bdib_df)
                        date_proc_raw_rows += market_write.upsert_processed_bdib(enriched)
                        bdib_enriched_chunks.append(enriched)

                        del chunk_map, chunk_dfs, chunk_bdib_df, enriched
                        gc.collect()
                    except Exception as chunk_err:
                        logger.warning("  BDIB chunk %d error for %s: %s", chunk_i, date_str, chunk_err)

                if not bdib_enriched_chunks:
                    total_raw_bdib_rows += date_raw_rows
                    total_processed_raw_bdib_rows += date_proc_raw_rows
                    continue

                # Combine enriched chunks for integration
                bdib_enriched = pd.concat(bdib_enriched_chunks, ignore_index=True)
                del bdib_enriched_chunks
                gc.collect()

                # ── Phase C: Integration with agg_fills ──
                agg_df = fills_reader.get_agg_fills_10s_for_date(date_str)
                if agg_df.empty:
                    agg_df = fills_reader.get_agg_fills_for_date(date_str)
                if agg_df.empty:
                    total_raw_bdib_rows += date_raw_rows
                    total_processed_raw_bdib_rows += date_proc_raw_rows
                    del bdib_enriched
                    gc.collect()
                    continue

                integrated_df = integrate_fills_bdib_for_date(agg_df, date_str, bdib_data=bdib_enriched, ticker_exchange_map=ticker_exchange_map_all)
                total_raw_bdib_rows += date_raw_rows
                total_processed_raw_bdib_rows += date_proc_raw_rows

                fill_bdib_rows = 0
                if not integrated_df.empty:
                    fill_bdib_rows = context.db.integrated_write.upsert_integrated_data(integrated_df, date_str=date_str)
                    total_fill_bdib_rows += fill_bdib_rows
                    fills_writer.mark_date_processed(date_str, stage="bdib_integrated", row_count=len(integrated_df))

                # ── Free per-date memory ──
                del bdib_enriched, agg_df, integrated_df
                gc.collect()
                logger.info("  BDIB %s: raw=%d processed=%d integrated=%d",
                            date_str, date_raw_rows, date_proc_raw_rows, fill_bdib_rows)

            except Exception as e:
                logger.error(f"  Error in BDIB integration for {date_str}: {e}")
                gc.collect()

        context.summary["bdib"] = {
            "completed": True, "candidate_dates": len(all_candidate_dates),
            "processed_dates": len(all_candidate_dates) - skipped_raw - skipped_proc_raw - skipped_fill,
            "skipped_raw": skipped_raw, "skipped_processed_raw": skipped_proc_raw, "skipped_fill": skipped_fill,
            "raw_bdib_rows": total_raw_bdib_rows, "processed_raw_bdib_rows": total_processed_raw_bdib_rows, "fill_bdib_rows": total_fill_bdib_rows,
        }
        return True


# ═══════════════════════════════════════════════════════════════
# S6: WriteManifestStage
# ═══════════════════════════════════════════════════════════════
class WriteManifestStage(BaseStage):
    """Stage 6: Write downstream manifest for MarketFetch."""
    @property
    def name(self) -> str: return "6. Write MarketFetch Manifest"

    def process(self, context: PipelineContext) -> bool:
        try:
            from CostView.src.downstream_interface import write_manifest
            write_manifest(updated_dates=context.target_dates)
            context.summary["manifest"] = {"written": True}
            return True
        except Exception as e:
            context.summary["manifest"] = {"written": False, "error": str(e)}
            logger.warning(f"Manifest write skipped: {e}")
            return True


# ═══════════════════════════════════════════════════════════════
# S7: CalculateDailyMetricsStage
# ═══════════════════════════════════════════════════════════════
class CalculateDailyMetricsStage(BaseStage):
    """Stage 7: Pre-compute ADV (5d/20d) and annualized volatility into bdib_daily_summary."""
    @property
    def name(self) -> str: return "7. Calculate Daily Metrics (ADV + Volatility)"

    def process(self, context: PipelineContext) -> bool:
        try:
            from DataPipeline.processing.daily_metrics_calculator import CalculateDailyMetrics
        except ImportError as e:
            logger.warning(f"Skipping daily metrics calculation: {e}")
            context.summary["daily_metrics"] = {"skipped": True, "error": str(e)}
            return True

        calc = CalculateDailyMetrics(
            connection_manager=context.get_connection_manager(), db=context.db,
        )

        if context.target_dates:
            dates_to_process = context.target_dates
        else:
            fills_reader = context.db.fills_read
            dates_to_process = fills_reader.get_processed_dates(stage="bdib_integrated")
            if not dates_to_process:
                dates_to_process = context.db.market_data_read.get_distinct_dates()

        if not dates_to_process:
            logger.info("No dates for daily metrics calculation")
            context.summary["daily_metrics"] = {"rows": 0}
            return True

        total_rows = 0
        for trade_date in dates_to_process:
            try:
                rows = calc.run_for_date(trade_date)
                total_rows += rows
            except Exception as e:
                logger.error(f"  Error computing metrics for {trade_date}: {e}")

        context.summary["daily_metrics"] = {"rows": total_rows, "dates": len(dates_to_process)}
        return True
