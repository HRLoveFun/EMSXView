"""按市场分批编排 BDIB 数据回补。

封装 CostView/scripts/backfill_raw_bdib.py 的 run_backfill()，
按 exchange 分批执行，避免一次性拉取数百个 ticker × 数百天
导致 Bloomberg API 过载或内存问题。

背景：扩展 BDIB_EXCHANGE 白名单 + 补注册 ticker_repository 后，
新增市场 ticker 需要历史 BDIB 数据回补。按市场分批可控制
每批的 Bloomberg API 调用量，便于监控和错误恢复。

2026-07-16 调整：业务决定仅保留 HK（香港 HKEX）进入分析范围，
2026-07-08 临时补齐的 CN / BZ / MM / PW / DC / IT / NZ / MUMBAI
等 8 个市场订单不在分析范围，已从 Config.BDIB_EXCHANGE 白名单移除，
这些 ticker 也已从 ticker_repository 清理。NEW_MARKETS 仅保留 HK。

用法：
    # 预览将要回补的市场和 ticker 数
    python backfill_bdib_by_market.py --dry-run

    # 仅回补 HK 市场
    python backfill_bdib_by_market.py --markets HK

    # 回补 HK + 显式指定其它市场（不推荐，仅 BDIB_EXCHANGE 内）
    python backfill_bdib_by_market.py --markets HK,US

    # 回补新增市场（当前仅 HK）
    python backfill_bdib_by_market.py --markets NEW

    # 回补 BDIB_EXCHANGE 全部市场
    python backfill_bdib_by_market.py --markets ALL

    # 指定日期范围
    python backfill_bdib_by_market.py --markets HK --start 2025-01-01 --end 2026-06-30

注意：需要 Bloomberg 连接（BPIPE/xbbg）。

⚠️ BDIB 历史保留窗口限制：
    Bloomberg BDIB (intraday bar) API 对历史数据有保留期限——
    - US/LN/JP/KS 等主要市场：约 9 个月
    - HK 等市场：约 6 个月
    超出保留窗口的日期 BDIB 返回空 DataFrame，无法回补。
    默认 --start 自动计算为 today - 180 天（Config.BDIB_API_RETENTION_DAYS），
    确保所有市场都在保留窗口内。
    使用 --force 确保新 ticker 数据被拉取（增量模式会跳过已有数据的日期）。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# ── 路径设置 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_COSTVIEW_ROOT = _PROJECT_ROOT / "CostView"
_COSTVIEW_SCRIPTS = _COSTVIEW_ROOT / "scripts"
for p in [_PROJECT_ROOT, _COSTVIEW_ROOT, _COSTVIEW_SCRIPTS]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

# 2026-07-16 调整：业务决定仅保留 HK（香港 HKEX）进入分析范围。
# 2026-07-08 曾临时补齐 9 个市场（CN / BZ / MM / PW / DC / IT / NZ / MUMBAI），
# 这些市场订单不在分析范围，已从 Config.BDIB_EXCHANGE 与 ticker_repository 中移除。
# 当前 NEW_MARKETS 仅包含 HK。
NEW_MARKETS: List[str] = ["HK"]


def _count_tickers_per_market(markets: List[str]) -> Dict[str, int]:
    """统计每个市场的 ticker 数量。"""
    from DataPipeline.storage.facade import DatabaseFacade

    db = DatabaseFacade()
    result: Dict[str, int] = {}
    for market in markets:
        mapping = db.fills_read.get_ticker_exchange_map(exchanges=[market])
        result[market] = len(mapping)
    return result


def _run_market_backfill(
    market: str,
    start_date: str,
    end_date: str | None,
    force: bool,
    dry_run: bool,
) -> dict:
    """对单个市场执行 BDIB 回补。

    通过临时修改 Config.BDIB_EXCHANGE 实现按市场过滤。
    """
    # 保存原始白名单
    original_exchange = Config.BDIB_EXCHANGE

    try:
        # 临时设置为仅当前市场
        Config.BDIB_EXCHANGE = [market]

        # 导入 run_backfill（延迟导入，确保 Config 修改生效）
        from backfill_raw_bdib import run_backfill

        logger.info("=" * 60)
        logger.info("开始回补市场 %s ...", market)
        logger.info("  日期范围: %s -> %s", start_date, end_date or "auto")
        logger.info("  force: %s, dry_run: %s", force, dry_run)

        start_time = time.time()
        summary = run_backfill(
            start_date_str=start_date,
            end_date_str=end_date,
            force=force,
            dry_run=dry_run,
        )
        elapsed = time.time() - start_time

        logger.info(
            "市场 %s 回补完成 (%.1fs): "
            "候选 %d 天, 成功 %d 天, 失败 %d 天, 写入 %d 行",
            market,
            elapsed,
            summary.get("total_candidate_days", 0),
            summary.get("fetched_days", 0),
            summary.get("failed_days", 0),
            summary.get("total_rows_upserted", 0),
        )
        return summary
    finally:
        # 恢复原始白名单
        Config.BDIB_EXCHANGE = original_exchange


def main() -> None:
    parser = argparse.ArgumentParser(
        description="按市场分批编排 BDIB 数据回补",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--markets",
        type=str,
        default="NEW",
        help=(
            "逗号分隔的市场代码（如 HK,US），"
            "或 NEW（当前仅 HK，2026-07-16 后从 9 个缩减为 1 个），"
            "或 ALL（BDIB_EXCHANGE 全部市场）"
        ),
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help=(
            "起始日期 YYYY-MM-DD（默认：today - 180 天，基于 BDIB 保留窗口自动计算）\n"
            "注意：Bloomberg BDIB API 有历史保留窗口限制——\n"
            "  US/LN/JP/KS 等主要市场：约 9 个月\n"
            "  HK/NZ/CN/BZ 等新兴市场：约 6 个月\n"
            "超出保留窗口的日期 BDIB 返回空数据，无法回补。"
        ),
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="结束日期 YYYY-MM-DD（默认到最近工作日）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新拉取，即使 raw_bdib 中已有数据",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际拉取数据",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细日志",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # ── 未指定 --start 时，基于 BDIB 保留窗口动态计算 ──
    if args.start is None:
        start_date = (
            datetime.now().date() - timedelta(days=Config.BDIB_API_RETENTION_DAYS)
        ).strftime("%Y-%m-%d")
        logger.info(
            "未指定 --start，基于 BDIB 保留窗口（%d 天）自动计算起始日期: %s",
            Config.BDIB_API_RETENTION_DAYS, start_date,
        )
    else:
        start_date = args.start

    # 解析市场列表
    if args.markets.upper() == "ALL":
        markets = list(Config.BDIB_EXCHANGE)
    elif args.markets.upper() == "NEW":
        markets = list(NEW_MARKETS)
    else:
        markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]

    if not markets:
        logger.error("未指定市场")
        sys.exit(1)

    # 预览各市场 ticker 数量
    logger.info("=" * 60)
    logger.info("BDIB 分批回补计划:")
    logger.info("  日期范围: %s -> %s", start_date, args.end or "auto")
    logger.info("  force: %s, dry_run: %s", args.force, args.dry_run)
    logger.info("  市场列表: %s", ", ".join(markets))

    ticker_counts = _count_tickers_per_market(markets)
    total_tickers = sum(ticker_counts.values())
    logger.info("  各市场 ticker 数:")
    for market in markets:
        count = ticker_counts.get(market, 0)
        logger.info("    %s: %d 个 ticker", market, count)
    logger.info("  合计: %d 个 ticker", total_tickers)

    if total_tickers == 0:
        logger.warning("无 ticker 可回补，退出")
        return

    if args.dry_run:
        logger.info("[dry-run] 未实际拉取数据。去掉 --dry-run 执行回补。")
        return

    # 逐市场执行回补
    all_summaries: Dict[str, dict] = {}
    total_start = time.time()

    for i, market in enumerate(markets, 1):
        if ticker_counts.get(market, 0) == 0:
            logger.info("[%d/%d] 跳过 %s（无 ticker）", i, len(markets), market)
            continue

        logger.info("[%d/%d] 回补市场 %s ...", i, len(markets), market)
        try:
            summary = _run_market_backfill(
                market=market,
                start_date=start_date,
                end_date=args.end,
                force=args.force,
                dry_run=args.dry_run,
            )
            all_summaries[market] = summary
        except Exception as e:
            logger.error("市场 %s 回补失败: %s", market, e, exc_info=True)
            all_summaries[market] = {"error": str(e)}

    # 汇总
    total_elapsed = time.time() - total_start
    logger.info("=" * 60)
    logger.info("全部分批回补完成 (%.1fs):", total_elapsed)
    total_fetched = 0
    total_rows = 0
    total_failed = 0
    for market, summary in all_summaries.items():
        if "error" in summary:
            logger.error("  %s: 失败 — %s", market, summary["error"])
        else:
            fetched = summary.get("fetched_days", 0)
            rows = summary.get("total_rows_upserted", 0)
            failed = summary.get("failed_days", 0)
            total_fetched += fetched
            total_rows += rows
            total_failed += failed
            logger.info(
                "  %s: %d 天成功, %d 行写入, %d 天失败",
                market, fetched, rows, failed,
            )
    logger.info("  合计: %d 天成功, %d 行写入, %d 天失败",
                total_fetched, total_rows, total_failed)


if __name__ == "__main__":
    main()
