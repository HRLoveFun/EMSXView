"""排查白名单内但 BDIB API 返回空的 ticker。

对 17 个在 BDIB_EXCHANGE 白名单内且已注册到 ticker_repository，
但 raw_bdib 中无数据的 ticker 逐个执行小样本 BDIB 拉取测试，
确认是否退市/停牌。确认后标记 outdated tombstone，后续 fetcher 自动跳过。

背景：这些 ticker 的 fetcher 曾尝试拉取但未获得数据，可能原因包括
退市、停牌、非交易日、或 Bloomberg BDIB API 对该 ticker 返回空。

用法：
    # 预览：仅报告排查结果，不标记 outdated
    python investigate_bdib_api_failures.py --dry-run

    # 执行排查并标记确认退市/停牌的 ticker
    python investigate_bdib_api_failures.py

    # 排查指定 ticker
    python investigate_bdib_api_failures.py --tickers "K US Equity,MMC US Equity"

注意：需要 Bloomberg 连接（BPIPE/xbbg）。
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

# ── 路径设置 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from DataPipeline.config import Config
from DataPipeline.common.outdated_tickers import (
    load_outdated_ticker_set,
    record_outdated_ticker,
)

logger = logging.getLogger(__name__)

# 17 个白名单内但无 BDIB 数据的 ticker
DEFAULT_FAILED_TICKERS: List[str] = [
    "9998819D US Equity",
    "CYBR US Equity",
    "FI US Equity",
    "K US Equity",
    "MMC US Equity",
    "AHT LN Equity",
    "PHNX LN Equity",
    "BALN SW Equity",
    "HELN SW Equity",
    "ROG SW Equity",
    "ADER1 IN Equity",
    "LTIM IN Equity",
    "TTMT IN Equity",
    "9613 JP Equity",
    "010620 KS Equity",
    "1CO GR Equity",
    "2596869D AU Equity",
]


def _get_recent_fill_dates(
    ticker: str,
    processed_fills_db: Path,
    count: int = 3,
) -> List[str]:
    """获取该 ticker 最近有成交的交易日（YYYYMMDD 格式）。

    Args:
        ticker: equ_ticker
        processed_fills_db: processed_fills.db 路径
        count: 返回的日期数量

    Returns:
        最近的交易日列表，按日期降序
    """
    if not processed_fills_db.exists():
        return []

    conn = sqlite3.connect(str(processed_fills_db), timeout=30)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT order_as_of_date FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE equ_ticker = ? AND order_as_of_date IS NOT NULL "
            f"ORDER BY order_as_of_date DESC LIMIT ?",
            (ticker, count),
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


def _test_bdib_fetch(
    ticker: str,
    date_str: str,
) -> Tuple[bool, str]:
    """对单个 ticker/date 执行 BDIB 拉取测试。

    Returns:
        (success, message): success=True 表示 API 返回了数据
    """
    try:
        from DataPipeline.acquisition.bdib_fetcher import fetch_bdib_for_ticker_date
    except ImportError as e:
        return False, f"导入 bdib_fetcher 失败: {e}"

    try:
        df = fetch_bdib_for_ticker_date(ticker=ticker, date_str=date_str)
        if df is None or df.empty:
            return False, f"API 返回空数据 (ticker={ticker}, date={date_str})"
        return True, f"API 返回 {len(df)} 行 (ticker={ticker}, date={date_str})"
    except Exception as e:
        return False, f"API 异常: {e} (ticker={ticker}, date={date_str})"


def _get_recent_weekdays(count: int = 3) -> List[str]:
    """获取最近几个工作日（YYYYMMDD 格式），用于回退测试。"""
    result: List[str] = []
    today = date.today()
    current = today
    while len(result) < count:
        current = current - timedelta(days=1)
        # 跳过周末
        if current.weekday() < 5:
            result.append(current.strftime("%Y%m%d"))
    return result


def investigate_ticker(
    ticker: str,
    processed_fills_db: Path,
) -> Tuple[bool, str, str]:
    """排查单个 ticker 的 BDIB API 状态。

    Returns:
        (has_data, reason, detail): has_data=True 表示 API 能返回数据
    """
    # 1. 尝试该 ticker 最近有成交的日期
    fill_dates = _get_recent_fill_dates(ticker, processed_fills_db, count=3)

    for date_str in fill_dates:
        success, msg = _test_bdib_fetch(ticker, date_str)
        if success:
            return True, "API 正常", msg
        logger.debug("  %s @ %s → %s", ticker, date_str, msg)

    # 2. 回退到最近几个工作日
    recent_dates = _get_recent_weekdays(count=3)
    for date_str in recent_dates:
        success, msg = _test_bdib_fetch(ticker, date_str)
        if success:
            return True, "API 正常", msg
        logger.debug("  %s @ %s → %s", ticker, date_str, msg)

    # 3. 所有尝试均失败
    detail = (
        f"测试了 {len(fill_dates)} 个成交日 + {len(recent_dates)} 个最近工作日，"
        f"BDIB API 全部返回空/异常。"
    )
    if fill_dates:
        detail += f" 成交日期: {', '.join(fill_dates)}"

    return False, "API 返回空", detail


def main() -> None:
    parser = argparse.ArgumentParser(
        description="排查白名单内但 BDIB API 返回空的 ticker"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅报告排查结果，不标记 outdated",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的 ticker 列表（覆盖默认 17 个）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细的 API 测试日志",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    tickers: List[str]
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = DEFAULT_FAILED_TICKERS

    processed_fills_db = Config.PROCESSED_FILLS_DB
    outdated_file = Config.OUTDATED_TICKERS_FILE

    # 加载已标记的 outdated ticker
    already_outdated = load_outdated_ticker_set(outdated_file)

    logger.info("排查 %d 个 ticker 的 BDIB API 状态 ...", len(tickers))
    logger.info("  processed_fills.db: %s", processed_fills_db)
    logger.info("  outdated_tickers: %s", outdated_file)

    confirmed_dead: List[str] = []
    confirmed_alive: List[str] = []

    for i, ticker in enumerate(tickers, 1):
        if ticker in already_outdated:
            logger.info("[%d/%d] %s → 已标记 outdated，跳过", i, len(tickers), ticker)
            continue

        logger.info("[%d/%d] 排查 %s ...", i, len(tickers), ticker)
        has_data, reason, detail = investigate_ticker(ticker, processed_fills_db)

        if has_data:
            logger.info("  → API 正常: %s", detail)
            confirmed_alive.append(ticker)
        else:
            logger.warning("  → 确认无数据: %s (%s)", reason, detail)
            confirmed_dead.append(ticker)

    # 汇总
    logger.info("=" * 60)
    logger.info("排查完成:")
    logger.info("  API 正常: %d 个", len(confirmed_alive))
    logger.info("  确认无数据: %d 个", len(confirmed_dead))

    if confirmed_alive:
        logger.info("  正常 ticker: %s", ", ".join(confirmed_alive))

    if confirmed_dead:
        logger.info("  无数据 ticker: %s", ", ".join(confirmed_dead))

    if not confirmed_dead:
        return

    if args.dry_run:
        logger.info("[dry-run] 未标记 outdated。去掉 --dry-run 执行标记。")
        return

    # 标记确认无数据的 ticker
    for ticker in confirmed_dead:
        entry = record_outdated_ticker(
            ticker=ticker,
            reason="BDIB API 返回空，疑似退市/停牌",
            detail=f"investigate_bdib_api_failures.py 确认无数据 ({__file__})",
            file_path=outdated_file,
        )
        logger.info("已标记 outdated: %s", entry.get("equ_ticker", ticker))

    logger.info("共标记 %d 个 ticker 为 outdated", len(confirmed_dead))


if __name__ == "__main__":
    main()
