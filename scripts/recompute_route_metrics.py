"""recompute_route_metrics.py

独立运行 Stage 5.5 (ComputeRouteMetricsStage) 从已落盘的 processed_fills + raw_bdib
计算并写入 tca_route_summary。**无需 Bloomberg 连接**。

主要用途：
- 回填新增列（如 fill_count）到现有 tca_route_summary
- 当 Stage 5 (IntegrateBDIB) 未完成时单独补全 tca_route_summary
- 验证 35 字段 (17 源值 + 18 计算指标) 的计算结果

Usage:
    # 默认: 处理 processed_fills 中所有已有日期（增量模式，跳过已计算）
    python scripts/recompute_route_metrics.py

    # 指定日期
    python scripts/recompute_route_metrics.py --dates 20260713 20260714 20260715

    # 日期范围
    python scripts/recompute_route_metrics.py --start-date 20260701 --end-date 20260715

    # 强制重算已有日期（覆盖现有 tca_route_summary 行）
    python scripts/recompute_route_metrics.py --force

    # 试运行：仅显示将处理的日期与配置，不实际执行
    python scripts/recompute_route_metrics.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# 确保可导入 DataPipeline / platform_data
_SCRIPT_DIR = Path(__file__).resolve().parent
_EMSX_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config
from DataPipeline.orchestration.context import PipelineContext
from DataPipeline.orchestration.stages_process import ComputeRouteMetricsStage
from DataPipeline.storage.schema.inline_ddl import init_fill_bdib_schema

# UTF-8 stdout (Windows PowerShell cp1252 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("recompute_route_metrics")


def _ensure_tca_route_summary_schema() -> None:
    """确保 fill_bdib.db 中 tca_route_summary 表及其列定义存在。"""
    Config.initialize_directories()
    db_path = Config.FILL_BDIB_DB
    conn = sqlite3.connect(str(db_path))
    try:
        init_fill_bdib_schema(conn)
        logger.info("Schema ensured: %s", db_path)
    finally:
        conn.close()


def _resolve_dates_from_processed_fills(
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[str]:
    """从 processed_fills.db 提取已处理日期（按 order_as_of_date 去重并排序）。"""
    conn = sqlite3.connect(str(Config.PROCESSED_FILLS_DB))
    try:
        sql = (
            f"SELECT DISTINCT order_as_of_date FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE order_as_of_date IS NOT NULL"
        )
        params: list = []
        if start_date:
            sql += " AND order_as_of_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND order_as_of_date <= ?"
            params.append(end_date)
        sql += " ORDER BY order_as_of_date"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


def _parse_date_arg(s: str) -> str:
    """支持 'YYYYMMDD' 或 'YYYY-MM-DD' 两种格式，统一返回 'YYYYMMDD'。"""
    s = s.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s.replace("-", "")
    if len(s) == 8 and s.isdigit():
        return s
    raise ValueError(f"Invalid date: {s!r} (expected YYYYMMDD or YYYY-MM-DD)")


def _print_plan(dates: list[str], force: bool, dry_run: bool) -> None:
    """打印执行计划。"""
    print("=" * 64)
    print(" recompute_route_metrics 执行计划")
    print("-" * 64)
    print(f"  fill_bdib.db       : {Config.FILL_BDIB_DB}")
    print(f"  tca_route_summary  : {Config.TCA_ROUTE_SUMMARY_TABLE}")
    print(f"  dates              : {len(dates)} ({dates[0]} .. {dates[-1]})")
    if len(dates) <= 20:
        print(f"    all              : {dates}")
    else:
        print(f"    first 10         : {dates[:10]}")
        print(f"    last 10          : {dates[-10:]}")
    print(f"  mode               : {'force (覆盖已有)' if force else 'incremental (跳过已计算)'}")
    print(f"  dry-run            : {dry_run}")
    print("=" * 64)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="独立运行 Stage 5.5 (ComputeRouteMetrics) 回填 tca_route_summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dates", nargs="+",
        help="指定日期列表 (YYYYMMDD 或 YYYY-MM-DD)",
    )
    parser.add_argument("--start-date", help="开始日期 (YYYYMMDD 或 YYYY-MM-DD)")
    parser.add_argument("--end-date", help="结束日期 (YYYYMMDD 或 YYYY-MM-DD)")
    parser.add_argument(
        "--force", action="store_true",
        help="强制重算已存在的日期（默认增量模式：跳过已计算）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行：仅显示将处理的日期与配置，不实际执行",
    )
    args = parser.parse_args()

    # 1. 确保 fill_bdib.db::tca_route_summary 表与列定义存在
    _ensure_tca_route_summary_schema()

    # 2. 解析日期
    if args.dates:
        try:
            dates = [_parse_date_arg(d) for d in args.dates]
        except ValueError as e:
            logger.error("%s", e)
            return 1
    elif args.start_date or args.end_date:
        start = _parse_date_arg(args.start_date) if args.start_date else None
        end = _parse_date_arg(args.end_date) if args.end_date else None
        dates = _resolve_dates_from_processed_fills(start, end)
    else:
        dates = _resolve_dates_from_processed_fills(None, None)

    if not dates:
        logger.error("无待处理日期。请检查 processed_fills.db 是否有数据。")
        return 1

    _print_plan(dates, args.force, args.dry_run)

    if args.dry_run:
        logger.info("DRY-RUN: 已显示执行计划，未实际执行。移除 --dry-run 以真正运行。")
        return 0

    # 3. 构建 PipelineContext 并运行 Stage 5.5
    # config={} 表示无 stage_marker_name，standalone 模式下不输出 [STAGE] 进度心跳
    ctx = PipelineContext(
        target_dates=dates,
        force=args.force,
        config={},
    )

    stage = ComputeRouteMetricsStage()
    logger.info("执行阶段: %s", stage.name)
    ok = stage.execute(ctx)

    summary = ctx.summary.get("route_metrics", {})
    logger.info("=" * 64)
    logger.info("执行完成: ok=%s, summary=%s", ok, summary)
    logger.info("错误数: %d", len(ctx.errors))
    if ctx.errors:
        for err in ctx.errors[:5]:
            logger.error("  - %s: %s", err["stage"], err["error"])
    logger.info("=" * 64)

    return 0 if ok and ctx.is_successful else 1


if __name__ == "__main__":
    sys.exit(main())
