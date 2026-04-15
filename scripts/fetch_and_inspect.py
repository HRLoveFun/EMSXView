"""
fetch_and_inspect.py - 拉取 20260309 的 fills 数据并逐步处理，每一步保存为 Excel 供人工检查。

执行流程:
    Step 0: 通过 Bloomberg EMSX History API 拉取 2026-03-09 的原始 fills 数据
    Step 1: 读取原始 Excel (fetched), 保存为 step1_raw_fetched.xlsx
    Step 2: 清洗数据 (clean_emsx_fills), 保存为 step2_cleaned.xlsx
    Step 3: 算法分类 (add_algo_column), 保存为 step3_with_algo.xlsx
    Step 4: 货币与区域 (add_currency_columns), 保存为 step4_with_currency.xlsx
    Step 5: 证券Ticker (add_equity_ticker), 保存为 step5_with_equ_ticker.xlsx
    Step 6: 市场时间戳 (add_mkt_timestamp_columns), 保存为 step6_with_mkt_timestamp.xlsx
    Step 7: 路由时间戳 (add_route_mkt_timestamp_columns), 保存为 step7_processed.xlsx
    Step 8: 10秒聚合 (generate_agg_fills_10s), 保存为 step8_agg_10s.xlsx
    Step 9: 1分钟聚合 (generate_agg_fills_1min), 保存为 step9_agg_1min.xlsx

使用方式:
    python scripts/fetch_and_inspect.py
    python scripts/fetch_and_inspect.py --team "TeamName"
    python scripts/fetch_and_inspect.py --force
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# 将项目根目录加入 sys.path，以便导入 CostView 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COSTVIEW_DIR = PROJECT_ROOT / "CostView"
if str(COSTVIEW_DIR) not in sys.path:
    sys.path.insert(0, str(COSTVIEW_DIR))

from src.fill_fetch import FillFetch, setup_logging
from src.fill_cleaner import clean_emsx_fills
from src.fill_processor import (
    process_fills,
    add_algo_column,
    add_currency_columns,
    add_equity_ticker,
    add_mkt_timestamp_columns,
    add_route_mkt_timestamp_columns,
)
from src.fill_aggregator import generate_agg_fills_10s, generate_agg_fills_1min

logger = logging.getLogger(__name__)

TARGET_DATE = date(2026, 3, 9)
OUTPUT_DIR = PROJECT_ROOT / "data" / "inspection" / "20260309"


def save_excel(df: pd.DataFrame, filename: str) -> Path:
    """Save DataFrame to Excel in output directory, return file path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = OUTPUT_DIR / filename
    df.to_excel(file_path, index=False, engine="openpyxl")
    logger.info(f"  -> Saved {len(df)} rows x {len(df.columns)} cols -> {file_path}")
    return file_path


def step0_fetch(team: Optional[str] = None, force: bool = False) -> List[Dict[str, Any]]:
    """Step 0: 从 Bloomberg API 拉取原始 fills 数据."""
    logger.info("=" * 70)
    logger.info("Step 0: Fetch fills from Bloomberg EMSX History API")
    logger.info(f"  Date: {TARGET_DATE} | Team: {team or 'TradingSystem (login-based)'}")
    logger.info("=" * 70)

    fetcher = FillFetch(data_dir=str(PROJECT_ROOT / "CostView" / "data" / "fills"))
    try:
        result = fetcher.fetch_day(TARGET_DATE, team=team, force=force)
        logger.info(f"  Result: {result.get('message', result.get('error'))}")
        if result.get("file_path"):
            logger.info(f"  Excel: {result['file_path']}")

        if not result["success"]:
            raise RuntimeError(f"Fetch failed: {result.get('error', 'unknown error')}")

        # Read the raw fills back from Excel for the pipeline
        if result.get("file_path") and Path(result["file_path"]).exists():
            raw_df = pd.read_excel(result["file_path"], engine="openpyxl")
            fills = raw_df.to_dict("records")
            logger.info(f"  Read back {len(fills)} records from Excel")
            return fills

        if result.get("rows_fetched", 0) == 0:
            logger.warning("  No fills found for this date")
            return []

        raise RuntimeError("Fetch succeeded but no file_path returned")
    finally:
        fetcher.close()


