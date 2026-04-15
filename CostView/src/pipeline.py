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
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .fill_aggregator import generate_agg_fills_10s
from .fill_ingestion import ingest_all_excel_files, process_raw_fills_for_date
from .order_label import generate_order_label_incremental
from .fill_bdib_db import FillBDIBDB
from .processed_bdib_db import ProcessedBDIBDB  # backward-compat alias for FillBDIBDB
from .processed_fills_db import ProcessedFillsDB
from .processed_raw_bdib_db import ProcessedRawBDIBDB
from .processing_config import ProcessingConfig as Config
from .raw_bdib_db import RawBDIBDB
from .raw_fills_db import RawFillsDB

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
    
    # 数据库连接单例
    raw_db: Optional[RawFillsDB] = None
    proc_db: Optional[ProcessedFillsDB] = None
    raw_bdib_db: Optional[RawBDIBDB] = None
    processed_raw_bdib_db: Optional[ProcessedRawBDIBDB] = None
    proc_bdib_db: Optional[ProcessedBDIBDB] = None  # alias for FillBDIBDB
    
    # 流水线阶段性产出结果 (用于记录或供下游阶段使用)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    # 状态与错误追踪
    is_successful: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)

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
        for date_str in target_dates:
            result = process_raw_fills_for_date(date_str, raw_db=context.raw_db, proc_db=context.proc_db)
            if result["success"]:
                total_processed += result["rows_processed"]
            else:
                logger.error(f"  Failed to process {date_str}: {result.get('error')}")

        context.summary["processing"] = {"rows_processed": total_processed}
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
        
        for date_str in target_dates:
            try:
                # Use legacy compatibility view so equ_ticker/ccy_ticker from
                # route_registry are present for downstream BDIB integration.
                processed_df = context.proc_db.get_processed_fills_for_date(
                    date_str,
                    use_legacy_view=True,
                )
                if processed_df.empty:
                    continue

                agg_10s = generate_agg_fills_10s(processed_df)
                if not agg_10s.empty:
                    context.proc_db.upsert_agg_fills_10s(agg_10s)

                context.proc_db.mark_date_processed(date_str, stage="aggregated", row_count=len(agg_10s))
                logger.info(f"  Aggregated {date_str}: {len(agg_10s)} 10s rows")

            except Exception as e:
                logger.error(f"  Error aggregating date {date_str}: {e}")

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
            dfs = [context.proc_db.get_processed_fills_for_date(d) for d in context.target_dates]
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

        if context.target_dates:
            target_dates = sorted({str(d) for d in context.target_dates if str(d)})
        else:
            prev_weekday = self._get_previous_weekday()
            latest_raw_bdib_date = context.raw_bdib_db.get_latest_order_as_of_date()

            if context.force or not latest_raw_bdib_date:
                start_dt = prev_weekday - timedelta(days=180)
                target_dates = self._expand_weekdays(start_dt, prev_weekday)
                logger.info(
                    f"BDIB first update window: {start_dt.strftime('%Y%m%d')} -> {prev_weekday.strftime('%Y%m%d')}"
                )
            else:
                try:
                    latest_dt = datetime.strptime(latest_raw_bdib_date, "%Y%m%d").date()
                    start_dt = latest_dt + timedelta(days=1)
                except ValueError:
                    start_dt = prev_weekday - timedelta(days=180)
                target_dates = self._expand_weekdays(start_dt, prev_weekday)
                logger.info(
                    f"BDIB daily update window: {start_dt.strftime('%Y%m%d')} -> {prev_weekday.strftime('%Y%m%d')}"
                )

        if not target_dates:
            logger.info("No dates for BDIB integration")
            context.summary["bdib"] = {"completed": True, "dates": 0}
            return True

        logger.info(f"BDIB integration for {len(target_dates)} dates")

        bdid_exchange = [str(e).strip().upper() for e in Config.BDID_EXCHANGE if str(e).strip()]
        ticker_exchange_map_all = context.proc_db.get_ticker_exchange_map(exchanges=bdid_exchange)
        if not ticker_exchange_map_all:
            logger.warning(
                f"No ticker_repository entries matched BDID_EXCHANGE={bdid_exchange}; skip raw BDIB fetch"
            )
            context.summary["bdib"] = {
                "completed": True,
                "dates": len(target_dates),
                "raw_bdib_rows": 0,
                "processed_raw_bdib_rows": 0,
                "fill_bdib_rows": 0,
            }
            return True

        total_raw_bdib_rows = 0
        total_processed_raw_bdib_rows = 0
        total_fill_bdib_rows = 0

        for date_str in target_dates:
            try:
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

                # Use enriched BDIB data for integration; fallback to fetch on demand
                if bdib_df.empty:
                    integrated_df = integrate_fills_bdib_for_date(
                        agg_df,
                        date_str,
                        ticker_exchange_map=ticker_exchange_map,
                    )
                else:
                    # Pass enriched BDIB (with derived fields) for TCA computation
                    integrated_df = integrate_fills_bdib_for_date(
                        agg_df,
                        date_str,
                        bdib_data=bdib_enriched,
                        ticker_exchange_map=ticker_exchange_map,
                    )

                # Fallback: materialize unique BDIB bars into raw_bdib if needed
                if raw_bdib_rows == 0 and not integrated_df.empty:
                    bar_cols = [
                        "equ_ticker", "order_as_of_date", "mkt_timestamp",
                        "open", "high", "low", "close",
                        "volume", "num_trds", "value",
                    ]
                    available_cols = [c for c in bar_cols if c in integrated_df.columns]
                    if {"equ_ticker", "mkt_timestamp"}.issubset(set(available_cols)):
                        raw_from_integrated = integrated_df[available_cols].copy()
                        if "order_as_of_date" not in raw_from_integrated.columns:
                            raw_from_integrated["order_as_of_date"] = date_str
                        market_cols = [
                            c for c in ["open", "high", "low", "close", "volume", "value"]
                            if c in raw_from_integrated.columns
                        ]
                        if market_cols:
                            raw_from_integrated = raw_from_integrated[
                                raw_from_integrated[market_cols].notna().any(axis=1)
                            ]
                        if not raw_from_integrated.empty:
                            raw_from_integrated["equ_ticker"] = raw_from_integrated["equ_ticker"].astype(str)
                            raw_from_integrated["mkt_timestamp"] = raw_from_integrated["mkt_timestamp"].astype(str)
                            raw_from_integrated = raw_from_integrated[
                                raw_from_integrated["equ_ticker"].str.strip().ne("")
                                & raw_from_integrated["equ_ticker"].str.lower().ne("none")
                                & raw_from_integrated["equ_ticker"].str.lower().ne("nan")
                                & raw_from_integrated["mkt_timestamp"].str.strip().ne("")
                                & raw_from_integrated["mkt_timestamp"].str.lower().ne("none")
                                & raw_from_integrated["mkt_timestamp"].str.lower().ne("nan")
                            ]
                            if not raw_from_integrated.empty:
                                raw_from_integrated = raw_from_integrated.drop_duplicates(
                                    subset=["equ_ticker", "order_as_of_date", "mkt_timestamp"]
                                )
                                raw_bdib_rows = context.raw_bdib_db.upsert_bdib_data(
                                    raw_from_integrated,
                                    date_str=date_str,
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
            "dates": len(target_dates),
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

        for stage in self._stages:
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
            
        pipeline.add_stage(WriteManifestStage())
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
) -> Dict[str, Any]:
    """
    Run the complete pipeline using the new Object-Oriented Framework.
    """
    ctx = PipelineContext(
        target_dates=dates or [],
        force=force,
        excel_dir=excel_dir,
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
) -> Dict[str, Any]:
    """Run incremental pipeline - only process new/changed data."""
    return run_full_pipeline(
        excel_dir=excel_dir,
        dates=None,
        force=False,
        skip_bdib=skip_bdib,
        skip_ingest=True,
    )


def get_pipeline_status() -> Dict[str, Any]:
    """Get current status of the processing pipeline."""
    status: Dict[str, Any] = {}

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
            "db_path": str(Config.RAW_BDIB_DB),
        }
    except Exception as e:
        status["raw_bdib"] = {"error": str(e)}

    try:
        proc_raw_bdib_db = ProcessedRawBDIBDB()
        status["processed_raw_bdib"] = {
            "total_rows": proc_raw_bdib_db.get_row_count(),
            "db_path": str(Config.PROCESSED_RAW_BDIB_DB),
        }
    except Exception as e:
        status["processed_raw_bdib"] = {"error": str(e)}

    try:
        # Use FillBDIBDB directly; ProcessedBDIBDB is a legacy alias
        fill_bdib_db = FillBDIBDB()
        status["fill_bdib"] = {
            "total_rows": fill_bdib_db.get_row_count(),
            "db_path": str(Config.FILL_BDIB_DB),
        }
        # Backward-compatible key for existing consumers
        status["processed_bdib"] = status["fill_bdib"]
    except Exception as e:
        status["fill_bdib"] = {"error": str(e)}
        status["processed_bdib"] = {"error": str(e)}

    return status
