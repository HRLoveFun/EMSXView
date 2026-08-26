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
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier
from DataPipeline.processing.tca_route_metrics import compute_route_metrics_for_date, load_raw_bdib_for_date
from DataPipeline.storage.repositories.bdib_fetch_history import (
    SqliteBdibFetchHistoryRepository,
    compute_bdib_data_hash,
)


from .base import BaseStage, _to_iso_safe
from .context import PipelineContext

if TYPE_CHECKING:
    # 仅类型标注用：fx_rates 汇率表仓储（fx-rate-persistence）
    from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository

logger = logging.getLogger(__name__)


def _load_daily_summary_for_metrics(
    cm, date_str: str, equ_tickers: Optional[List[str]],
) -> Optional[pd.DataFrame]:
    """加载 bdib_daily_summary 供 TCA 路由指标计算使用。

    003-tca-core-benchmarks:
    - Phase 0 需要当日 daily_close（收盘价基准 / 机会成本）
    - Phase 1 需要下一交易日 daily_close（跨日次日收盘恢复窗口）

    加载区间 [date_str, date_str + 10 日历日]，覆盖下一交易日的 daily_close。
    """
    from DataPipeline.storage.repositories.market_data import SqliteMarketDataReadRepository

    reader = SqliteMarketDataReadRepository(cm)
    start = date_str
    base = datetime.strptime(date_str, Config.DATE_FORMAT)
    end = (base + timedelta(days=10)).strftime(Config.DATE_FORMAT)
    df = reader.get_daily_summary_for_date_range(start, end, equ_tickers)
    return df if df is not None and not df.empty else None


def _enrich_fills_with_fx_rate(
    cm, processed_fills_df: pd.DataFrame, date_str: str,
) -> pd.DataFrame:
    """从 fill_bdib 回填 processed_fills 的 fx_rate（007-costview-report-filters）。

    processed_fills 本身不拉取 FX（S2 无 Bloomberg 依赖）；fx_rate 在 S5
    fill_bdib 集成时才有。此处按 (OrderId, RouteId, mkt_timestamp) 连接 fill_bdib，
    把 fill 级 fx_rate 合并回 processed_fills（缺失保持 None），并写回
    processed_fills 表持久化（方案 B：processed_fills 加列）。

    Returns:
        已附加 fx_rate 列的 processed_fills 副本（原 df 不变）。
    """
    if processed_fills_df.empty or "fx_rate" in processed_fills_df.columns and processed_fills_df["fx_rate"].notna().all():
        return processed_fills_df

    from DataPipeline.storage.repositories.integrated import SqliteIntegratedReadRepository

    try:
        fb = SqliteIntegratedReadRepository(cm).get_integrated_data_for_date(date_str)
    except Exception as exc:
        logger.warning("  RouteMetrics %s: 加载 fill_bdib 失败，fx_rate 跳过: %s", date_str, exc)
        return processed_fills_df

    if fb.empty or "fx_rate" not in fb.columns:
        return processed_fills_df

    fx = fb[["OrderId", "RouteId", "mkt_timestamp", "fx_rate"]].dropna(subset=["fx_rate"])
    if fx.empty:
        return processed_fills_df

    df = processed_fills_df.copy()
    for col in ("OrderId", "RouteId", "mkt_timestamp"):
        df[col] = df[col].astype(str)
        fx[col] = fx[col].astype(str)
    df = df.merge(
        fx, on=["OrderId", "RouteId", "mkt_timestamp"], how="left",
        suffixes=("", "_fb"),
    )
    if "fx_rate_fb" in df.columns:
        df["fx_rate"] = df["fx_rate_fb"]
        df = df.drop(columns=["fx_rate_fb"])

    # 持久化回 processed_fills（方案 B）
    try:
        from DataPipeline.storage.repositories.fills import SqliteFillWriteRepository
        cols_to_write = [c for c in df.columns if c in PROCESSED_COLUMNS_FX]
        if "fx_rate" in df.columns:
            SqliteFillWriteRepository(cm).upsert_processed_fills(df[cols_to_write])
    except Exception as exc:
        logger.warning("  RouteMetrics %s: fx_rate 写回 processed_fills 失败: %s", date_str, exc)

    return df


