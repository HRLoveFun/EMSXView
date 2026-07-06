"""
Fill Processor — transform cleaned EMSX fills into processed fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill.py.
All functions use EMSX column names (e.g. StrategyType not "Strategy Type",
FillPrice not "Exec Last Fill Px", exchange_exec_time not "Exchange Exec Time").

"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from DataPipeline.common.mapping import (
    EXCHANGE_AUCTION_TIME_ADJUST,
    close,
    closing_auction_times,
    currency_region,
    pov,
    twap,
    vwap,
)
from DataPipeline.config import Config

logger = logging.getLogger(__name__)

# ── Algo Classification ─────────────────────────────────────────────────────

def add_algo_column(df: pd.DataFrame) -> pd.DataFrame:
    """Classify fills into algo categories based on Broker + StrategyType.

    EMSX uses 'StrategyType' (not 'Strategy Type' as in Evaluation).

    注意：
      - 部分 Broker（例如 CROSSING）在 EMSX 中本就不提供 StrategyType，
        因此 StrategyType 为 NULL 或空字符串属于正常业务现象。
      - 这类记录无法匹配任何 algo 映射，最终归类为 ``algo="other"``，
        下游不应将其视为数据质量问题。
    """
    df = df.copy()
    df["algo"] = "other"


    def _apply_mapping(algo_name: str, mapping_dict: Dict[str, List[str]]):
        for broker, strategies in mapping_dict.items():
            if not strategies:
                continue
            mask = (df["Broker"] == broker) & (df["StrategyType"].isin(strategies))
            if mask.any():
                df.loc[mask, "algo"] = algo_name

    _apply_mapping("vwap", vwap)
    _apply_mapping("twap", twap)
    _apply_mapping("pov", pov)
    _apply_mapping("close", close)

    return df

# ── Currency Columns ─────────────────────────────────────────────────────────

def add_currency_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ccy_ticker and region columns from Currency."""
    df = df.copy()
    currency_upper = df["Currency"].astype(str).str.upper()
    df["ccy_ticker"] = np.where(
        currency_upper != "USD",
        "USD" + currency_upper + " Curncy",
        "USD Curncy",
    )
    df["region"] = df["Currency"].map(currency_region)
    return df

# ── Equity Ticker ────────────────────────────────────────────────────────────

