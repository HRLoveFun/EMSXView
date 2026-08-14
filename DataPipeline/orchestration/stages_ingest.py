"""
Ingest & aggregation stages (S1–S4).

S1  IngestExcelStage         — [DEPRECATED v2.0 移除] Excel ingestion into raw_fills.db
S2  ProcessRawFillsStage     — raw → processed fills
S3  AggregateFillsStage      — route-level 10s aggregation
S4  GenerateOrderLabelsStage — order-level labels
"""

from __future__ import annotations

import gc
import logging
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier
from DataPipeline.ingestion.fill_ingestion import ingest_all_excel_files, process_raw_fills_for_date
from DataPipeline.processing.fill_aggregator import generate_agg_fills_10s
from DataPipeline.processing.order_label import generate_order_label_incremental

from .base import BaseStage
from .context import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# S1: IngestExcelStage
# ═══════════════════════════════════════════════════════════════
class IngestExcelStage(BaseStage):
    """Stage 1 (Legacy, DEPRECATED): Ingest all new Excel files into raw_fills.db.

    .. deprecated::
        `IngestExcelStage` is deprecated and will be removed in v2.0.
        Data must be ingested from Bloomberg API via `fill_fetch.py`, not from Excel.
        Default pipeline already skips this stage (`skip_ingest=True`).
    """
    @property
    def name(self) -> str: return "1. Ingest Excel (Legacy)"

    def process(self, context: PipelineContext) -> bool:
        warnings.warn(
            "IngestExcelStage is deprecated and will be removed in v2.0. "
            "Data must be ingested from Bloomberg API via fill_fetch.py, not from Excel.",
            DeprecationWarning,
            stacklevel=2,
        )
        from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository
        from DataPipeline.storage.repositories.raw_fills import SqliteRawFillWriteRepository
        cm = context.connection_manager
        raw_fill_write = SqliteRawFillWriteRepository(cm) if cm else SqliteRawFillWriteRepository()

        from DataPipeline.ingestion.fill_ingestion import ingest_all_excel_files
        results = ingest_all_excel_files(excel_dir=context.excel_dir)

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

        # v2.0 修复: target_dates 维度从 source_date 改为 order_as_of_date
        # S1 (Bloomberg 拉取) 以 source_date 为单位，一个 source_date 可能覆盖多交易日成交。
        # S2 目标 schema 为 processed_fills.order_as_of_date (真实交易日)，旧逻转用 source_date 会导致跨日数据被拒绝。
        all_raw_dates = raw_reader.get_distinct_order_as_of_dates()
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
        total_route_history = 0
        total_route_events = 0
        # M1: 输出样本收集 (护栏输出校验臂)
        output_samples: list[dict] = []
        max_workers = min(Config.MAX_PARALLEL_DATES, len(target_dates))

        def _process_one(date_str: str) -> dict:
            """Process a single date with its own DB connections."""
            result = process_raw_fills_for_date(date_str)
            gc.collect()
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {executor.submit(_process_one, d): d for d in target_dates}
            for future in as_completed(future_to_date):
                date_str = future_to_date[future]
                try:
                    result = future.result()
                    if result["success"]:
                        total_processed += result["rows_processed"]
                        # PR-1: order_history 是 route_history 的 VIEW 派生，无独立行数
                        total_route_history += result.get("route_history_rows", 0)
                        total_route_events += result.get("route_event_rows", 0)
                        output_samples.extend(result.get("sample_records") or [])
                    else:
                        logger.error(f"  Failed to process {date_str}: {result.get('error')}")
                except Exception as exc:
                    logger.error(f"  Exception processing {date_str}: {exc}")

        # M1: 暴露输出样本 (最多 100 条) 供护栏校验
        self._output_sample = output_samples[:100]
        gc.collect()
        context.summary["processing"] = {
            "rows_processed": total_processed,
            # PR-1: order_history 已是 VIEW，无独立行数；保留 0 以兼容前端 summary 字段
            "order_history_rows": 0,
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
            processed_dates = fills_reader.get_distinct_fill_dates()
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
            del processed_df
            with aggregate_write_lock:
                if not agg_10s.empty:
                    local_writer.upsert_agg_fills_10s(agg_10s)
                local_writer.mark_date_processed(
                    date_str,
                    stage="aggregated",
                    row_count=len(agg_10s),
                )

            gc.collect()
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
    """Stage 4: Generate order labels (date-by-date to avoid OOM)."""
    @property
    def name(self) -> str: return "4. Generate Order Labels"

    def process(self, context: PipelineContext) -> bool:
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write

        if context.target_dates:
            target_label_dates = context.target_dates
        else:
            # Incremental: only process dates whose fills are NOT yet labelled.
            # Query the order_label table to find which dates already have
            # labels, then intersect with processed dates to find new work.
            all_processed_dates = fills_reader.get_distinct_fill_dates()
            if not all_processed_dates:
                logger.info("No processed dates for order label generation")
                context.summary["order_labels"] = {"orders": 0}
                return True

            try:
                # B4迁移后 order_label 已迁至 ticker_registry.db
                conn = context.connection_manager.get_connection(
                    "ticker_registry", AccessTier.READ,
                )
                already_labelled = set(
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT order_as_of_date FROM order_label"
                    ).fetchall()
                )
            except Exception:
                logger.warning("查询已标注日期失败，将视为全新处理")
                already_labelled = set()

            target_label_dates = [
                d for d in all_processed_dates if d not in already_labelled
            ]
            if not target_label_dates:
                logger.info(
                    "All %d processed dates already labelled — skipping",
                    len(all_processed_dates),
                )
                context.summary["order_labels"] = {"orders": 0}
                return True

        logger.info(f"Generating order labels for {len(target_label_dates)} dates (per-date processing)")

        try:
            existing_labels = None if context.force else fills_reader.get_order_labels()
        except Exception:
            logger.warning("获取已有order_label失败，将重新生成")
            existing_labels = None
        total_orders = 0

        # 进度报告：逐日期处理，输出 [STAGE] 避免前端误判 stalled
        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        total_label_dates = max(1, len(target_label_dates))

        # Process each date individually to keep peak memory low
        for date_idx, d in enumerate(target_label_dates):
            if marker_name:
                stage_pct = 71 + int((date_idx / total_label_dates) * 4)
                print(
                    f"[STAGE] {marker_name} {stage_pct} "
                    f"Labels date {date_idx + 1}/{total_label_dates}: {d}",
                    flush=True,
                )
            try:
                df_day = fills_reader.get_fills_for_date(d)
                if df_day.empty:
                    continue
                day_labels = generate_order_label_incremental(df_day, existing_labels)
                if day_labels is not None and not day_labels.empty:
                    fills_writer.upsert_order_labels(day_labels)
                    total_orders += len(day_labels)
                    existing_labels = day_labels  # carry forward for next date
                del df_day, day_labels
                gc.collect()
            except Exception as exc:
                logger.error(f"  Error generating order labels for {d}: {exc}")

        logger.info(f"Order labels generated: {total_orders} total orders across {len(target_label_dates)} dates")
        context.summary["order_labels"] = {"orders": total_orders}
        return True