#: processed_fills 列（供 fx_rate 写回时过滤）
PROCESSED_COLUMNS_FX: List[str] = [
    "FillId", "OrderId", "RouteId", "mkt_timestamp",
    "order_as_of_date", "local_fill_datetime", "exchange_exec_time",
    "route_as_of_time", "DateTimeOfFill", "Broker", "StrategyType",
    "algo", "TraderName", "Exchange", "Amount", "RouteShares",
    "is_closing_auction", "ExecType", "region", "equ_ticker",
    "FillPrice", "FillShares", "fx_rate",
]


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

    @staticmethod
    def _init_fx_repo(cm) -> Optional["SqliteFxRatesRepository"]:
        """构造 fx_rates 仓储并确保表存在（fx-rate-persistence）。

        初始化失败时降级为 None（fx_fetcher 退化为无持久化拉取，不阻断 S5）。
        """
        from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository
        from DataPipeline.storage.schema.inline_ddl import init_fx_rates_schema

        try:
            repo = SqliteFxRatesRepository(connection_manager=cm)
            conn = repo._get_admin_conn()
            try:
                init_fx_rates_schema(conn)
            finally:
                conn.close()
            return repo
        except Exception as exc:
            logger.warning("fx_rates 仓储初始化失败，退化为无持久化 FX 拉取: %s", exc)
            return None

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
        cm = context.connection_manager
        market_write = SqliteMarketDataWriteRepository(connection_manager=cm) if cm else context.db.market_data_write
        fills_reader = context.db.fills_read
        fills_writer = context.db.fills_write
        # fx-rate-persistence: fx_rates 汇率表仓储（查表优先/成功落表/有界回退）
        fx_repo = self._init_fx_repo(cm)
        # BDIB 拉取历史审计（对齐 fill_fetch_history）：初始化失败仅告警，不阻断 S5
        bdib_history_repo = None
        try:
            bdib_history_repo = SqliteBdibFetchHistoryRepository(
                connection_manager=cm
            ) if cm else None
        except Exception as exc:
            logger.warning("bdib_fetch_history 仓储初始化失败，审计记录不可用: %s", exc)

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
                # Force 模式或 raw_bdib 尚无数据: 回填窗口180天
                start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)
            else:
                # 增量模式: start_dt 取 (raw_bdib 最新日期 + 1 天) 与 latest_safe_bdib_date 的较小者
                # 避免 start_dt > latest_safe_bdib_date 导致空候选 — 当 raw_bdib 已超过
                # safe_bdib_date (BDIB 数据先于 fills 拉取的情况) 时, 从 safe_bdib_date 开始
                try:
                    latest_dt = datetime.strptime(latest_raw, "%Y%m%d").date()
                    start_dt = min(latest_dt + timedelta(days=1), latest_safe_bdib_date)
                except ValueError:
                    start_dt = latest_safe_bdib_date - timedelta(days=180)
                all_candidate_dates = self._expand_weekdays(start_dt, latest_safe_bdib_date)

        if not all_candidate_dates:
            logger.info("No dates for BDIB integration")
            context.summary["bdib"] = {"completed": True, "dates": 0}
            return True

        # 前置校验：检测 raw_bdib 空 bar 残留（历史数据问题，不影响新数据拉取）
        try:
            from DataPipeline.pipeline_guards.empty_bar_guard import EmptyBarGuard
            violations = EmptyBarGuard().scan(
                run_id=getattr(context, "run_id", "S5_precheck")
            )
            if violations:
                logger.warning(
                    "raw_bdib 空 bar 检测: 发现 %d 条违规（历史残留；清理脚本已归档 git 历史，"
                    "见 ADR-0014，可恢复后运行 cleanup_raw_bdib_empty_bars.py --apply）",
                    len(violations),
                )
        except Exception as e:
            logger.debug("空 bar 前置校验跳过: %s", e)

        # 前置校验：检测 processed_fills 与 raw_bdib 的 ticker 覆盖缺口
        try:
            from DataPipeline.pipeline_guards.bdib_coverage_guard import BDIBCoverageGuard
            coverage_violations = BDIBCoverageGuard().scan(
                run_id=getattr(context, "run_id", "S5_precheck")
            )
            if coverage_violations:
                logger.warning(
                    "BDIB 覆盖率检测: 发现 %d 条覆盖率缺口（有成交但无 BDIB 行情），"
                    "建议运行 scripts/ops/backfill_ticker_repository.py 补注册 ticker，"
                    "再用 scripts/ops/backfill_bdib_by_market.py 回补 BDIB 数据",
                    len(coverage_violations),
                )
        except Exception as e:
            logger.debug("BDIB 覆盖率前置校验跳过: %s", e)

        latest_raw_date = context.db.market_data_read.get_latest_order_as_of_date()
        latest_proc_raw_date = context.db.market_data_read.get_latest_order_as_of_date()
        try:
            already_integrated = set(fills_reader.get_processed_dates(stage="bdib_integrated") or [])
        except Exception:
            already_integrated = set()

        bdid_exchange = [str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip()]
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
        # 防护 (M10): 失败显式化 — 日期级失败进健康清单, 全部失败时阶段失败
        failed_dates: list[str] = []
        failed_chunks = 0

        # Chunk tickers to avoid loading ALL BDIB data into memory at once
        all_tickers = list(ticker_exchange_map_all.keys())
        ticker_chunk_size = 50
        logger.info("BDIB: %d tickers, processing in chunks of %d", len(all_tickers), ticker_chunk_size)

        # 进度报告：BDIB 阶段可能处理数百个日期，每处理一个日期输出 [STAGE]
        # 避免前端因长时间无输误判为"stalled"
        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        total_dates = max(1, len(all_candidate_dates))

        for date_idx, date_str in enumerate(all_candidate_dates):
            # 每个日期处理前输出 [STAGE] 进度，防止前端误判 stalled
            if marker_name:
                stage_pct = 76 + int((date_idx / total_dates) * 5)
                print(
                    f"[STAGE] {marker_name} {stage_pct} "
                    f"BDIB date {date_idx + 1}/{total_dates}: {date_str}",
                    flush=True,
                )
            try:
                # ── v4.0-p2: 仅当 fill_bdib 已集成时跳过整个日期 ──
                # raw_bdib/processed_raw_bdib 已有数据时仅跳过拉取阶段,
                # 仍会执行集成阶段 (Phase C), 解决 fill_bdib 滞后问题
                if not context.force and date_str in already_integrated:
                    skipped_fill += 1
                    logger.info("  BDIB %s: fill_bdib 已存在, 跳过", date_str)
                    continue

                # ── 判断各阶段是否需要执行 ──
                need_bdib_fetch = (
                    context.force
                    or not latest_raw_date
                    or date_str > latest_raw_date
                )
                need_bdib_enrich = (
                    context.force
                    or not latest_proc_raw_date
                    or date_str > latest_proc_raw_date
                )

                if not need_bdib_fetch:
                    skipped_raw += 1
                    logger.info("  BDIB %s: raw_bdib 已存在, 跳过 Bloomberg 拉取 (仍将执行集成)", date_str)

                date_raw_rows = 0
                date_proc_raw_rows = 0
                bdib_enriched_chunks = []

                # ── Phase A+B: BDIB 拉取 + 写入 (仅当需要时) ──
                if need_bdib_fetch:
                    fetched_tickers: set[str] = set()
                    for chunk_i in range(0, len(all_tickers), ticker_chunk_size):
                        chunk_tickers = all_tickers[chunk_i:chunk_i + ticker_chunk_size]
                        chunk_ticker_dates = {t: [date_str] for t in chunk_tickers}
                        try:
                            chunk_map = fetch_bdib_for_fills(chunk_ticker_dates, interval=10, ticker_exchange_map=ticker_exchange_map_all)
                            if not chunk_map:
                                continue
                            fetched_tickers.update(
                                k.split("|")[0] for k in chunk_map
                            )
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
                            failed_chunks += 1
                            logger.warning("  BDIB chunk %d error for %s: %s", chunk_i, date_str, chunk_err)
                    # ── BDIB 拉取历史审计（对齐 fill_fetch_history）──
                    # 仅在本次确实向 Bloomberg 发起拉取并成功写入时记录
                    if date_raw_rows > 0 and bdib_history_repo is not None:
                        try:
                            bdib_history_repo.record_fetch(
                                source_date=date_str,
                                data_hash=compute_bdib_data_hash(
                                    fetched_tickers, date_raw_rows
                                ),
                                row_count=date_raw_rows,
                                ticker_count=len(fetched_tickers),
                            )
                        except Exception as hist_err:
                            logger.warning(
                                "  BDIB %s: 拉取历史记录失败（不影响数据）: %s",
                                date_str, hist_err,
                            )

                # ── 回补路径: BDIB 拉取跳过时, 从 raw_bdib 加载已有数据 ──
                # Phase A8 后 processed_raw_bdib 已退役，直接从 raw_bdib 读取
                # 并使用 compute_derived_fields 计算派生字段
                if not need_bdib_fetch and not bdib_enriched_chunks:
                    try:
                        conn = cm.get_connection("raw_bdib", AccessTier.READ)
                        bdib_from_db = pd.read_sql_query(
                            "SELECT equ_ticker, order_as_of_date, mkt_timestamp, "
                            "open, high, low, close, volume, num_trds, value "
                            "FROM raw_bdib WHERE order_as_of_date = ?",
                            conn.raw_connection,
                            params=[date_str],
                        )
                        conn.close()
                        if not bdib_from_db.empty:
                            enriched = market_write.compute_derived_fields(bdib_from_db)
                            bdib_enriched_chunks.append(enriched)
                            date_proc_raw_rows = len(enriched)
                            logger.info(
                                "  BDIB %s: 从 raw_bdib 加载 %d 行并计算派生字段用于集成",
                                date_str, len(bdib_from_db),
                            )
                        else:
                            logger.info(
                                "  BDIB %s: raw_bdib 中无数据, 跳过集成",
                                date_str,
                            )
                    except Exception as load_err:
                        logger.warning(
                            "  BDIB %s: 从 raw_bdib 加载失败 (%s), 跳过集成",
                            date_str, load_err,
                        )

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

                # ── Phase FX: Fetch FX rates for this date ──
                # fx-rate-persistence: 注入 fx_repo —— 查表优先（命中零配额消耗）、
                # miss 才拉 Bloomberg、成功即落表、失败/暂停按表内 ≤目标日期 回退
                from DataPipeline.acquisition.fx_fetcher import fetch_fx_rates_for_date, fx_rates_to_dataframe
                ccy_tickers = agg_df["ccy_ticker"].dropna().unique().tolist() if "ccy_ticker" in agg_df.columns else []
                if ccy_tickers:
                    fx_dict = fetch_fx_rates_for_date(ccy_tickers, date_str, fx_repo=fx_repo)
                    fx_rates = fx_rates_to_dataframe(fx_dict, date_str)
                    logger.info("Fetched FX rates for %s: %d ccy_tickers", date_str, len(fx_rates))
                else:
                    fx_rates = None

                integrated_df = integrate_fills_bdib_for_date(agg_df, date_str, bdib_data=bdib_enriched, ticker_exchange_map=ticker_exchange_map_all, fx_rates=fx_rates)
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
                failed_dates.append(date_str)
                logger.error(f"  Error in BDIB integration for {date_str}: {e}")
                gc.collect()

        context.summary["bdib"] = {
            "completed": True, "candidate_dates": len(all_candidate_dates),
            "processed_dates": len(all_candidate_dates) - skipped_raw - skipped_proc_raw - skipped_fill,
            "skipped_raw": skipped_raw, "skipped_processed_raw": skipped_proc_raw, "skipped_fill": skipped_fill,
            "raw_bdib_rows": total_raw_bdib_rows, "processed_raw_bdib_rows": total_processed_raw_bdib_rows, "fill_bdib_rows": total_fill_bdib_rows,
            # M10: 健康清单 — 失败日期与失败分块数 (部分失败不再被静默掩盖)
            "failed_dates": failed_dates,
            "failed_chunks": failed_chunks,
        }
        # M10: 全部候选日期失败时阶段返回 False; 部分失败显式记录于 summary
        all_failed = bool(all_candidate_dates) and len(failed_dates) >= len(all_candidate_dates)
        if all_failed:
            logger.error("BDIB 阶段全部 %d 个日期失败", len(all_candidate_dates))
        return not all_failed