def step1_raw_fetched(fills: List[Dict[str, Any]]) -> pd.DataFrame:
    """Step 1: 保存原始拉取数据 (未清洗)."""
    logger.info("=" * 70)
    logger.info("Step 1: Raw fetched data (Bloomberg API 原始输出, 未经清洗)")
    logger.info("=" * 70)

    df = pd.DataFrame(fills)
    logger.info(f"  Shape: {df.shape}")
    logger.info(f"  Columns: {list(df.columns)}")
    save_excel(df, "step1_raw_fetched.xlsx")
    return df


def step2_cleaned(fills: List[Dict[str, Any]]) -> pd.DataFrame:
    """Step 2: 清洗数据 - 解析时间字段、时区转换、数据类型规范化."""
    logger.info("=" * 70)
    logger.info("Step 2: Cleaned data (clean_emsx_fills)")
    logger.info("  - DateTimeOfFill -> local_fill_datetime, order_as_of_date, exchange_exec_time")
    logger.info("  - NyOrderCreateAsOfDateTime -> order_as_of_time (local)")
    logger.info("  - NyTranCreateAsOfDateTime -> route_as_of_time (local)")
    logger.info("  - 字符串去空格、数字类型规范化")
    logger.info("=" * 70)

    df = clean_emsx_fills(fills)
    logger.info(f"  Shape: {df.shape}")
    new_cols = [c for c in df.columns if c not in (fills[0].keys() if fills else [])]
    logger.info(f"  New derived columns: {new_cols}")
    save_excel(df, "step2_cleaned.xlsx")
    return df


def step3_algo(df: pd.DataFrame) -> pd.DataFrame:
    """Step 3: 算法分类 - 根据 Broker + StrategyType 分类为 vwap/twap/pov/close/other."""
    logger.info("=" * 70)
    logger.info("Step 3: Algo classification (add_algo_column)")
    logger.info("  - Broker + StrategyType -> algo (vwap/twap/pov/close/other)")
    logger.info("=" * 70)

    df = add_algo_column(df)
    if "algo" in df.columns:
        logger.info(f"  Algo distribution:\n{df['algo'].value_counts().to_string()}")
    save_excel(df, "step3_with_algo.xlsx")
    return df


def step4_currency(df: pd.DataFrame) -> pd.DataFrame:
    """Step 4: 货币列 - 添加 ccy_ticker 和 region."""
    logger.info("=" * 70)
    logger.info("Step 4: Currency columns (add_currency_columns)")
    logger.info("  - Currency -> ccy_ticker (e.g. USDJPY Curncy)")
    logger.info("  - Currency -> region (APAC/EMEA/NSA)")
    logger.info("=" * 70)

    df = add_currency_columns(df)
    if "region" in df.columns:
        logger.info(f"  Region distribution:\n{df['region'].value_counts().to_string()}")
    save_excel(df, "step4_with_currency.xlsx")
    return df


def step5_equity_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Step 5: 证券Ticker - 构建 Bloomberg equity ticker (含 EUR composite 解析)."""
    logger.info("=" * 70)
    logger.info("Step 5: Equity ticker (add_equity_ticker)")
    logger.info("  - Ticker + Exchange + Currency -> equ_ticker (e.g. 7203 JP Equity)")
    logger.info("  - KRW tickers: 零填充 (zfill 6)")
    logger.info("  - EUR tickers: 尝试获取 EU_COMPOSITE_TICKER")
    logger.info("=" * 70)

    df = add_equity_ticker(df)
    if "equ_ticker" in df.columns:
        sample = df["equ_ticker"].dropna().head(5).tolist()
        logger.info(f"  Sample equ_ticker: {sample}")
    save_excel(df, "step5_with_equ_ticker.xlsx")
    return df


def step6_mkt_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Step 6: 市场时间戳 - 10秒取整 + 收盘竞价检测."""
    logger.info("=" * 70)
    logger.info("Step 6: Market timestamp (add_mkt_timestamp_columns)")
    logger.info("  - exchange_exec_time -> mkt_timestamp (10秒向下取整)")
    logger.info("  - 交易所收盘时间检测 -> is_closing_auction")
    logger.info("=" * 70)

    df = add_mkt_timestamp_columns(df)
    if "is_closing_auction" in df.columns:
        auction_count = df["is_closing_auction"].sum()
        logger.info(f"  Closing auction fills: {auction_count}")
    if "mkt_timestamp" in df.columns:
        sample = df["mkt_timestamp"].dropna().head(5).tolist()
        logger.info(f"  Sample mkt_timestamp: {sample}")
    save_excel(df, "step6_with_mkt_timestamp.xlsx")
    return df