def _ensure_composite_cache_table(conn) -> None:
    """确保 eur_composite_ticker_cache 表存在（幂等创建）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eur_composite_ticker_cache (
            raw_eur_ticker       TEXT PRIMARY KEY,
            composite_ticker     TEXT NOT NULL,
            created_at           TEXT DEFAULT (datetime('now')),
            updated_at           TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _load_composite_cache() -> Dict[str, str]:
    """从 ticker_registry.db 加载 EUR 复合代码缓存全量。

    缓存表体积极小（每只 EUR 股票一条记录），全量加载是最简单高效的方式。
    """
    import sqlite3
    db_path = str(Config.TICKER_REGISTRY_DB)
    try:
        conn = sqlite3.connect(db_path, timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    except Exception as e:
        logger.warning("无法连接 ticker_registry.db: %s", e)
        return {}
    try:
        _ensure_composite_cache_table(conn)
        cursor = conn.execute(
            "SELECT raw_eur_ticker, composite_ticker FROM eur_composite_ticker_cache"
        )
        cache = {row[0]: row[1] for row in cursor.fetchall()}
        if cache:
            logger.debug("加载 %d 条 EUR 复合代码缓存", len(cache))
        return cache
    except Exception as e:
        logger.warning("加载复合代码缓存失败: %s", e)
        return {}
    finally:
        conn.close()


def _save_composite_cache(mappings: Dict[str, str]) -> None:
    """将 Bloomberg 查询结果回写至 eur_composite_ticker_cache。

    使用 INSERT OR REPLACE 策略，已存在的条目会更新 updated_at。
    """
    import sqlite3
    db_path = str(Config.TICKER_REGISTRY_DB)
    try:
        conn = sqlite3.connect(db_path, timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    except Exception as e:
        logger.warning("无法连接 ticker_registry.db 以保存缓存: %s", e)
        return
    try:
        _ensure_composite_cache_table(conn)
        conn.executemany(
            """INSERT OR REPLACE INTO eur_composite_ticker_cache
               (raw_eur_ticker, composite_ticker, updated_at)
               VALUES (?, ?, datetime('now'))""",
            [(ticker, composite) for ticker, composite in mappings.items()]
        )
        conn.commit()
        logger.info("已缓存 %d 条 EUR 复合代码", len(mappings))
    except Exception as e:
        logger.warning("保存复合代码缓存失败: %s", e)
    finally:
        conn.close()


def add_equity_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """添加 equ_ticker 列（Bloomberg 股票代码）。

    对 EUR 股票采用缓存优先策略：
        ① 先查本地 eur_composite_ticker_cache
        ② 缓存未命中 → 查询 Bloomberg
        ③ BBG 结果回写缓存
        ④ 仍未命中 → 保留原始拼接 equ_ticker（fallback），记录 warning
    """
    required = ["Ticker", "Exchange", "Currency"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()

    # KRW tickers need zero-padding
    df["_processed_ticker"] = np.where(
        df["Currency"] == "KRW",
        df["Ticker"].astype(str).str.zfill(6),
        df["Ticker"].astype(str),
    )

    # v2 修复: 当 Ticker 或 Exchange 为空/空白时，拼接出 `"Ticker  Equity"` (双空格) 或
    # `" Equity"` 是错误语义；统一在拼接后用 `where` 替换为 `None`。
    exchange_blank = (
        df["Exchange"].isna()
        | (df["Exchange"].astype(str).str.strip() == "")
        | (df["Exchange"].astype(str).str.lower().isin(["nan", "none"]))
    )
    ticker_blank = (
        df["_processed_ticker"].isna()
        | (df["_processed_ticker"].astype(str).str.strip() == "")
        | (df["_processed_ticker"].astype(str).str.lower().isin(["nan", "none"]))
    )
    blank_mask = exchange_blank | ticker_blank

    df["equ_ticker"] = (
        df["_processed_ticker"] + " " + df["Exchange"] + " Equity"
    ).str.strip()
    # 空 ticker/exchange → None（不再保留拼接后的空串）
    df.loc[blank_mask, "equ_ticker"] = np.nan

    # 如果存在缺失 Ticker/Exchange 的行，记录为错误，避免后续聚合时产生空 equ_ticker
    blank_count = int(blank_mask.sum())
    if blank_count > 0:
        logger.error(
            "add_equity_ticker: %d 行因 Ticker 或 Exchange 缺失无法构造 equ_ticker",
            blank_count,
        )
        # 只在严格模式下报错；默认先警告，允许后续清洗脚本处理
        if Config.STRICT_MISSING_TICKER_VALIDATION:
            raise ValueError(
                f"{blank_count} 行缺少 Ticker 或 Exchange，无法构造 equ_ticker"
            )

    # ── EUR composite ticker resolution（缓存优先策略）──
    eur_mask = df["Currency"] == "EUR"
    if eur_mask.any():
        unique_eur_tickers = df.loc[eur_mask, "equ_ticker"].dropna().unique().tolist()
        logger.debug("EUR 股票 %d 行, %d 个唯一 ticker", eur_mask.sum(), len(unique_eur_tickers))

        # ① 加载本地缓存
        composite_cache = _load_composite_cache()

        # ② 拆分命中 / 未命中
        cache_hit = {t: v for t, v in composite_cache.items() if t in unique_eur_tickers}
        cache_miss = [t for t in unique_eur_tickers if t not in composite_cache]
        logger.debug(
            "EUR 复合代码: 缓存命中 %d, 未命中 %d",
            len(cache_hit), len(cache_miss),
        )

        # ③ 缓存未命中 → 查询 Bloomberg
        bbg_results: Dict[str, str] = {}
        if cache_miss:
            logger.info("查询 %d 个未命中的 EUR 复合代码 (BBG 超时=%ds)...",
                        len(cache_miss), Config.BBG_COMPOSITE_QUERY_TIMEOUT_SEC)
            bbg_results = _fetch_composite_tickers(cache_miss)
            if bbg_results:
                _save_composite_cache(bbg_results)
            logger.info("BBG 返回 %d 条 EUR 复合代码结果", len(bbg_results))
        elif not cache_hit:
            logger.warning("EUR 缓存为空且无 ticker 需查询 BBG — 保留原始拼接 equ_ticker")

        # ④ 合并结果: 命中 → composite ticker, 未命中 → 保留原始拼接值（fallback）
        composite_map = {**cache_hit, **bbg_results}
        if composite_map:
            original_values = df.loc[eur_mask, "equ_ticker"]
            mapped = original_values.map(composite_map)
            # 未命中的 ticker 保留原始拼接值，不再丢弃为 NaN
            df.loc[eur_mask, "equ_ticker"] = mapped.fillna(original_values)
            hit_count = int(mapped.notna().sum())
            fallback_count = int(original_values.notna().sum() - hit_count)
            if fallback_count > 0:
                logger.info(
                    "EUR 复合代码: 缓存/BBG 命中 %d 行, %d 行未命中保留原始拼接值",
                    hit_count, fallback_count,
                )
        else:
            # BBG 完全不可用且无缓存 → 保留原始拼接值，仅记录 warning
            logger.warning(
                "EUR composite ticker 缓存为空且 BBG 查询失败，%d 行保留原始拼接 equ_ticker",
                int(eur_mask.sum()),
            )

    return df.drop(columns=["_processed_ticker"])

def _fetch_one_bbg_chunk(chunk: List[str]) -> Any:
    """在独立线程中执行 blp.bdp，便于调用方设置超时。"""
    from xbbg import blp
    return blp.bdp(chunk, "EU_COMPOSITE_TICKER")


def _fetch_composite_tickers(
    tickers: List[str], chunk_size: int = 100, max_retries: int = 1,
    chunk_timeout: int = None,
) -> Dict[str, str]:
    """获取 EU_COMPOSITE_TICKER（通过 xbbg blp.bdp，每个 chunk 独立线程超时）。

    仅返回有效结果（过滤 NaN），避免 "nan" 字符串污染复合代码映射。

    每个 chunk 在独立线程中执行，超时后跳过该 chunk 继续处理下一个，
    确保单个 BBG 调用挂起不会拖死整条管线。
    """
    if chunk_timeout is None:
        chunk_timeout = Config.BBG_COMPOSITE_QUERY_TIMEOUT_SEC

    results: Dict[str, str] = {}
    if not tickers:
        return results

    try:
        from xbbg import blp  # noqa: F401 — 仅检查是否可导入
    except ImportError:
        logger.warning("xbbg 不可用；跳过 EUR 复合代码解析")
        return results

    total_chunks = (len(tickers) + chunk_size - 1) // chunk_size
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        chunk_idx = i // chunk_size
        logger.debug(
            "EUR 复合代码查询 chunk %d/%d (%d tickers)",
            chunk_idx + 1, total_chunks, len(chunk),
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # 在独立线程中运行 blp.bdp，超时后跳过该 chunk
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_fetch_one_bbg_chunk, chunk)
                    response = future.result(timeout=chunk_timeout)

                if "eu_composite_ticker" in response.columns:
                    valid_mask = response["eu_composite_ticker"].notna()
                    if valid_mask.any():
                        results.update(
                            response.loc[valid_mask, "eu_composite_ticker"]
                            .astype(str).to_dict()
                        )
                break  # 成功则跳出重试循环

            except FuturesTimeoutError:
                logger.warning(
                    "EUR 复合代码查询超时 (%ds) chunk %d/%d，跳过",
                    chunk_timeout, chunk_idx + 1, total_chunks,
                )
                break  # 超时不重试，直接跳过
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.debug(
                        "EUR 复合代码查询失败 chunk %d (尝试 %d/%d): %s",
                        chunk_idx + 1, attempt + 1, max_retries + 1, e,
                    )
                else:
                    logger.warning(
                        "EUR 复合代码查询失败 chunk %d/%d: %s",
                        chunk_idx + 1, total_chunks, e,
                    )

    return results

# ── Market Timestamp (10-second floor) ───────────────────────────────────────

def add_mkt_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add mkt_timestamp (10s floor) and is_closing_auction from exchange_exec_time.

    EMSX uses 'exchange_exec_time' (derived column) instead of Evaluation's
    'Exchange Exec Time'.
    """
    df = df.copy()

    # Parse exchange_exec_time to datetime for arithmetic
    exec_time_dt = pd.to_datetime(
        df["exchange_exec_time"].astype(str), format="%H:%M:%S.%f", errors="coerce"
    )
    mask_na = exec_time_dt.isna()
    if mask_na.any():
        exec_time_dt.loc[mask_na] = pd.to_datetime(
            df.loc[mask_na, "exchange_exec_time"].astype(str),
            format=Config.TIME_FORMAT,
            errors="coerce",
        )

    # Floor to 10-second intervals
    df["mkt_timestamp"] = exec_time_dt.dt.floor("10s").dt.strftime("%H:%M:%S")

    # Closing auction detection
    df["is_closing_auction"] = False

    for exchange, close_time_str in closing_auction_times.items():
        close_time = pd.to_datetime(close_time_str, format=Config.TIME_FORMAT).time()
        exch_mask = df["Exchange"] == exchange

        if not exch_mask.any():
            continue

        if exchange in EXCHANGE_AUCTION_TIME_ADJUST:
            adj_time = (exec_time_dt[exch_mask] + pd.Timedelta(minutes=1)).dt.time
            auction_mask = adj_time >= close_time
        else:
            mkt_time = pd.to_datetime(
                df.loc[exch_mask, "mkt_timestamp"], format="%H:%M:%S"
            ).dt.time
            auction_mask = mkt_time >= close_time

        df.loc[
            exch_mask & auction_mask.reindex(df.index, fill_value=False),
            "is_closing_auction",
        ] = True

    return df