# ═══════════════════════════════════════════════════════════════
# S5.5: ComputeRouteMetricsStage
# ═══════════════════════════════════════════════════════════════
class ComputeRouteMetricsStage(BaseStage):
    """Stage 5.5: 计算并存储路由级 TCA 指标到 tca_route_summary 表。"""

    @property
    def name(self) -> str: return "5.5. Compute Route Metrics"

    def process(self, context: PipelineContext) -> bool:
        try:
            from DataPipeline.storage.connection import ConnectionManager
            cm = context.connection_manager
        except ImportError as e:
            logger.warning(f"Skipping route metrics computation: {e}")
            context.summary["route_metrics"] = {"skipped": True, "error": str(e)}
            return True

        fills_reader = context.db.fills_read
        raw_fills_reader = context.db.raw_fills_read

        # 确定待处理日期：优先 target_dates，否则取已 bdib_integrated 的日期
        if context.target_dates:
            dates_to_process = list(context.target_dates)
        else:
            dates_to_process = fills_reader.get_processed_dates(stage="bdib_integrated") or []

        if not dates_to_process:
            logger.info("No dates for route metrics computation")
            context.summary["route_metrics"] = {"completed": True, "dates": 0, "rows": 0}
            return True

        # 增量：跳过已计算 route_metrics 的日期（除非 force）
        if not context.force:
            try:
                conn = cm.get_connection("fill_bdib", AccessTier.READ)
                already_computed = set(
                    r[0] for r in conn.execute(
                        f"SELECT DISTINCT order_as_of_date FROM {Config.TCA_ROUTE_SUMMARY_TABLE}"
                    ).fetchall()
                )
                conn.close()
                dates_to_process = [d for d in dates_to_process if d not in already_computed]
            except Exception as e:
                logger.debug("tca_route_summary 增量判断跳过: %s", e)

        if not dates_to_process:
            logger.info("All candidate dates already have route metrics")
            context.summary["route_metrics"] = {"completed": True, "dates": 0, "rows": 0}
            return True

        total_rows = 0
        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        total_metric_dates = max(1, len(dates_to_process))

        for metric_idx, date_str in enumerate(dates_to_process):
            if marker_name:
                stage_pct = 81 + int((metric_idx / total_metric_dates) * 2)
                print(
                    f"[STAGE] {marker_name} {stage_pct} "
                    f"RouteMetrics date {metric_idx + 1}/{total_metric_dates}: {date_str}",
                    flush=True,
                )
            try:
                raw_fills_df = raw_fills_reader.get_fills_for_date(date_str)
                processed_fills_df = fills_reader.get_fills_for_date(date_str)
                if processed_fills_df.empty or raw_fills_df.empty:
                    logger.info("  RouteMetrics %s: no fills, skipping", date_str)
                    continue

                # 007: 从 fill_bdib 回填 processed_fills 的 fx_rate（方案 B）
                try:
                    processed_fills_df = _enrich_fills_with_fx_rate(
                        cm, processed_fills_df, date_str,
                    )
                except Exception as exc:
                    logger.warning("  RouteMetrics %s: fx_rate 回填失败，继续: %s", date_str, exc)

                equ_tickers = processed_fills_df["equ_ticker"].dropna().unique().tolist() if "equ_ticker" in processed_fills_df.columns else []
                raw_bdib_df = load_raw_bdib_for_date(date_str, equ_tickers=equ_tickers)

                # 003-tca-core-benchmarks: 加载 bdib_daily_summary（含下一交易日，
                # 供收盘价基准 + 跨日次日收盘恢复窗口使用）
                daily_summary_df = None
                if (Config.TCA_CORE_BENCHMARKS_ENABLED or Config.TCA_RISK_IMPACT_ENABLED):
                    try:
                        daily_summary_df = _load_daily_summary_for_metrics(cm, date_str, equ_tickers)
                    except Exception as e:
                        logger.warning("  RouteMetrics %s: 加载 daily_summary 失败: %s", date_str, e)
                        daily_summary_df = None

                metrics_df = compute_route_metrics_for_date(
                    raw_fills_df, processed_fills_df, raw_bdib_df, date_str,
                    daily_summary_df=daily_summary_df,
                )
                if not metrics_df.empty:
                    rows = context.db.integrated_write.upsert_tca_route_summary(metrics_df, date_str=date_str)
                    total_rows += rows
                    logger.info("  RouteMetrics %s: computed %d routes", date_str, len(metrics_df))
                else:
                    logger.info("  RouteMetrics %s: no routes computed", date_str)

                del raw_fills_df, processed_fills_df, raw_bdib_df, metrics_df
                if daily_summary_df is not None:
                    del daily_summary_df
                gc.collect()
            except Exception as e:
                logger.error(f"  Error computing route metrics for {date_str}: {e}")
                gc.collect()

        context.summary["route_metrics"] = {
            "completed": True,
            "dates": len(dates_to_process),
            "rows": total_rows,
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
            from DataPipeline.analysis.downstream_interface import write_manifest
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
            connection_manager=context.connection_manager, db=context.db,
        )

        if context.target_dates:
            dates_to_process = context.target_dates
        else:
            fills_reader = context.db.fills_read
            all_bdib_dates = fills_reader.get_processed_dates(stage="bdib_integrated")
            if not all_bdib_dates:
                all_bdib_dates = context.db.market_data_read.get_distinct_dates()

            # Incremental: skip dates that already have daily metrics computed.
            # Query the bdib_daily_summary table for distinct trade_date values
            # that already exist — only process dates NOT in this set.
            try:
                conn = context.connection_manager.get_connection(
                    "raw_bdib", AccessTier.READ,
                )
                already_computed = set(
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT trade_date FROM bdib_daily_summary"
                    ).fetchall()
                )
            except Exception:
                already_computed = set()

            dates_to_process = [
                d for d in all_bdib_dates if d not in already_computed
            ]
            if all_bdib_dates and not dates_to_process:
                logger.info(
                    "All %d BDIB dates already have daily metrics — skipping",
                    len(all_bdib_dates),
                )

        if not dates_to_process:
            logger.info("No new dates for daily metrics calculation")
            context.summary["daily_metrics"] = {"rows": 0, "dates": 0}
            return True

        total_rows = 0
        # 进度报告：逐日期处理，输出 [STAGE] 避免前端误判 stalled
        marker_name = str(context.config.get("stage_marker_name", "")).strip()
        total_metric_dates = max(1, len(dates_to_process))
        for metric_idx, trade_date in enumerate(dates_to_process):
            if marker_name:
                stage_pct = 83 + int((metric_idx / total_metric_dates) * 5)
                print(
                    f"[STAGE] {marker_name} {stage_pct} "
                    f"Metrics date {metric_idx + 1}/{total_metric_dates}: {trade_date}",
                    flush=True,
                )
            try:
                rows = calc.run_for_date(trade_date)
                total_rows += rows
            except Exception as e:
                logger.error(f"  Error computing metrics for {trade_date}: {e}")

        context.summary["daily_metrics"] = {"rows": total_rows, "dates": len(dates_to_process)}
        return True
