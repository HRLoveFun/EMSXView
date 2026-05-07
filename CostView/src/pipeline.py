"""
Financial Data Processing Pipeline Framework (v3 - Object-Oriented).

此模块提供了一个可扩展的、面向对象的流水线架构，用于处理 EMSX 交易记录（Fills）
与行情数据（BDIB）的获取、清洗、加工和聚合。

包含:
1. 流水线数据上下文 (PipelineContext)
2. 抽象处理阶段基类 (BaseStage)
3. 具体的处理阶段 (ProcessStage, AggregateStage 等)
4. 流水线调度器 (FinancialPipeline)
5. 兼容原 API 的辅助函数 (run_full_pipeline, run_process 等)
"""

from __future__ import annotations

import logging
import abc
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .fill_aggregator import generate_agg_fills_10s
from .fill_ingestion import ingest_all_excel_files, process_raw_fills_for_date
from .order_label import generate_order_label_incremental
from .fill_bdib_db import FillBDIBDB
from .processed_fills_db import ProcessedFillsDB
from .processed_raw_bdib_db import ProcessedRawBDIBDB
from .processing_config import ProcessingConfig as Config
from .raw_bdib_db import RawBDIBDB
from .raw_fills_db import RawFillsDB
from .db.connection import ConnectionManager

logger = logging.getLogger(__name__)


# ==========================================
# 1. 数据上下文定义 (Pipeline Context)
# ==========================================
@dataclass
class PipelineContext:
    """流水线上下文，用于在各个处理阶段之间共享状态、配置和数据源连接。"""
    
    # 基础配置
    target_dates: List[str] = field(default_factory=list)
    force: bool = False
    excel_dir: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)
    
    # 数据库连接管理器（Phase 1 新增：统一连接生命周期）
    connection_manager: Optional[ConnectionManager] = None
    
    # 数据库连接单例（保留向后兼容，内部逐步迁移到 ConnectionManager）
    raw_db: Optional[RawFillsDB] = None
    proc_db: Optional[ProcessedFillsDB] = None
    raw_bdib_db: Optional[RawBDIBDB] = None
    processed_raw_bdib_db: Optional[ProcessedRawBDIBDB] = None
    proc_bdib_db: Optional[FillBDIBDB] = None
    
    # Attribution Repository 注入（解耦后新增）
    fill_repo: Optional[Any] = None          # FillRepository Protocol
    bar_repo: Optional[Any] = None            # BarDataRepository Protocol
    regime_repo: Optional[Any] = None        # RegimeRepository Protocol
    config_repo: Optional[Any] = None        # AttributionConfigRepository Protocol
    
    # 流水线阶段性产出结果 (用于记录或供下游阶段使用)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    # 状态与错误追踪
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def get_connection_manager(self) -> ConnectionManager:
        """Get or lazily create the ConnectionManager singleton."""
        if self.connection_manager is None:
            self.connection_manager = ConnectionManager()
        return self.connection_manager

    def log_error(self, stage_name: str, error: Exception) -> None:
        """记录阶段性错误并将上下文标记为失败。"""
        self.errors.append({"stage": stage_name, "error": str(error)})
        self.is_successful = False
        logger.error(f"Error in stage '{stage_name}': {error}", exc_info=True)


# ==========================================
# 2. 抽象阶段定义 (Abstract Stage)
# ==========================================
class BaseStage(abc.ABC):
    """流水线处理阶段的抽象基类。"""
    
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """返回当前阶段的名称。"""
        pass

    def execute(self, context: PipelineContext) -> bool:
        """
        执行阶段逻辑，包含标准的日志记录和顶层错误捕获。
        返回 True 表示成功，返回 False 表示发生致命错误。
        """
        logger.info("=" * 60)
        logger.info(f"==> Starting Stage: {self.name}")
        logger.info("=" * 60)
        try:
            return self.process(context)
        except Exception as e:
            context.log_error(self.name, e)
            return False

    @abc.abstractmethod
    def process(self, context: PipelineContext) -> bool:
        """
        核心业务逻辑实现方法。必须由子类实现。
        如果返回 False，则中断后续流水线执行。
        """
        pass


