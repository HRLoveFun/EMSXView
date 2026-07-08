"""补注册 ticker_repository 中缺失的 equ_ticker → Exchange 映射。

从 processed_fills.db 提取 DISTINCT equ_ticker, Exchange 中不在
ticker_repository 表的记录，执行 upsert 注册。

背景：108 个 ticker 出现在 processed_fills 但未注册到 ticker_repository，
导致 S5 IntegrateBDIBStage 的 get_ticker_exchange_map() 对它们不可见，
BDIB fetcher 从未尝试拉取这些 ticker 的行情数据。

用法：
    # 预览将要补注册的 ticker（不写入）
    python backfill_ticker_repository.py --dry-run

    # 仅补注册 HK 市场的 ticker
    python backfill_ticker_repository.py --exchange HK

    # 执行补注册
    python backfill_ticker_repository.py
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

# ── 路径设置 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from DataPipeline.config import Config

logger = logging.getLogger(__name__)


def _find_unregistered_tickers(
    processed_fills_db: Path,
    ticker_registry_db: Path,
    exchange_filter: str | None = None,
) -> List[Tuple[str, str]]:
    """返回 processed_fills 中有但 ticker_repository 中没有的 (equ_ticker, Exchange) 对。

    Args:
        processed_fills_db: processed_fills.db 路径
        ticker_registry_db: ticker_registry.db 路径
        exchange_filter: 仅返回该 exchange 的 ticker（可选）

    Returns:
        [(equ_ticker, exchange), ...] 列表，exchange 已大写化
    """
    proc_conn = sqlite3.connect(str(processed_fills_db), timeout=30)
    try:
        # 读取已注册 ticker 集合
        reg_conn = sqlite3.connect(str(ticker_registry_db), timeout=30)
        try:
            registered = {
                str(row[0]).strip()
                for row in reg_conn.execute(
                    "SELECT equ_ticker FROM ticker_repository"
                ).fetchall()
            }
        finally:
            reg_conn.close()

        # 从 processed_fills 提取未注册 ticker
        query = (
            f"SELECT DISTINCT equ_ticker, Exchange "
            f"FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE equ_ticker IS NOT NULL "
            f"  AND TRIM(equ_ticker) != '' "
            f"  AND Exchange IS NOT NULL "
            f"  AND TRIM(Exchange) != ''"
        )
        params: List[str] = []
        if exchange_filter:
            query += " AND UPPER(TRIM(Exchange)) = UPPER(?)"
            params.append(exchange_filter)

        rows = proc_conn.execute(query, params).fetchall()
    finally:
        proc_conn.close()

    # 过滤掉已注册的 + 清理脏值
    unregistered: List[Tuple[str, str]] = []
    for ticker, exchange in rows:
        ticker_str = str(ticker).strip()
        exchange_str = str(exchange).strip().upper()
        # 跳过无效值
        if ticker_str.lower() in ("none", "nan", ""):
            continue
        if exchange_str.lower() in ("none", "nan", ""):
            continue
        if ticker_str in registered:
            continue
        unregistered.append((ticker_str, exchange_str))

    return unregistered


def _upsert_tickers(
    ticker_registry_db: Path,
    tickers: List[Tuple[str, str]],
) -> int:
    """将 ticker 列表 upsert 到 ticker_repository。

    Returns:
        实际写入的行数
    """
    if not tickers:
        return 0

    conn = sqlite3.connect(str(ticker_registry_db), timeout=30)
    try:
        conn.executemany(
            "INSERT INTO ticker_repository (equ_ticker, exchange, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(equ_ticker) DO UPDATE SET "
            "    exchange = excluded.exchange, "
            "    updated_at = datetime('now')",
            tickers,
        )
        conn.commit()
        return len(tickers)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="补注册 ticker_repository 中缺失的 equ_ticker → Exchange 映射"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不写入数据库",
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default=None,
        help="仅补注册指定 exchange 的 ticker（如 HK, CN, BZ）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出每个 ticker 的详细信息",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    processed_fills_db = Config.PROCESSED_FILLS_DB
    ticker_registry_db = Config.TICKER_REGISTRY_DB

    if not processed_fills_db.exists():
        logger.error("processed_fills.db 不存在: %s", processed_fills_db)
        sys.exit(1)
    if not ticker_registry_db.exists():
        logger.error("ticker_registry.db 不存在: %s", ticker_registry_db)
        sys.exit(1)

    logger.info("扫描未注册 ticker ...")
    logger.info("  processed_fills.db: %s", processed_fills_db)
    logger.info("  ticker_registry.db: %s", ticker_registry_db)

    unregistered = _find_unregistered_tickers(
        processed_fills_db=processed_fills_db,
        ticker_registry_db=ticker_registry_db,
        exchange_filter=args.exchange,
    )

    if not unregistered:
        logger.info("未发现未注册 ticker，ticker_repository 已完整覆盖 processed_fills")
        return

    # 按 exchange 分组统计
    by_exchange: dict[str, list[str]] = {}
    for ticker, exchange in unregistered:
        by_exchange.setdefault(exchange, []).append(ticker)

    logger.info("发现 %d 个未注册 ticker，涉及 %d 个 exchange:",
                len(unregistered), len(by_exchange))
    for exchange in sorted(by_exchange, key=lambda e: -len(by_exchange[e])):
        tickers = by_exchange[exchange]
        logger.info("  %s: %d 个 ticker", exchange, len(tickers))
        if args.verbose:
            for t in sorted(tickers):
                logger.info("    %s", t)

    if args.dry_run:
        logger.info("[dry-run] 未写入数据库。去掉 --dry-run 执行补注册。")
        return

    # 执行写入
    written = _upsert_tickers(
        ticker_registry_db=ticker_registry_db,
        tickers=unregistered,
    )
    logger.info("成功补注册 %d 个 ticker 到 ticker_repository", written)


if __name__ == "__main__":
    main()