def step7_route_mkt_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Step 7: 路由市场时间戳 - 间接时区转换."""
    logger.info("=" * 70)
    logger.info("Step 7: Route market timestamp (add_route_mkt_timestamp_columns)")
    logger.info("  - route_as_of_time (local) -> route_mkt_timestamp (10s floor)")
    logger.info("  - 10秒向下取整")
    logger.info("=" * 70)

    df = add_route_mkt_timestamp_columns(df)
    if "route_mkt_timestamp" in df.columns:
        sample = df["route_mkt_timestamp"].dropna().head(5).tolist()
        logger.info(f"  Sample route_mkt_timestamp: {sample}")
    save_excel(df, "step7_processed.xlsx")
    return df


def step8_agg_10s(df: pd.DataFrame) -> pd.DataFrame:
    """Step 8: 10秒聚合 - 按 OrderId + mkt_timestamp 分组, VWAP + 补零."""
    logger.info("=" * 70)
    logger.info("Step 8: 10-second aggregation (generate_agg_fills_10s)")
    logger.info("  - 按 (OrderId, mkt_timestamp) 分组")
    logger.info("  - FillShares 求和, FillPrice 计算 VWAP")
    logger.info("  - 分类字段取唯一值或标记 'Mult'")
    logger.info("  - 缺失的10秒间隔补零填充")
    logger.info("=" * 70)

    agg = generate_agg_fills_10s(df)
    if not agg.empty:
        logger.info(f"  Shape: {agg.shape}")
        logger.info(f"  Unique orders: {agg['OrderId'].nunique()}")
    save_excel(agg, "step8_agg_10s.xlsx")
    return agg


def step9_agg_1min(df: pd.DataFrame) -> pd.DataFrame:
    """Step 9: 1分钟聚合 - 在10秒聚合基础上向下取整到1分钟."""
    logger.info("=" * 70)
    logger.info("Step 9: 1-minute aggregation (generate_agg_fills_1min)")
    logger.info("  - mkt_timestamp 向下取整到 1 分钟")
    logger.info("  - 重新计算 VWAP")
    logger.info("=" * 70)

    agg = generate_agg_fills_1min(df)
    if not agg.empty:
        logger.info(f"  Shape: {agg.shape}")
        logger.info(f"  Unique orders: {agg['OrderId'].nunique()}")
    save_excel(agg, "step9_agg_1min.xlsx")
    return agg


def run_full_inspection(team: Optional[str] = None, force: bool = False):
    """执行完整的拉取 + 逐步处理 + 每步保存 Excel."""
    logger.info("=" * 70)
    logger.info("Fetch & Inspect Pipeline for 2026-03-09")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info("=" * 70)

    # Step 0: Fetch
    fills = step0_fetch(team=team, force=force)
    if not fills:
        logger.warning("No fills data to process. Exiting.")
        return

    # Step 1: Raw fetched
    step1_raw_fetched(fills)

    # Step 2: Cleaned
    df = step2_cleaned(fills)
    if df.empty:
        logger.warning("Cleaned data is empty. Exiting.")
        return

    # Step 3-7: Individual processing steps
    df = step3_algo(df)
    df = step4_currency(df)
    df = step5_equity_ticker(df)
    df = step6_mkt_timestamp(df)
    df = step7_route_mkt_timestamp(df)

    # Step 8: 10s aggregation
    agg_10s = step8_agg_10s(df)

    # Step 9: 1min aggregation
    step9_agg_1min(agg_10s)

    logger.info("=" * 70)
    logger.info("All steps completed. Check output files in:")
    logger.info(f"  {OUTPUT_DIR}")
    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="拉取 20260309 fills 数据并逐步处理，每步保存 Excel"
    )
    parser.add_argument(
        "--team", type=str, default=None,
        help="EMSX Team 名称 (默认使用 TradingSystem scope)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制重新拉取 (忽略去重检查)"
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    run_full_inspection(team=args.team, force=args.force)


if __name__ == "__main__":
    main()
