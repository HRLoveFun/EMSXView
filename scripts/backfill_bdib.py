"""fill_bdib 回补脚本 — 将缺失日期的 fill_bdib 数据从已有 BDIB 数据补算。

策略:
  - 从 processed_raw_bdib 加载已有 BDIB 市场数据
  - 从 processed_fills 加载 agg_fills_10s 成交数据
  - 调用 integrate_fills_bdib_for_date() 执行集成
  - 写入 fill_bdib.db

安全措施:
  - 仅追加 (INSERT OR REPLACE), 不删除任何已存在数据
  - 每日期独立处理, 单日失败不影响其他日期
  - 写入前检查 fill_bdib 是否已有该日期数据
"""

import gc
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager, AccessTier
from DataPipeline.processing.fill_bdib_integrated import integrate_fills_bdib_for_date
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_bdib")


def get_processed_bdib_for_date(cm: ConnectionManager, date_str: str) -> pd.DataFrame:
    """从 raw_bdib 表加载并增强指定日期的 BDIB 数据。

    当前环境中 processed_raw_bdib.db 为空库, BDIB 增强数据从未持久化。
    因此直接从 raw_bdib 加载原始数据并调用 compute_derived_fields() 做增强。
    """
    # 1. 从 raw_bdib 加载原始 BDIB 数据
    conn = cm.get_connection("raw_bdib", AccessTier.READ)
    try:
        df = pd.read_sql_query(
            f"SELECT * FROM {Config.RAW_BDIB_TABLE} WHERE order_as_of_date = ?",
            conn.raw_connection,
            params=[date_str],
        )
    finally:
        conn.close()

    if df.empty:
        return df

    # 2. 调用 compute_derived_fields() 生成增强字段
    #    (log_chg_pct_10s, fluctuation 等衍生列)
    from DataPipeline.storage.repositories.market_data import (
        SqliteMarketDataWriteRepository,
    )
    market_write = SqliteMarketDataWriteRepository(connection_manager=cm)
    enriched = market_write.compute_derived_fields(df)
    logger.info("%s: raw_bdib %d 行 -> 增强 %d 列", date_str, len(df), len(enriched.columns))

    return enriched


def get_agg_fills_for_date(cm: ConnectionManager, date_str: str) -> pd.DataFrame:
    """从 processed_fills 加载指定日期的聚合成交数据。"""
    conn = cm.get_connection("processed_fills", AccessTier.READ)
    try:
        # 先尝试 agg_fills_10s
        df = pd.read_sql_query(
            f"SELECT * FROM {Config.AGG_10S_TABLE} WHERE order_as_of_date = ?",
            conn.raw_connection,
            params=[date_str],
        )
        if df.empty:
            # 回退到 agg_processed_fills
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        return df
    finally:
        conn.close()


def check_fill_bdib_exists(cm: ConnectionManager, date_str: str) -> bool:
    """检查 fill_bdib 是否已有该日期数据。"""
    conn = cm.get_connection("fill_bdib", AccessTier.READ)
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE} WHERE order_as_of_date = ?",
            (date_str,),
        ).fetchone()[0]
        return count > 0
    finally:
        conn.close()