# ==========================================
# 3. 具体业务阶段实现 (Concrete Stages)
# ==========================================
class IngestExcelStage(BaseStage):
    """Stage 1 (Legacy): Ingest all new Excel files into raw_fills.db."""
    @property
    def name(self) -> str: return "1. Ingest Excel (Legacy)"

    def process(self, context: PipelineContext) -> bool:
        if context.raw_db is None:
            context.raw_db = RawFillsDB()
            
        results = ingest_all_excel_files(excel_dir=context.excel_dir, db=context.raw_db)
        
        context.summary["ingestion"] = {
            "results": results,
            "files_processed": len(results),
            "new_rows": sum(r.get("new_rows", 0) for r in results),
            "skipped": sum(1 for r in results if r.get("skipped", False)),
        }
        return True


class ProcessRawFillsStage(BaseStage):
    """Stage 2: Process raw fills -> processed fills."""
    @property
    def name(self) -> str: return "2. Process Raw Fills -> Clean -> Enrich"

    def process(self, context: PipelineContext) -> bool:
        if context.raw_db is None:
            context.raw_db = RawFillsDB()
        if context.proc_db is None:
            context.proc_db = ProcessedFillsDB()
            
        all_raw_dates = context.raw_db.get_all_source_dates()
        if not all_raw_dates:
            logger.info("No dates in raw_fills.db to process")
            context.summary["processing"] = {"rows_processed": 0}
            return True

        if context.target_dates:
            target_dates = [d for d in context.target_dates if d in all_raw_dates]
        elif context.force:
            target_dates = all_raw_dates
        else:
            target_dates = context.proc_db.get_unprocessed_dates(all_raw_dates, stage="processed")

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

        def _process_date(date_str: str) -> dict:
            """Process a single date with its own DB connections."""
            local_raw = RawFillsDB()
            local_proc = ProcessedFillsDB()
            return process_raw_fills_for_date(date_str, raw_db=local_raw, proc_db=local_proc)

        if max_workers <= 1:
            for date_str in target_dates:
                result = process_raw_fills_for_date(date_str, raw_db=context.raw_db, proc_db=context.proc_db)
                if result["success"]:
                    total_processed += result["rows_processed"]
                    total_order_history += result.get("order_history_rows", 0)
                    total_route_history += result.get("route_history_rows", 0)
                    total_route_events += result.get("route_event_rows", 0)
                else:
                    logger.error(f"  Failed to process {date_str}: {result.get('error')}")
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_date = {executor.submit(_process_date, d): d for d in target_dates}
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


class AggregateFillsStage(BaseStage):
    """Stage 3: Generate route-level 10s aggregation."""
    @property
    def name(self) -> str: return "3. Aggregate (route-level 10s)"

    def process(self, context: PipelineContext) -> bool:
        if context.proc_db is None:
            context.proc_db = ProcessedFillsDB()

        if context.target_dates:
            target_dates = context.target_dates
        elif context.force:
            target_dates = context.proc_db.get_processed_dates(stage="processed")
        else:
            processed_dates = context.proc_db.get_processed_dates(stage="processed")
            target_dates = context.proc_db.get_unprocessed_dates(processed_dates, stage="aggregated")

        if not target_dates:
            logger.info("No dates to aggregate")
            context.summary["aggregation"] = {"completed": True, "dates": 0}
            return True

        logger.info(f"Aggregating {len(target_dates)} dates")
        
        max_workers = min(Config.MAX_PARALLEL_DATES, len(target_dates))
        aggregate_write_lock = threading.Lock()

        def _aggregate_date(date_str: str) -> tuple[str, int]:
            """Aggregate a single date with its own DB connection."""
            local_proc = ProcessedFillsDB()
            processed_df = local_proc.get_processed_fills_for_date(
                date_str,
                use_legacy_view=True,
            )
            if processed_df.empty:
                return date_str, 0

            agg_10s = generate_agg_fills_10s(processed_df)
            write_conn = local_proc._get_conn()
            try:
                with aggregate_write_lock:
                    if not agg_10s.empty:
                        local_proc.upsert_agg_fills_10s(agg_10s, conn=write_conn)
                    local_proc.mark_date_processed(
                        date_str,
                        stage="aggregated",
                        row_count=len(agg_10s),
                        conn=write_conn,
                    )
                    write_conn.commit()
            finally:
                write_conn.close()

            return date_str, len(agg_10s)

        if max_workers <= 1:
            for date_str in target_dates:
                try:
                    processed_df = context.proc_db.get_processed_fills_for_date(
                        date_str,
                        use_legacy_view=True,
                    )
                    if processed_df.empty:
                        continue

                    agg_10s = generate_agg_fills_10s(processed_df)
                    write_conn = context.proc_db._get_conn()
                    try:
                        if not agg_10s.empty:
                            context.proc_db.upsert_agg_fills_10s(agg_10s, conn=write_conn)
                        context.proc_db.mark_date_processed(
                            date_str,
                            stage="aggregated",
                            row_count=len(agg_10s),
                            conn=write_conn,
                        )
                        write_conn.commit()
                    finally:
                        write_conn.close()

                    logger.info(f"  Aggregated {date_str}: {len(agg_10s)} 10s rows")

                except Exception as e:
                    logger.error(f"  Error aggregating date {date_str}: {e}")
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_date = {executor.submit(_aggregate_date, d): d for d in target_dates}
                for future in as_completed(future_to_date):
                    date_str = future_to_date[future]
                    try:
                        date_str, count = future.result()
                        logger.info(f"  Aggregated {date_str}: {count} 10s rows")
                    except Exception as exc:
                        logger.error(f"  Error aggregating date {date_str}: {exc}")

        context.summary["aggregation"] = {"completed": True, "dates": len(target_dates)}
        return True


