"""
Concrete pipeline processing stages.

Each stage is a self-contained class inheriting from BaseStage:
  S1  IngestExcelStage         — Excel ingestion into raw_fills.db
  S2  ProcessRawFillsStage     — raw → processed fills
  S3  AggregateFillsStage      — route-level 10s aggregation
  S4  GenerateOrderLabelsStage — order-level labels
  S5  IntegrateBDIBStage       — BDIB market data integration
  S6  WriteManifestStage       — MarketFetch manifest
  S7  CalculateDailyMetricsStage  — ADV + volatility
  S8  RegimeDailyFeaturesStage — vol/liq/trend classification
  S9  RegimeFillTaggerStage    — regime label fill tagging
  S10 AttributionMetricsStage  — IS/VWAP/reversal metrics
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.ingestion.fill_ingestion import ingest_all_excel_files, process_raw_fills_for_date
from DataPipeline.src.processing.fill_aggregator import generate_agg_fills_10s
from DataPipeline.src.storage.processed_raw_bdib_db import ProcessedRawBDIBDB
from CostView.src.order_label import generate_order_label_incremental

from .base import BaseStage, _to_iso_safe
from .context import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# S1: IngestExcelStage
# ═══════════════════════════════════════════════════════════════
class IngestExcelStage(BaseStage):
    """Stage 1 (Legacy): Ingest all new Excel files into raw_fills.db."""
    @property
    def name(self) -> str: return "1. Ingest Excel (Legacy)"

    def process(self, context: PipelineContext) -> bool:
        raw_db = context.raw_db or context.db.raw_db

        results = ingest_all_excel_files(excel_dir=context.excel_dir, db=raw_db)

        context.summary["ingestion"] = {
            "results": results,
            "files_processed": len(results),
            "new_rows": sum(r.get("new_rows", 0) for r in results),
            "skipped": sum(1 for r in results if r.get("skipped", False)),
        }
        return True


# ═══════════════════════════════════════════════════════════════
# S2: ProcessRawFillsStage
# ═══════════════════════════════════════════════════════════════
class ProcessRawFillsStage(BaseStage):
    """Stage 2: Process raw fills -> processed fills."""
    @property
    def name(self) -> str: return "2. Process Raw Fills -> Clean -> Enrich"

    def process(self, context: PipelineContext) -> bool:
        raw_reader = context.db.raw_fills_read
        fills_reader = context.db.fills_read

        all_raw_dates = raw_reader.get_all_source_dates()
        if not all_raw_dates:
            logger.info("No dates in raw_fills.db to process")
            context.summary["processing"] = {"rows_processed": 0}
            return True

        if context.target_dates:
            target_dates = [d for d in context.target_dates if d in all_raw_dates]
        elif context.force:
            target_dates = all_raw_dates
        else:
            target_dates = fills_reader.get_unprocessed_dates(all_raw_dates, stage="processed")

        if not target_dates:
            logger.info("All dates already processed")
            context.summary["processing"] = {"rows_processed": 0}
            return True

        logger.info(f"Processing {len(target_dates)} dates: {target_dates}")

        total_processed = 0
        total_order_history = 0
        total_route_history = 0
        total_route_events = 0
        max_workers = min(Config.MAX_PARALLEL_DATES, len(target_dates))

        def _process_one(date_str: str) -> dict:
            """Process a single date with its own DB connections."""
            return process_raw_fills_for_date(date_str, raw_db=context.db.raw_db, proc_db=context.db.proc_db)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {executor.submit(_process_one, d): d for d in target_dates}
            for future in as_completed(future_to_date):
                date_str = future_to_date[future]
                try:
                    result = future.result()
                    if result["success"]:
                        total_processed += result["rows_processed"]
                        total_order_history += result.get("order_history_rows", 0)
                        total_route_history += result.get("route_history_rows", 0)
                        total_route_events += result.get("route_event_rows", 0)
                    else:
                        logger.error(f"  Failed to process {date_str}: {result.get('error')}")
                except Exception as exc:
                    logger.error(f"  Exception processing {date_str}: {exc}")

        context.summary["processing"] = {
            "rows_processed": total_processed,
            "order_history_rows": total_order_history,
            "route_history_rows": total_route_history,
            "route_event_rows": total_route_events,
        }
        return True


# ═══════════════════════════════════════════════════════════════
# S3: AggregateFillsStage
# ═══════════════════════════════════════════════════════════════
class AggregateFillsStage(BaseStage):
    """Stage 3: Generate route-level 10s aggregation."""
    @property
    def name(self) -> str: return "3. Aggregate (route-level 10s)"

    def process(self, context: PipelineContext) -> bool:
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write

        if context.target_dates:
            target_dates = context.target_dates
        elif context.force:
            target_dates = fills_reader.get_processed_dates(stage="processed")
        else:
            processed_dates = fills_reader.get_processed_dates(stage="processed")
            target_dates = fills_reader.get_unprocessed_dates(processed_dates, stage="aggregated")

        if not target_dates:
            logger.info("No dates to aggregate")
            context.summary["aggregation"] = {"completed": True, "dates": 0}
            return True

        logger.info(f"Aggregating {len(target_dates)} dates")

        max_workers = min(Config.MAX_PARALLEL_DATES, len(target_dates))
        aggregate_write_lock = threading.Lock()

        def _aggregate_one(date_str: str) -> tuple[str, int]:
            """Aggregate a single date with its own DB connections."""
            local_reader = context.db.fills_read
            local_writer = context.db.fills_write
            processed_df = local_reader.get_fills_for_date(date_str)
            if processed_df.empty:
                return date_str, 0

            agg_10s = generate_agg_fills_10s(processed_df)
            with aggregate_write_lock:
                if not agg_10s.empty:
                    local_writer.upsert_agg_fills_10s(agg_10s)
                local_writer.mark_date_processed(
                    date_str,
                    stage="aggregated",
                    row_count=len(agg_10s),
                )

            return date_str, len(agg_10s)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {executor.submit(_aggregate_one, d): d for d in target_dates}
            for future in as_completed(future_to_date):
                date_str = future_to_date[future]
                try:
                    date_str, count = future.result()
                    logger.info(f"  Aggregated {date_str}: {count} 10s rows")
                except Exception as exc:
                    logger.error(f"  Error aggregating date {date_str}: {exc}")

        context.summary["aggregation"] = {"completed": True, "dates": len(target_dates)}
        return True


# ═══════════════════════════════════════════════════════════════
# S4: GenerateOrderLabelsStage
# ═══════════════════════════════════════════════════════════════
class GenerateOrderLabelsStage(BaseStage):
    """Stage 4: Generate order labels."""
    @property
    def name(self) -> str: return "4. Generate Order Labels"

    def process(self, context: PipelineContext) -> bool:
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write

        if context.target_dates:
            target_label_dates = context.target_dates
        else:
            # Optimisation: only regenerate labels for dates processed in the current run
            # instead of reading the entire processed_fills table.
            processing_info = context.summary.get("processing", {})
            aggregation_info = context.summary.get("aggregation", {})
            if processing_info.get("rows_processed", 0) > 0:
                # Use the dates S2 actually processed (available from get_processed_dates)
                target_label_dates = fills_reader.get_processed_dates(stage="processed")
            else:
                target_label_dates = None

        if target_label_dates:
            dfs = [fills_reader.get_fills_for_date(d) for d in target_label_dates]
            processed_fills = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        else:
            processed_fills = fills_reader.get_all_processed_fills()

        if processed_fills.empty:
            logger.info("No processed fills for order label generation")
            context.summary["order_labels"] = {"orders": 0}
            return True

        existing_labels = None if context.force else fills_reader.get_order_labels()
        order_labels = generate_order_label_incremental(processed_fills, existing_labels)

        if not order_labels.empty:
            fills_writer.upsert_order_labels(order_labels)

        logger.info(f"Order labels generated: {len(order_labels)} orders")
        context.summary["order_labels"] = {"orders": len(order_labels)}
        return True


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
        # 延迟加载，避免无Bloomberg环境时报错
        try:
            from .bdib_fetcher import fetch_bdib_for_fills, get_bdib_for_date
            from .fill_bdib_integrated import integrate_fills_bdib_for_date
        except ImportError as e:
            logger.warning(f"Skipping BDIB Integration due to ImportError: {e}")
            context.summary["bdib"] = {"skipped": True, "error": str(e)}
            return True

        # ── Initialize all three BDIB database layers ──
        # Layer 1: raw_bdib (Bloomberg-native columns only)
        raw_bdib_db = context.raw_bdib_db or context.db.raw_bdib_db
        # Layer 2: processed_raw_bdib (raw + vwap/fluctuation/log_chg)
        processed_raw_bdib_db = context.processed_raw_bdib_db or context.db.processed_raw_bdib_db
        # Layer 3: fill_bdib (fills + processed_bdib integration + TCA)
        proc_bdib_db = context.proc_bdib_db or context.db.fill_bdib_db
        # Also need proc_db for date tracking
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write

        # ── Determine target dates with proper incremental filtering per layer ──
        # Each BDIB layer has its own incremental state:
        #   Layer 1 (raw_bdib):       get_latest_order_as_of_date()
        #   Layer 2 (processed_raw): get_latest_order_as_of_date()
        #   Layer 3 (fill_bdib):      check via proc_db.get_processed_dates()
        latest_safe_bdib_date = self._get_latest_safe_bdib_date()
        latest_safe_bdib_str = latest_safe_bdib_date.strftime("%Y%m%d")

        if context.target_dates:
            # Caller explicitly provided dates — use them as candidate set
            # but still apply incremental filtering within each phase
            all_candidate_dates = sorted({str(d) for d in context.target_dates if str(d)})
            unsafe_dates = [d for d in all_candidate_dates if d > latest_safe_bdib_str]
            if unsafe_dates:
                logger.info(
                    f"Skipping {len(unsafe_dates)} unsafe BDIB target date(s) newer than "
                    f"{latest_safe_bdib_str}: {unsafe_dates[:5]}"
                )
                all_candidate_dates = [d for d in all_candidate_dates if d <= latest_safe_bdib_str]
            logger.info(
                f"Caller provided {len(all_candidate_dates)} candidate date(s); "
                f"incremental filter applied per layer"
            )
        else:
            # Auto-detect: use raw_bdib's latest date as baseline
            latest_raw = raw_bdib_db.get_latest_order_as_of_date()

            if context.force or not latest_raw:
                start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)
                logger.info(
                    f"BDIB first-run window: {start_dt.strftime('%Y%m%d')} -> {latest_safe_bdib_date.strftime('%Y%m%d')} "
                    f"({len(all_candidate_dates)} dates)"
                )
            else:
                try:
                    latest_dt = datetime.strptime(latest_raw, "%Y%m%d").date()
                    start_dt = latest_dt + timedelta(days=1)
                except ValueError:
                    start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)
                logger.info(
                    f"BDIB incremental window: {start_dt.strftime('%Y%m%d')} -> "
                    f"{latest_safe_bdib_date.strftime('%Y%m%d')} ({len(all_candidate_dates)} new dates)"
                )

        if not all_candidate_dates:
            logger.info("No dates for BDIB integration")
            context.summary["bdib"] = {"completed": True, "dates": 0}
            return True

        logger.info(f"BDIB integration: {len(all_candidate_dates)} candidate dates")

        # ── Pre-filter: get each layer's latest processed date ──
        latest_raw_date = raw_bdib_db.get_latest_order_as_of_date()
        latest_proc_raw_date = processed_raw_bdib_db.get_latest_order_as_of_date()
        # For fill_bdib, check which dates are already marked as bdib_integrated
        try:
            already_integrated = set(
                fills_reader.get_processed_dates(stage="bdib_integrated")
                or []
            )
        except Exception:
            already_integrated = set()

        bdid_exchange = [str(e).strip().upper() for e in Config.BDID_EXCHANGE if str(e).strip()]
        ticker_exchange_map_all = fills_reader.get_ticker_exchange_map(exchanges=bdid_exchange)
        if not ticker_exchange_map_all:
            logger.warning(
                f"No ticker_repository entries matched BDID_EXCHANGE={bdid_exchange}; skip raw BDIB fetch"
            )
            context.summary["bdib"] = {
                "completed": True,
                "dates": len(all_candidate_dates),
                "raw_bdib_rows": 0,
                "processed_raw_bdib_rows": 0,
                "fill_bdib_rows": 0,
            }
            return True

        total_raw_bdib_rows = 0
        total_processed_raw_bdib_rows = 0
        total_fill_bdib_rows = 0
        skipped_raw = 0
        skipped_proc_raw = 0
        skipped_fill = 0

        for date_str in all_candidate_dates:
            try:
                # ── Per-layer incremental filtering ──
                # Layer 1: raw_bdib — skip if date already exists (unless force)
                if not context.force and latest_raw_date and date_str <= latest_raw_date:
                    skipped_raw += 1
                    continue
                # Layer 2: processed_raw_bdib — skip if already processed
                if not context.force and latest_proc_raw_date and date_str <= latest_proc_raw_date:
                    skipped_proc_raw += 1
                    continue
                # Layer 3: fill_bdib — skip if already integrated (via proc_db tracking)
                if not context.force and date_str in already_integrated:
                    skipped_fill += 1
                    continue

                ticker_dates = {ticker: [date_str] for ticker in ticker_exchange_map_all.keys()}
                ticker_exchange_map = ticker_exchange_map_all

                # ── Phase A: Fetch from Bloomberg → raw_bdib.db ──
                bdib_map = (
                    fetch_bdib_for_fills(
                        ticker_dates,
                        interval=10,
                        ticker_exchange_map=ticker_exchange_map,
                    )
                    if ticker_dates
                    else {}
                )
                bdib_df = get_bdib_for_date(bdib_map, date_str) if bdib_map else pd.DataFrame()

                raw_bdib_rows = 0
                if not bdib_df.empty:
                    raw_bdib_rows = raw_bdib_db.upsert_bdib_data(bdib_df, date_str=date_str)

                # ── Phase B: raw_bdib → processed_raw_bdib (add derived fields) ──
                proc_raw_bdib_rows = 0
                if not bdib_df.empty:
                    # Compute vwap, fluctuation, log_chg_pct_10s
                    bdib_enriched = ProcessedRawBDIBDB.compute_derived_fields(bdib_df)
                    proc_raw_bdib_rows = processed_raw_bdib_db.upsert_processed_bdib(
                        bdib_enriched
                    )

                # ── Phase C: processed_raw_bdib + agg_fills → fill_bdib (TCA) ──
                # Requires valid BDIB data from Phase A; if Phase A returned empty,
                # we skip integration rather than retrying with a different strategy.
                if bdib_df.empty:
                    total_raw_bdib_rows += raw_bdib_rows
                    total_processed_raw_bdib_rows += proc_raw_bdib_rows
                    logger.warning(
                        f"  BDIB {date_str}: no data from Phase A, skipping fill-bdib integration"
                    )
                    continue

                agg_df = fills_reader.get_agg_fills_10s_for_date(date_str)
                if agg_df.empty:
                    agg_df = fills_reader.get_agg_fills_for_date(date_str)  # Fallback

                if agg_df.empty:
                    total_raw_bdib_rows += raw_bdib_rows
                    total_processed_raw_bdib_rows += proc_raw_bdib_rows
                    logger.info(
                        f"  Raw BDIB {date_str}: raw={raw_bdib_rows}, "
                        f"processed={proc_raw_bdib_rows} (no aggregated fills, skip fill-bdib)"
                    )
                    continue

                # Pass enriched BDIB data (with derived fields) for TCA computation
                integrated_df = integrate_fills_bdib_for_date(
                    agg_df,
                    date_str,
                    bdib_data=bdib_enriched,
                    ticker_exchange_map=ticker_exchange_map,
                )

                total_raw_bdib_rows += raw_bdib_rows
                total_processed_raw_bdib_rows += proc_raw_bdib_rows

                fill_bdib_rows = 0
                if not integrated_df.empty:
                    fill_bdib_rows = proc_bdib_db.upsert_integrated_data(
                        integrated_df,
                        date_str=date_str,
                    )
                    total_fill_bdib_rows += fill_bdib_rows

                    fills_writer.mark_date_processed(
                        date_str, stage="bdib_integrated", row_count=len(integrated_df)
                    )
                    logger.info(
                        f"  Integrated {date_str}: {len(integrated_df)} rows "
                        f"(raw_bdib={raw_bdib_rows}, processed_raw_bdib={proc_raw_bdib_rows}, "
                        f"fill_bdib={fill_bdib_rows})"
                    )

            except Exception as e:
                logger.error(f"  Error in BDIB integration for {date_str}: {e}")

        context.summary["bdib"] = {
            "completed": True,
            "candidate_dates": len(all_candidate_dates),
            "processed_dates": len(all_candidate_dates) - skipped_raw - skipped_proc_raw - skipped_fill,
            "skipped_raw": skipped_raw,
            "skipped_processed_raw": skipped_proc_raw,
            "skipped_fill": skipped_fill,
            "raw_bdib_rows": total_raw_bdib_rows,
            "processed_raw_bdib_rows": total_processed_raw_bdib_rows,
            "fill_bdib_rows": total_fill_bdib_rows,
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
            from .downstream_interface import write_manifest
            write_manifest(updated_dates=context.target_dates)
            context.summary["manifest"] = {"written": True}
        except Exception as e:
            logger.warning(f"Manifest write failed: {e}")
            context.summary["manifest"] = {"error": str(e)}
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
            from .daily_metrics_calculator import CalculateDailyMetrics
        except ImportError as e:
            logger.warning(f"Skipping daily metrics calculation: {e}")
            context.summary["daily_metrics"] = {"skipped": True, "error": str(e)}
            return True

        calc = CalculateDailyMetrics(db=context.raw_bdib_db or context.db.raw_bdib_db,
                                     proc_db=context.db.proc_db)

        # Determine which dates to (re)compute
        if context.target_dates:
            dates_to_process = context.target_dates
        else:
            fills_reader = context.db.fills_read
            dates_to_process = fills_reader.get_processed_dates(stage="bdib_integrated")
            if not dates_to_process:
                _raw_bdib_db = context.raw_bdib_db or context.db.raw_bdib_db
                dates_to_process = _raw_bdib_db.get_distinct_dates()

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

        logger.info(f"Stage 7 complete: {total_rows} bdib_daily_summary rows upserted")
        context.summary["daily_metrics"] = {"rows": total_rows, "dates": len(dates_to_process)}
        return True


# ═══════════════════════════════════════════════════════════════
# S8: RegimeDailyFeaturesStage
# ═══════════════════════════════════════════════════════════════
class RegimeDailyFeaturesStage(BaseStage):
    """Stage 8: build daily regime features (market_index → vol/liq/trend) for target_dates.

    Reads context.config["regime"] for options:
      - skip_fetch: bool (default False) — skip Bloomberg fetch, reuse daily_market_index
      - config_version: str | None       — override active config
    """

    @property
    def name(self) -> str: return "8. Regime Daily Features (vol/liq/trend)"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 8: no target_dates; skipping")
            context.summary["regime_daily"] = {"skipped": True}
            return True
        try:
            from .regime import liquidity_regime, market_index_loader, trend_regime, vol_regime
            from .regime.config import ensure_default_config
            from .regime.run_journal import run_journal
        except ImportError as e:
            logger.warning(f"Skipping regime daily stage: {e}")
            context.summary["regime_daily"] = {"skipped": True, "error": str(e)}
            return True

        opts = context.config.get("regime", {}) or {}
        skip_fetch = bool(opts.get("skip_fetch", False))
        version = opts.get("config_version") or ensure_default_config()

        # Convert legacy 'YYYYMMDD' target_dates → ISO range.
        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            logger.warning("Stage 8: no convertible target_dates")
            return True
        start, end = min(iso_dates), max(iso_dates)

        results = {}
        if not skip_fetch:
            with run_journal("market_index_loader", config_version=version,
                             start=start, end=end) as rec:
                n = market_index_loader.load_market_index(start, end)
                rec.set_rows(n)
                results["market_index_loader"] = n
        for stage_name, fn in (
            ("vol_regime", vol_regime.classify),
            ("liquidity_regime", liquidity_regime.classify),
            ("trend_regime", trend_regime.classify),
        ):
            with run_journal(stage_name, config_version=version, start=start, end=end) as rec:
                n = fn(start, end, config_version=version)
                rec.set_rows(n)
                results[stage_name] = n

        context.summary["regime_daily"] = {"config_version": version, **results}
        return True


# ═══════════════════════════════════════════════════════════════
# S9: RegimeFillTaggerStage
# ═══════════════════════════════════════════════════════════════
class RegimeFillTaggerStage(BaseStage):
    """Stage 9: tag fills with regime labels (depends on Stage 8)."""

    @property
    def name(self) -> str: return "9. Regime Fill Tagger"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 9: no target_dates; skipping")
            return True
        try:
            from .regime import fill_regime_tagger
            from .regime.config import ensure_default_config
            from .regime.run_journal import run_journal
        except ImportError as e:
            logger.warning(f"Skipping regime tagger stage: {e}")
            context.summary["regime_tagger"] = {"skipped": True, "error": str(e)}
            return True

        opts = context.config.get("regime", {}) or {}
        version = opts.get("config_version") or ensure_default_config()

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)

        with run_journal("fill_regime_tagger", config_version=version,
                         start=start, end=end) as rec:
            s = fill_regime_tagger.tag_fills(start, end, config_version=version)
            rec.set_rows(s["rows_upserted"])
        context.summary["regime_tagger"] = s
        return True


# ═══════════════════════════════════════════════════════════════
# S10: AttributionMetricsStage
# ═══════════════════════════════════════════════════════════════
class AttributionMetricsStage(BaseStage):
    """Stage 10: per-fill attribution metrics (IS/VWAP/reversal). Depends on Stage 9."""

    @property
    def name(self) -> str: return "10. Attribution Metrics"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 10: no target_dates; skipping")
            return True
        try:
            from .attribution.writer import run_metrics
            from .attribution.repositories import (
                SqliteFillRepository,
                SqliteBarDataRepository,
                SqliteRegimeRepository,
                SqliteAttributionConfigRepository,
            )
        except ImportError as e:
            logger.warning(f"Skipping attribution metrics stage: {e}")
            context.summary["attribution_metrics"] = {"skipped": True, "error": str(e)}
            return True

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)

        s = run_metrics(
            start, end,
            fill_repo=SqliteFillRepository(),
            bar_repo=SqliteBarDataRepository(),
            regime_repo=SqliteRegimeRepository(),
            config_repo=SqliteAttributionConfigRepository(),
        )
        context.summary["attribution_metrics"] = s
        return True