def backfill_date(cm: ConnectionManager, date_str: str) -> dict:
    """回补单个日期的 fill_bdib 数据。"""
    result = {"date": date_str, "status": "unknown", "rows": 0}

    # 1. 检查是否已存在
    if check_fill_bdib_exists(cm, date_str):
        result["status"] = "skipped"
        logger.info("%s: fill_bdib 已存在, 跳过", date_str)
        return result

    # 2. 加载 processed_raw_bdib 数据
    bdib_df = get_processed_bdib_for_date(cm, date_str)
    if bdib_df.empty:
        result["status"] = "no_bdib"
        logger.warning("%s: processed_raw_bdib 无数据, 跳过", date_str)
        return result
    logger.info("%s: 加载 %d 行 BDIB 数据", date_str, len(bdib_df))

    # 3. 加载 agg_fills
    agg_df = get_agg_fills_for_date(cm, date_str)
    if agg_df.empty:
        result["status"] = "no_fills"
        logger.warning("%s: 无聚合成交数据, 跳过", date_str)
        return result
    logger.info("%s: 加载 %d 行聚合成交数据", date_str, len(agg_df))

    # 4. 加载 ticker_exchange_map
    try:
        ticker_conn = cm.get_connection("processed_fills", AccessTier.READ)
        ticker_rows = ticker_conn.execute(
            "SELECT equ_ticker, Exchange FROM ticker_date_mapping WHERE Exchange IS NOT NULL"
        ).fetchall()
        ticker_conn.close()
        ticker_exchange_map = {str(r[0]): str(r[1]) for r in ticker_rows if r[0] and r[1]}
    except Exception:
        ticker_exchange_map = {}

    # 5. 执行集成
    t0 = time.time()
    integrated_df = integrate_fills_bdib_for_date(
        agg_df,
        date_str,
        bdib_data=bdib_df,
        ticker_exchange_map=ticker_exchange_map,
        fx_rates=None,
    )

    if integrated_df.empty:
        result["status"] = "empty_result"
        logger.warning("%s: 集成后无有效行 (fill_volume 全为 0)", date_str)
        return result

    # 6. 写入 fill_bdib
    from DataPipeline.storage.repositories.integrated import SqliteIntegratedWriteRepository
    writer = SqliteIntegratedWriteRepository(connection_manager=cm)
    rows_written = writer.upsert_integrated_data(integrated_df, date_str=date_str)

    # 7. 标记处理完成
    try:
        conn = cm.get_connection("processed_fills", AccessTier.WRITE)
        conn.execute(
            "INSERT OR REPLACE INTO processing_log (order_as_of_date, stage, row_count, processed_at) VALUES (?, ?, ?, datetime('now'))",
            (date_str, "bdib_integrated", len(integrated_df)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("%s: 标记 processing_log 失败: %s", date_str, e)

    elapsed = time.time() - t0
    result["status"] = "ok"
    result["rows"] = rows_written

    # 验证 9 个累积列
    cum_cols = [
        "cum_vwap", "cum_fill_vwap", "cum_slippage_bps",
        "cum_slippage_usd", "cum_volume_pct", "cum_tracking_error",
        "cum_info_ratio", "cum_interval_volatility",
        "standard_cum_interval_volatility",
    ]
    non_null_counts = {
        c: int(integrated_df[c].notna().sum()) if c in integrated_df.columns else 0
        for c in cum_cols
    }
    non_null_pct = {
        c: f"{non_null_counts[c] / len(integrated_df) * 100:.1f}%"
        for c in cum_cols
    }

    logger.info(
        "%s: 集成完成, %d 行 (%.1fs). 累积列非空率: %s",
        date_str, rows_written, elapsed,
        ", ".join(f"{c}={non_null_pct[c]}" for c in cum_cols if non_null_counts[c] > 0),
    )

    # 内存清理
    del bdib_df, agg_df, integrated_df
    gc.collect()

    return result


def main():
    # 回补日期列表: fill_bdib 最新日 20260608, 缺失 20260609-20260611
    dates_to_backfill = ["20260609", "20260610", "20260611"]

    logger.info("=" * 60)
    logger.info("fill_bdib 回补开始: %s -> %s", dates_to_backfill[0], dates_to_backfill[-1])
    logger.info("=" * 60)

    cm = ConnectionManager()
    results = []

    for date_str in dates_to_backfill:
        try:
            result = backfill_date(cm, date_str)
            results.append(result)
        except Exception as e:
            logger.error("%s: 回补失败 — %s", date_str, e)
            results.append({"date": date_str, "status": "error", "rows": 0, "error": str(e)})
        gc.collect()

    # 输出汇总
    logger.info("=" * 60)
    logger.info("回补完成汇总:")
    total_rows = 0
    for r in results:
        status_icon = "OK" if r["status"] == "ok" else r["status"].upper()
        logger.info("  %s: %s — %d rows", r["date"], status_icon, r.get("rows", 0))
        total_rows += r.get("rows", 0)
    logger.info("总计: %d 行写入 fill_bdib.db", total_rows)
    logger.info("=" * 60)

    # 验证
    conn = cm.get_connection("fill_bdib", AccessTier.READ)
    for date_str in dates_to_backfill:
        count = conn.execute(
            "SELECT COUNT(*) FROM fill_bdib WHERE order_as_of_date = ?",
            (date_str,),
        ).fetchone()[0]
        logger.info("  验证 %s: %d 行", date_str, count)
    conn.close()

    # 失败时返回非零退出码
    failed = [r for r in results if r["status"] not in ("ok", "skipped")]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
