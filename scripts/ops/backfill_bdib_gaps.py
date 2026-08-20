"""backfill_bdib_gaps.py — 针对窗口内 BDIB 缺口日期的精准回补（003-tca-core-benchmarks）。

背景：`backfill_bdib_by_market.py` 对每个交易日拉取**全部**已注册 ticker（约 2120 个），
对 66 个缺口日期执行会非常耗时且浪费（多数 ticker 当日并无成交）。

本脚本只对**缺口日期**且**当日有成交的 ticker** 拉取 BDIB，大幅减少 Bloomberg API 调用量。

缺口判定：tca_route_summary 中 p_arrival 覆盖率 < 80% 且日期在保留窗口内（>= today-180d）。

用法:
    # 预览（只列出缺口日期与待拉取 ticker 数，不实际拉取）
    python scripts/ops/backfill_bdib_gaps.py --dry-run

    # 执行回补（默认窗口内全部缺口日期）
    python scripts/ops/backfill_bdib_gaps.py

    # 指定日期范围
    python scripts/ops/backfill_bdib_gaps.py --start 2026-05-01 --end 2026-08-12

    # 强制重新拉取已有数据的 ticker-date（默认跳过已有）
    python scripts/ops/backfill_bdib_gaps.py --force

    # 指定单个/多个日期（空格分隔，YYYYMMDD 或 YYYY-MM-DD）
    python scripts/ops/backfill_bdib_gaps.py --dates 20260511 20260512
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# ── 路径设置 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_EMSX_ROOT = _SCRIPT_DIR.parent.parent
_COSTVIEW_ROOT = _EMSX_ROOT / "CostView"
_COSTVIEW_SCRIPTS = _COSTVIEW_ROOT / "scripts"
for p in [_EMSX_ROOT, _COSTVIEW_ROOT, _COSTVIEW_SCRIPTS]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from DataPipeline.config import Config
from DataPipeline.acquisition.bdib_fetcher import fetch_bdib_for_fills
from DataPipeline.storage.facade import DatabaseFacade

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logger = logging.getLogger("backfill_bdib_gaps")

GAP_COVERAGE_THRESHOLD = 80.0  # p_arrival 覆盖率低于该值视为缺口


def _get_fill_tickers_for_date(date_str: str) -> List[str]:
    """获取某交易日 processed_fills 中有成交的 equ_ticker 列表。"""
    db = DatabaseFacade()
    return db.fills_read.get_distinct_tickers_for_date(date_str)


def _get_gap_dates(start: str, end: str) -> List[str]:
    """从 tca_route_summary 识别 p_arrival 覆盖率 < 阈值的缺口日期。"""
    import sqlite3
    conn = sqlite3.connect(str(Config.FILL_BDIB_DB))
    rows = conn.execute(
        "SELECT order_as_of_date, COUNT(*) t, "
        "SUM(CASE WHEN p_arrival IS NOT NULL THEN 1 ELSE 0 END) a "
        f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
        "WHERE order_as_of_date BETWEEN ? AND ? "
        "GROUP BY order_as_of_date ORDER BY order_as_of_date",
        (start, end),
    ).fetchall()
    conn.close()
    return [d for d, t, a in rows if t and (a / t * 100) < GAP_COVERAGE_THRESHOLD]


def _already_has_bdib(date_str: str, tickers: List[str]) -> set:
    """返回该日期 raw_bdib 中已有的 ticker 集合。

    只计 close 非 NULL 的有效 bar——存在空 bar（close 为 NULL）的 ticker
    视为缺失，需重新拉取。这是 2026-07-08 修复的"空 bar 残留"问题的延续。
    """
    import sqlite3
    conn = sqlite3.connect(str(Config.RAW_BDIB_DB))
    placeholders = ",".join(["?"] * len(tickers)) if tickers else "''"
    sql = (
        f"SELECT DISTINCT equ_ticker FROM raw_bdib "
        f"WHERE order_as_of_date = ? AND equ_ticker IN ({placeholders}) "
        f"AND close IS NOT NULL AND TRIM(CAST(close AS TEXT)) != ''"
    )
    rows = conn.execute(sql, [date_str, *tickers]).fetchall()
    conn.close()
    return {r[0] for r in rows}


def run_gap_backfill(
    start: str,
    end: str,
    force: bool,
    dry_run: bool,
    explicit_dates: Optional[List[str]] = None,
) -> int:
    """执行缺口回补。返回处理日期数。"""
    # 归一化日期
    def _norm(d: str) -> str:
        return d.replace("-", "")

    if explicit_dates:
        gap_dates = sorted({_norm(d) for d in explicit_dates})
        logger.info("使用显式日期列表: %d 个日期", len(gap_dates))
    else:
        gap_dates = _get_gap_dates(_norm(start), _norm(end))
        logger.info(
            "识别缺口日期 (p_arrival<%.0f%%, %s..%s): %d 个",
            GAP_COVERAGE_THRESHOLD, start, end, len(gap_dates),
        )

    if not gap_dates:
        logger.info("无缺口日期，无需回补")
        return 0

    logger.info("缺口日期: %s", gap_dates)

    # 获取白名单内 ticker→exchange 映射
    db = DatabaseFacade()
    bdid_exchange = [str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip()]
    ticker_exchange_map = db.fills_read.get_ticker_exchange_map(exchanges=bdid_exchange)

    total_dates = 0
    total_rows = 0
    total_fetched = 0

    for date_str in gap_dates:
        # 当日有成交的 ticker（且在白名单内）
        fill_tickers = [t for t in _get_fill_tickers_for_date(date_str) if t in ticker_exchange_map]
        if not fill_tickers:
            logger.info("  %s: 无白名单内有成交的 ticker，跳过", date_str)
            continue

        # 跳过已有数据的 ticker（除非 force）
        to_fetch = fill_tickers
        if not force:
            existing = _already_has_bdib(date_str, fill_tickers)
            to_fetch = [t for t in fill_tickers if t not in existing]
            if not to_fetch:
                logger.info("  %s: 全部 %d 个 ticker 已有 BDIB，跳过", date_str, len(fill_tickers))
                continue

        logger.info(
            "  %s: 待拉取 %d/%d 个 ticker (已有 %d 跳过)",
            date_str, len(to_fetch), len(fill_tickers),
            len(fill_tickers) - len(to_fetch),
        )

        if dry_run:
            total_dates += 1
            total_fetched += len(to_fetch)
            continue

        # 拉取 BDIB（仅当日有成交的 ticker）
        ticker_dates = {t: [date_str] for t in to_fetch}
        try:
            t0 = time.monotonic()
            bdib_map = fetch_bdib_for_fills(
                ticker_dates,
                interval=10,
                ticker_exchange_map=ticker_exchange_map,
            )
            if not bdib_map:
                logger.info("  %s: Bloomberg 返回空（可能超保留窗口或无行情）", date_str)
                continue

            # 合并当日 DataFrame
            parts = [df for key, df in bdib_map.items() if key.endswith(f"|{date_str}")]
            if not parts:
                logger.info("  %s: 无当日数据", date_str)
                continue
            bdib_df = parts[0] if len(parts) == 1 else _concat(parts)

            # 写入 raw_bdib
            from DataPipeline.storage.repositories.market_data import SqliteMarketDataWriteRepository
            writer = SqliteMarketDataWriteRepository()
            rows = writer.upsert_bdib_data(bdib_df, date_str=date_str)
            elapsed = time.monotonic() - t0
            logger.info(
                "  %s: upserted %d rows (%d bars, %d tickers, %.1fs)",
                date_str, rows, len(bdib_df), len(to_fetch), elapsed,
            )
            total_rows += rows
            total_dates += 1
            total_fetched += len(to_fetch)
            time.sleep(0.3)  # Bloomberg API 限流
        except Exception as e:
            logger.error("  %s: 拉取失败: %s", date_str, e, exc_info=True)

    logger.info("=" * 60)
    if dry_run:
        logger.info("[dry-run] 计划回补 %d 个日期、%d 个 ticker-date", total_dates, total_fetched)
    else:
        logger.info("回补完成: %d 个日期, %d 个 ticker-date, %d 行写入", total_dates, total_fetched, total_rows)
    logger.info("=" * 60)
    return total_dates


def _concat(parts: List) -> "object":
    import pandas as pd
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="窗口内 BDIB 缺口精准回补")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD（默认 today-180d）")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（默认上一工作日）")
    parser.add_argument("--dates", nargs="+", help="显式日期列表 YYYYMMDD/YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="强制重新拉取已有数据的 ticker")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不拉取")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 默认窗口: today-180d -> 上一工作日
    today = datetime.now().date()
    end = args.end or (today - timedelta(days=1)).strftime("%Y-%m-%d")
    start = args.start or (today - timedelta(days=Config.BDIB_API_RETENTION_DAYS)).strftime("%Y-%m-%d")

    run_gap_backfill(
        start, end,
        force=args.force,
        dry_run=args.dry_run,
        explicit_dates=args.dates,
    )


if __name__ == "__main__":
    main()