# ── Route Market Timestamp ───────────────────────────────────────────────────

def add_route_mkt_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add route_mkt_timestamp by applying 10-second floor to route_as_of_time.

    EMSX derived columns:
      - exchange_exec_time (local exchange time)
      - route_as_of_time (local exchange time)
    """
    df = df.copy()

    def _to_seconds(series: pd.Series) -> pd.Series:
        dt_series = pd.to_datetime(
            series.astype(str), format="%H:%M:%S.%f", errors="coerce"
        )
        mask = dt_series.isna()
        if mask.any():
            dt_series.loc[mask] = pd.to_datetime(
                series.loc[mask].astype(str), format=Config.TIME_FORMAT, errors="coerce"
            )
        return dt_series.dt.hour * 3600 + dt_series.dt.minute * 60 + dt_series.dt.second

    rt_sec = _to_seconds(df["route_as_of_time"])

    # Round to 10-second intervals
    new_rt_total = (rt_sec // 10) * 10

    hours = (new_rt_total // 3600).fillna(0).astype(int)
    minutes = ((new_rt_total % 3600) // 60).fillna(0).astype(int)
    seconds = (new_rt_total % 60).fillna(0).astype(int)

    time_strs = (
        hours.astype(str).str.zfill(2)
        + ":"
        + minutes.astype(str).str.zfill(2)
        + ":"
        + seconds.astype(str).str.zfill(2)
    )
    df["route_mkt_timestamp"] = pd.to_datetime(
        time_strs, format="%H:%M:%S", errors="coerce"
    ).dt.time

    mask_nan = rt_sec.isna()
    df.loc[mask_nan, "route_mkt_timestamp"] = None

    return df

# ── Pipeline: Process a DataFrame ───────────────────────────────────────────

def process_fills(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all transformation steps to a cleaned EMSX fills DataFrame.

    Expects input that has already been through clean_emsx_fills()
    (i.e. DFD filtered, exchange times derived, columns normalized).

    Pipeline:
        1. add_algo_column
        2. add_currency_columns
        3. add_equity_ticker
        4. add_mkt_timestamp_columns
        5. add_route_mkt_timestamp_columns
    """
    if df.empty:
        return df

    # 确保字符串列为干净字符串 (非 'nan')
    for col in ["Broker", "StrategyType", "Exchange", "Ticker", "Currency", "Side"]:
        if col in df.columns:
            if col == "Exchange":
                # Exchange 列特殊处理: 字符串 "nan" → "NA" (荷兰交易所代码被 pandas 误转)
                # 但真正的缺失值必须保持 NaN，不能降级为空字符串，避免后续时区转换
                # 回退到 NY 时间并产生错误日期。
                exchange_clean = df[col].astype(str).str.strip().replace("nan", "NA")
                empty_mask = exchange_clean.isin(["", "None", "NONE", "nan", "NaN"])
                df[col] = np.where(empty_mask, np.nan, exchange_clean)
            else:
                df[col] = df[col].astype(str).str.strip().replace("nan", "").replace("None", "")

    logger.info("处理 %d 条成交记录: algo → ccy → ticker → timestamp", len(df))
    print(f"[PROGRESS] processing {len(df)} fills", flush=True)
    processed = (
        df.pipe(add_algo_column)
        .pipe(add_currency_columns)
        .pipe(add_equity_ticker)
        .pipe(add_mkt_timestamp_columns)
        .pipe(add_route_mkt_timestamp_columns)
    )

    # 处理完成后做硬校验：Exchange 与 equ_ticker 不允许出现空/NULL
    # 这些空值会导致 S3 聚合缺 Ticker/Side/Currency 列或 BDIB 集成失败。
    if "Exchange" in processed.columns:
        empty_exchange = processed["Exchange"].isna() | (processed["Exchange"].astype(str).str.strip() == "")
        if empty_exchange.any():
            logger.error("process_fills: %d 行 Exchange 为空", int(empty_exchange.sum()))
            if Config.STRICT_MISSING_TICKER_VALIDATION:
                raise ValueError(f"{empty_exchange.sum()} 行 Exchange 为空，请检查上游数据")
    if "equ_ticker" in processed.columns:
        empty_equ = processed["equ_ticker"].isna() | (processed["equ_ticker"].astype(str).str.strip() == "")
        if empty_equ.any():
            logger.error("process_fills: %d 行 equ_ticker 为空", int(empty_equ.sum()))
            if Config.STRICT_MISSING_TICKER_VALIDATION:
                raise ValueError(f"{empty_equ.sum()} 行 equ_ticker 为空，请检查上游数据")

    logger.info(f"Processed {len(processed)} fills -> added algo/ccy/ticker/timestamp columns")
    return processed

def process_raw_fills(df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: clean then process.

    Convenience function that runs clean_emsx_fills() + process_fills()
    in sequence. Use when the input has NOT been pre-cleaned.

    Args:
        df: Raw EMSX DataFrame or List[Dict].
    """
    from .fill_cleaner import clean_emsx_fills

    cleaned = clean_emsx_fills(df)
    return process_fills(cleaned)