class GenerateOrderLabelsStage(BaseStage):
    """Stage 4: Generate order labels."""
    @property
    def name(self) -> str: return "4. Generate Order Labels"

    def process(self, context: PipelineContext) -> bool:
        if context.proc_db is None:
            context.proc_db = ProcessedFillsDB()

        if context.target_dates:
            target_label_dates = context.target_dates
        else:
            # Optimisation: only regenerate labels for dates processed in the current run
            # instead of reading the entire processed_fills table.
            processing_info = context.summary.get("processing", {})
            aggregation_info = context.summary.get("aggregation", {})
            if processing_info.get("rows_processed", 0) > 0:
                # Use the dates S2 actually processed (available from get_processed_dates)
                target_label_dates = context.proc_db.get_processed_dates(stage="processed")
            else:
                target_label_dates = None

        if target_label_dates:
            dfs = [context.proc_db.get_processed_fills_for_date(d) for d in target_label_dates]
            processed_fills = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        else:
            processed_fills = context.proc_db.get_all_processed_fills()

        if processed_fills.empty:
            logger.info("No processed fills for order label generation")
            context.summary["order_labels"] = {"orders": 0}
            return True

        existing_labels = None if context.force else context.proc_db.get_order_labels()
        order_labels = generate_order_label_incremental(processed_fills, existing_labels)

        if not order_labels.empty:
            context.proc_db.upsert_order_labels(order_labels)

        logger.info(f"Order labels generated: {len(order_labels)} orders")
        context.summary["order_labels"] = {"orders": len(order_labels)}
        return True


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
        if context.raw_bdib_db is None:
            context.raw_bdib_db = RawBDIBDB()
        # Layer 2: processed_raw_bdib (raw + vwap/fluctuation/log_chg)
        if context.processed_raw_bdib_db is None:
            context.processed_raw_bdib_db = ProcessedRawBDIBDB()
        # Layer 3: fill_bdib (fills + processed_bdib integration + TCA)
        if context.proc_bdib_db is None:
            context.proc_bdib_db = FillBDIBDB()

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
            latest_raw = context.raw_bdib_db.get_latest_order_as_of_date()

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
        latest_raw_date = context.raw_bdib_db.get_latest_order_as_of_date()
        latest_proc_raw_date = context.processed_raw_bdib_db.get_latest_order_as_of_date()
        # For fill_bdib, check which dates are already marked as bdib_integrated
        try:
            already_integrated = set(
                context.proc_db.get_processed_dates(stage="bdib_integrated")
                or []
            )
        except Exception:
            already_integrated = set()

        bdid_exchange = [str(e).strip().upper() for e in Config.BDID_EXCHANGE if str(e).strip()]
        ticker_exchange_map_all = context.proc_db.get_ticker_exchange_map(exchanges=bdid_exchange)
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
                    raw_bdib_rows = context.raw_bdib_db.upsert_bdib_data(bdib_df, date_str=date_str)

                # ── Phase B: raw_bdib → processed_raw_bdib (add derived fields) ──
                proc_raw_bdib_rows = 0
                if not bdib_df.empty:
                    # Compute vwap, fluctuation, log_chg_pct_10s
                    bdib_enriched = ProcessedRawBDIBDB.compute_derived_fields(bdib_df)
                    proc_raw_bdib_rows = context.processed_raw_bdib_db.upsert_processed_bdib(
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

                agg_df = context.proc_db.get_agg_fills_10s_for_date(date_str)
                if agg_df.empty:
                    agg_df = context.proc_db.get_agg_fills_for_date(date_str)  # Fallback

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
                    fill_bdib_rows = context.proc_bdib_db.upsert_integrated_data(
                        integrated_df,
                        date_str=date_str,
                    )
                    total_fill_bdib_rows += fill_bdib_rows

                    context.proc_db.mark_date_processed(
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

        calc = CalculateDailyMetrics(db=context.raw_bdib_db, proc_db=context.proc_db)

        # Determine which dates to (re)compute
        if context.target_dates:
            dates_to_process = context.target_dates
        else:
            if context.proc_db is None:
                context.proc_db = ProcessedFillsDB()
            dates_to_process = context.proc_db.get_processed_dates(stage="bdib_integrated")
            if not dates_to_process:
                if context.raw_bdib_db is None:
                    context.raw_bdib_db = RawBDIBDB()
                dates_to_process = context.raw_bdib_db.get_distinct_dates()

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

        # Create repository instances if not already injected
        if context.fill_repo is None:
            context.fill_repo = SqliteFillRepository()
        if context.bar_repo is None:
            context.bar_repo = SqliteBarDataRepository()
        if context.regime_repo is None:
            context.regime_repo = SqliteRegimeRepository()
        if context.config_repo is None:
            context.config_repo = SqliteAttributionConfigRepository()

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)

        s = run_metrics(
            start, end,
            fill_repo=context.fill_repo,
            bar_repo=context.bar_repo,
            regime_repo=context.regime_repo,
            config_repo=context.config_repo,
        )
        context.summary["attribution_metrics"] = s
        return True


def _to_iso_safe(d: str) -> Optional[str]:
    """Convert 'YYYYMMDD' or 'YYYY-MM-DD' → 'YYYY-MM-DD'; None on bad input."""
    if not d or not isinstance(d, str):
        return None
    s = d.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


# ==========================================
# 4. 流水线编排器 (Pipeline Orchestrator)
# ==========================================
class FinancialPipeline:
    """管理和按顺序执行所有处理阶段的调度器。"""
    
    def __init__(self, name: str = "默认-综合处理流水线"):
        self.name = name
        self._stages: List[BaseStage] = []

    def add_stage(self, stage: BaseStage) -> 'FinancialPipeline':
        """添加一个新的处理阶段，支持链式调用。"""
        self._stages.append(stage)
        return self

    def run(self, context: PipelineContext) -> PipelineContext:
        """顺序执行所有阶段。"""
        logger.info("=" * 60)
        logger.info(f"EMSX Pipeline Execution: [{self.name}]")
        logger.info("=" * 60)

        Config.initialize_directories()

        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        marker_start = int(context.config.get("stage_marker_start", 0))
        marker_end = int(context.config.get("stage_marker_end", 100))
        total_stages = max(1, len(self._stages))

        for index, stage in enumerate(self._stages):
            if marker_name:
                stage_progress = marker_start + int(
                    max(0, marker_end - marker_start) * (index + 1) / total_stages
                )
                print(f"[STAGE] {marker_name} {min(100, max(0, stage_progress))}", flush=True)
            success = stage.execute(context)
            if not success:
                logger.error(f"Pipeline halted at stage: {stage.name}")
                break

        logger.info("=" * 60)
        if context.is_successful:
            logger.info(f"Pipeline completed SUCCESSFULLY: {context.summary}")
        else:
            logger.warning(f"Pipeline completed with ERRORS: {len(context.errors)} issues found.")
        logger.info("=" * 60)
        
        return context


# ==========================================
# 5. 流水线工厂 (Pipeline Factory)
# ==========================================
class PipelineFactory:
    """流水线工厂类，使用'功能描述-业务领域'规范命名并装配流水线。"""

    @staticmethod
    def create_data_sync_legacy() -> FinancialPipeline:
        """创建【数据同步-历史Excel流水】流水线"""
        return FinancialPipeline("数据同步-历史Excel流水").add_stage(IngestExcelStage())

    @staticmethod
    def create_data_processing_trade_model() -> FinancialPipeline:
        """创建【数据清洗与加工-交易核心模型】流水线"""
        return FinancialPipeline("数据清洗与加工-交易核心模型").add_stage(ProcessRawFillsStage())

    @staticmethod
    def create_aggregation_order_route() -> FinancialPipeline:
        """创建【降频聚合与特征提取-订单路由视角】流水线"""
        return (FinancialPipeline("降频聚合与特征提取-订单路由视角")
                .add_stage(AggregateFillsStage())
                .add_stage(GenerateOrderLabelsStage()))

    @staticmethod
    def create_integration_tca_analysis() -> FinancialPipeline:
        """创建【多源融合-TCA成本分析】流水线"""
        return FinancialPipeline("多源融合-TCA成本分析").add_stage(IntegrateBDIBStage())

    @staticmethod
    def create_contract_downstream() -> FinancialPipeline:
        """创建【契约分发-下游行情依赖】流水线"""
        return FinancialPipeline("契约分发-下游行情依赖").add_stage(WriteManifestStage())

    @staticmethod
    def create_daily_e2e_pipeline(skip_ingest: bool = True, skip_bdib: bool = True) -> FinancialPipeline:
        """每日端到端总控调度 (组合多个子Pipeline的阶段)"""
        pipeline = FinancialPipeline("端到端全链路-日终批处理")
        
        if not skip_ingest:
            pipeline.add_stage(IngestExcelStage())
            
        pipeline.add_stage(ProcessRawFillsStage())
        pipeline.add_stage(AggregateFillsStage())
        pipeline.add_stage(GenerateOrderLabelsStage())
        
        if not skip_bdib:
            pipeline.add_stage(IntegrateBDIBStage())
            pipeline.add_stage(CalculateDailyMetricsStage())  # Stage 7: ADV + volatility

        pipeline.add_stage(WriteManifestStage())
        return pipeline

    @staticmethod
    def create_regime_classification(skip_fetch: bool = False) -> FinancialPipeline:
        """Regime layer: market_index → vol/liq/trend → fill labels."""
        pipeline = FinancialPipeline("行情分类与标签-Regime层")
        pipeline.add_stage(RegimeDailyFeaturesStage())
        pipeline.add_stage(RegimeFillTaggerStage())
        return pipeline

    @staticmethod
    def create_attribution() -> FinancialPipeline:
        """Attribution layer: per-fill IS/VWAP/reversal metrics."""
        pipeline = FinancialPipeline("绩效归因-Attribution层")
        pipeline.add_stage(AttributionMetricsStage())
        return pipeline


# ==========================================
# 6. 兼容层API (Backward Compatibility / Runners)
# ==========================================

def run_ingest(excel_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Legacy compatibility: Ingest Excel files."""
    ctx = PipelineContext(excel_dir=excel_dir)
    pipeline = PipelineFactory.create_data_sync_legacy()
    pipeline.run(ctx)
    return ctx.summary.get("ingestion", {}).get("results", [])


def run_process(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Process raw fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = PipelineFactory.create_data_processing_trade_model()
    pipeline.run(ctx)
    
    # Return empty DataFrame as placeholder, caller should query DB directly
    if ctx.proc_db and ctx.target_dates:
        dfs = [ctx.proc_db.get_processed_fills_for_date(d) for d in ctx.target_dates]
        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    return pd.DataFrame()


def run_aggregate(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Aggregate fills."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    # Note: the factory pipeline also runs OrderLabels, we keep just aggregate for legacy compatibility
    pipeline = FinancialPipeline("降频聚合-订单路由视角(单阶段)").add_stage(AggregateFillsStage())
    pipeline.run(ctx)


def run_order_labels(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Legacy compatibility: Generate order labels."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = FinancialPipeline("特征提取-全局订单标签(单阶段)").add_stage(GenerateOrderLabelsStage())
    pipeline.run(ctx)
    if ctx.proc_db:
        return ctx.proc_db.get_order_labels()
    return pd.DataFrame()


def run_bdib_integration(
    dates: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """Legacy compatibility: Integrate BDIB data."""
    ctx = PipelineContext(target_dates=dates or [], force=force)
    pipeline = PipelineFactory.create_integration_tca_analysis()
    pipeline.run(ctx)


def run_full_pipeline(
    excel_dir: Optional[Path] = None,
    dates: Optional[List[str]] = None,
    force: bool = False,
    skip_bdib: bool = True,
    skip_ingest: bool = True,
    stage_marker_name: Optional[str] = None,
    stage_marker_start: int = 0,
    stage_marker_end: int = 100,
) -> Dict[str, Any]:
    """
    Run the complete pipeline using the new Object-Oriented Framework.
    """
    ctx = PipelineContext(
        target_dates=dates or [],
        force=force,
        excel_dir=excel_dir,
        config={
            "stage_marker_name": stage_marker_name,
            "stage_marker_start": stage_marker_start,
            "stage_marker_end": stage_marker_end,
        },
    )
    
    pipeline = PipelineFactory.create_daily_e2e_pipeline(
        skip_ingest=skip_ingest,
        skip_bdib=skip_bdib
    )
    
    if skip_ingest:
        ctx.summary["ingestion"] = {"skipped": True}
    if skip_bdib:
        ctx.summary["bdib"] = {"skipped": True}
    
    # 执行流水线
    pipeline.run(ctx)
    return ctx.summary


def run_incremental(
    excel_dir: Optional[Path] = None,
    skip_bdib: bool = True,
    stage_marker_name: Optional[str] = None,
    stage_marker_start: int = 0,
    stage_marker_end: int = 100,
) -> Dict[str, Any]:
    """Run incremental pipeline - only process new/changed data."""
    return run_full_pipeline(
        excel_dir=excel_dir,
        dates=None,
        force=False,
        skip_bdib=skip_bdib,
        skip_ingest=True,
        stage_marker_name=stage_marker_name,
        stage_marker_start=stage_marker_start,
        stage_marker_end=stage_marker_end,
    )


def get_pipeline_status() -> Dict[str, Any]:
    """Get current status of the processing pipeline."""
    status: Dict[str, Any] = {}
    mgr = ConnectionManager()

    try:
        raw_db = RawFillsDB()
        status["raw_fills"] = {
            "total_rows": raw_db.get_row_count(),
            "dates": raw_db.get_all_source_dates(),
            "date_counts": raw_db.get_date_row_counts(),
        }
        fetch_log = raw_db.get_fetch_log_stats()
        status["fetch_log"] = {
            "entries": len(fetch_log),
            "latest": fetch_log[0] if fetch_log else None,
        }
    except Exception as e:
        status["raw_fills"] = {"error": str(e)}

    try:
        proc_db = ProcessedFillsDB()
        stats = proc_db.get_processing_stats()
        status["processed_fills"] = stats
    except Exception as e:
        status["processed_fills"] = {"error": str(e)}

    # ── BDIB pipeline (3-layer) status ──
    try:
        raw_bdib_db = RawBDIBDB()
        status["raw_bdib"] = {
            "total_rows": raw_bdib_db.get_row_count(),
            "db_path": str(mgr.get_path("raw_bdib")),
        }
    except Exception as e:
        status["raw_bdib"] = {"error": str(e)}

    try:
        proc_raw_bdib_db = ProcessedRawBDIBDB()
        status["processed_raw_bdib"] = {
            "total_rows": proc_raw_bdib_db.get_row_count(),
            "db_path": str(mgr.get_path("processed_raw_bdib")),
        }
    except Exception as e:
        status["processed_raw_bdib"] = {"error": str(e)}

    try:
        # Use FillBDIBDB directly; ProcessedBDIBDB is a legacy alias
        fill_bdib_db = FillBDIBDB()
        status["fill_bdib"] = {
            "total_rows": fill_bdib_db.get_row_count(),
            "db_path": str(mgr.get_path("fill_bdib")),
        }
        # Backward-compatible key for existing consumers
        status["processed_bdib"] = status["fill_bdib"]
    except Exception as e:
        status["fill_bdib"] = {"error": str(e)}
        status["processed_bdib"] = {"error": str(e)}

    return status
