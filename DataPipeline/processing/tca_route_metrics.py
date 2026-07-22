"""TCA 路由级指标计算引擎。

负责从 raw_fills、processed_fills 和 raw_bdib 计算新 schema 的 34 个字段
（17 个源值 + 17 个计算指标），并组装为 tca_route_summary 表的数据。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from DataPipeline.common.exchange_tz import batch_convert_ny_to_local, convert_ny_to_local
from DataPipeline.common.mapping import closing_auction_times, EXCHANGE_AUCTION_TIME_ADJUST
from DataPipeline.config import Config
from DataPipeline.storage.market_store import MarketStoreReader

logger = logging.getLogger(__name__)

# PWP 支持的 POV Rate 档位
_PWP_RATES = [0.05, 0.10, 0.15, 0.20, 0.25]
_PWP_COLUMNS = ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]


# 输出列顺序（严格匹配 schema）
_OUTPUT_COLUMNS = [
    # 源值（17）
    "OrderId", "RouteId", "order_as_of_date", "Exchange", "Account",
    "equ_ticker", "Currency", "Side", "Amount", "RouteShares",
    "Type", "LimitPrice", "StopPrice", "Broker", "StrategyType",
    "algo", "TraderName",
    # 计算指标（18）：fill_count 为该路由下 FillId 的去重计数
    "fill_count", "fill", "fill_continuous", "fill_close",
    "par_rate", "par_rate_continuous", "par_rate_close",
    "p_avg", "p_avg_continuous",
    "pnl_vwap", "pnl_vwap_continuous",
    "RPM", "RPM_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
]


def compute_route_metrics_for_date(
    raw_fills_df: pd.DataFrame,
    processed_fills_df: pd.DataFrame,
    raw_bdib_df: pd.DataFrame,
    date_str: str,
) -> pd.DataFrame:
    """计算单个交易日的所有路由级 TCA 指标。

    Args:
        raw_fills_df: raw_fills 表数据，至少包含源值字段。
        processed_fills_df: processed_fills 表数据，至少包含成交明细。
        raw_bdib_df: raw_bdib 表数据，包含市场分时行情。
        date_str: 交易日（YYYYMMDD），用于过滤和日志。

    Returns:
        包含 34 个字段的 DataFrame，每行对应一个 (OrderId, RouteId, order_as_of_date)。
    """
    if raw_fills_df.empty or processed_fills_df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    source_df = _build_source_values(raw_fills_df, processed_fills_df, date_str)
    if source_df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    routes = source_df.to_dict("records")
    rows: list[dict[str, Any]] = []

    for route in routes:
        row = _compute_route_metrics(route, processed_fills_df, raw_bdib_df, date_str)
        rows.append(row)

    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def load_raw_bdib_for_date(
    date_str: str,
    equ_tickers: Optional[list[str]] = None,
    raw_bdib_db_path: Optional[Path] = None,
    parquet_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """按日期读取 raw_bdib，SQLite 缺失时回退到 Parquet 分区。

    生产环境中 raw_bdib.db 只保留较近热数据，历史 BDIB 已按年月分区写入
    Parquet。本函数先尝试 SQLite，返回为空时回退到 Parquet 读取，确保
    历史交易日（如 20260303 之前）也能纳入 TCA 计算。

    Args:
        date_str: 交易日（YYYYMMDD）。
        equ_tickers: 可选的 ticker 过滤列表，用于减少 Parquet 读取量。
        raw_bdib_db_path: SQLite 路径，默认使用 ``Config.RAW_BDIB_DB``。
        parquet_dir: Parquet 分区根目录，默认使用 ``Config.BDIB_PARQUET_DIR``。

    Returns:
        包含 ``equ_ticker``、``order_as_of_date``、``mkt_timestamp``、
        ``volume``、``value`` 的 DataFrame。
    """
    db_path = raw_bdib_db_path or Config.RAW_BDIB_DB
    parquet_dir = parquet_dir or Config.BDIB_PARQUET_DIR
    columns = ["equ_ticker", "order_as_of_date", "mkt_timestamp", "volume", "value"]
    requested_tickers = set(equ_tickers) if equ_tickers else set()

    # 1. 优先从 SQLite 热数据读取
    df_sql = pd.DataFrame(columns=columns)
    if db_path.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(db_path), timeout=Config.SQLITE_BUSY_TIMEOUT_MS)
            sql = f"SELECT {', '.join(columns)} FROM raw_bdib WHERE order_as_of_date = ?"
            params: list[Any] = [date_str]
            if requested_tickers:
                placeholders = ",".join(["?"] * len(requested_tickers))
                sql += f" AND equ_ticker IN ({placeholders})"
                params.extend(requested_tickers)
            df_sql = pd.read_sql_query(sql, conn, params=params)
            conn.close()
        except Exception as e:
            logger.warning("从 SQLite 读取 raw_bdib 失败: %s", e)

    # 未指定 ticker 列表且 SQLite 有数据时直接返回；否则按需补全缺失 ticker
    if requested_tickers:
        sql_tickers = set(df_sql["equ_ticker"].unique()) if not df_sql.empty else set()
        missing_tickers = requested_tickers - sql_tickers
        if not missing_tickers:
            return df_sql
    else:
        if not df_sql.empty:
            return df_sql
        missing_tickers = set()

    # 2. SQLite 未覆盖时，从 Parquet 分区读取缺失 ticker 并合并
    if not parquet_dir.exists():
        return df_sql

    if not any(parquet_dir.rglob("*.parquet")):
        return df_sql

    try:
        reader = MarketStoreReader(parquet_dir)
        sql = (
            f"SELECT {', '.join(columns)} FROM {reader.table_name} "
            "WHERE order_as_of_date = ?"
        )
        df_pq = reader.query(sql, [date_str])
        reader.close()
        if not df_pq.empty:
            if missing_tickers:
                df_pq = df_pq[df_pq["equ_ticker"].isin(missing_tickers)].copy()
            df_pq = df_pq[columns]
            if df_sql.empty:
                return df_pq
            return pd.concat([df_sql, df_pq], ignore_index=True)
    except Exception as e:
        logger.warning("从 Parquet 读取 raw_bdib 失败: %s", e)

    return df_sql





def _build_source_values(
    raw_fills_df: pd.DataFrame,
    processed_fills_df: pd.DataFrame,
    date_str: str,
) -> pd.DataFrame:
    """从 raw_fills 和 processed_fills 构建路由级源值。"""
    # 两个表 order_as_of_date 格式可能不一致：raw_fills 为 YYYY-MM-DD，processed_fills 为 YYYYMMDD
    raw_fills_df = raw_fills_df.copy()
    processed_fills_df = processed_fills_df.copy()
    raw_fills_df["order_as_of_date"] = _normalize_oad(raw_fills_df["order_as_of_date"])
    processed_fills_df["order_as_of_date"] = _normalize_oad(processed_fills_df["order_as_of_date"])

    raw = raw_fills_df[raw_fills_df["order_as_of_date"] == date_str].copy()
    if raw.empty:
        return pd.DataFrame()

    raw_source_cols = [
        "OrderId", "RouteId", "order_as_of_date", "Exchange", "Account",
        "Currency", "Side", "Amount", "RouteShares", "Type", "LimitPrice",
        "StopPrice", "Broker", "StrategyType", "TraderName",
    ]
    for col in raw_source_cols:
        if col not in raw.columns:
            raw[col] = None

    raw_grouped = raw.groupby(["OrderId", "RouteId", "order_as_of_date"], as_index=False).agg(
        Exchange=("Exchange", lambda x: _first_non_null(x)),
        Account=("Account", lambda x: _first_non_null(x)),
        Currency=("Currency", lambda x: _first_non_null(x)),
        Side=("Side", lambda x: _first_non_null(x)),
        Amount=("Amount", lambda x: _first_non_null(x)),
        RouteShares=("RouteShares", lambda x: _first_non_null(x)),
        Type=("Type", lambda x: _first_non_null(x)),
        LimitPrice=("LimitPrice", lambda x: _first_non_null(x)),
        StopPrice=("StopPrice", lambda x: _first_non_null(x)),
        Broker=("Broker", lambda x: _first_non_null(x)),
        StrategyType=("StrategyType", lambda x: _first_non_null(x)),
        TraderName=("TraderName", lambda x: _first_non_null(x)),
    )

    proc = processed_fills_df[processed_fills_df["order_as_of_date"] == date_str].copy()
    proc_source_cols = ["OrderId", "RouteId", "order_as_of_date", "equ_ticker", "algo"]
    for col in proc_source_cols:
        if col not in proc.columns:
            proc[col] = None

    proc_grouped = proc.groupby(["OrderId", "RouteId", "order_as_of_date"], as_index=False).agg(
        equ_ticker=("equ_ticker", lambda x: _first_non_null(x)),
        algo=("algo", lambda x: _first_non_null(x)),
    )

    merged = pd.merge(
        raw_grouped,
        proc_grouped,
        on=["OrderId", "RouteId", "order_as_of_date"],
        how="inner",
    )
    return merged


def _normalize_oad(series: pd.Series) -> pd.Series:
    """将 order_as_of_date 统一规范化为 YYYYMMDD 字符串。"""
    # 先尝试按 datetime 解析，否则保留原字符串并去除非数字字符
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    # 对于无法解析的字符串（如已经是 YYYYMMDD），直接保留并去除非数字
    result = []
    for dt, raw in zip(parsed, series):
        if pd.notna(dt):
            result.append(dt.strftime("%Y%m%d"))
        else:
            cleaned = str(raw).replace("-", "").replace(" ", "").split("+")[0]
            result.append(cleaned[:8] if cleaned.isdigit() else str(raw))
    return pd.Series(result, index=series.index)




def _first_non_null(series: pd.Series) -> Any:
    """返回 Series 中第一个非空值。"""
    cleaned = series.dropna()
    return cleaned.iloc[0] if not cleaned.empty else None


def _compute_route_metrics(
    route: dict[str, Any],
    processed_fills_df: pd.DataFrame,
    raw_bdib_df: pd.DataFrame,
    date_str: str,
) -> dict[str, Any]:
    """计算单个路由的 34 个字段。"""
    order_id = route["OrderId"]
    route_id = route["RouteId"]

    fills = processed_fills_df[
        (processed_fills_df["OrderId"] == order_id)
        & (processed_fills_df["RouteId"] == route_id)
        & (processed_fills_df["order_as_of_date"] == date_str)
    ].copy()

    result = _init_result(route)

    if fills.empty:
        return result

    fills = _prepare_fills(fills)
    total_fill = float(fills["FillShares"].sum())
    result["fill"] = total_fill if total_fill > 0 else 0.0
    # fill_count：路由下 FillId 的去重计数
    if "FillId" in fills.columns and not fills["FillId"].isna().all():
        result["fill_count"] = int(fills["FillId"].nunique())
    else:
        result["fill_count"] = int(len(fills))

    continuous_fills = fills[fills["is_closing_auction"] == 0]
    close_fills = fills[fills["is_closing_auction"] == 1]
    result["fill_continuous"] = float(continuous_fills["FillShares"].sum()) if not continuous_fills.empty else 0.0
    result["fill_close"] = float(close_fills["FillShares"].sum()) if not close_fills.empty else 0.0

    result["p_avg"] = _weighted_average(fills, "FillPrice", "FillShares")
    result["p_avg_continuous"] = _weighted_average(continuous_fills, "FillPrice", "FillShares")

    side = str(route.get("Side") or "").strip().upper()
    side_sign = _pnl_side_sign(side)

    exchange_code = route.get("Exchange")
    first_fill_time = _get_first_fill_time(fills, exchange_code)
    last_fill_time = _get_last_fill_time(fills, exchange_code)
    first_close_time = _get_first_fill_time(close_fills, exchange_code)

    equ_ticker = route.get("equ_ticker")
    all_bars = _get_all_day_bars(raw_bdib_df, equ_ticker, date_str)

    if all_bars is not None and not all_bars.empty:
        last_bdib_time = _get_last_bar_time(all_bars)
        # par_rate：终点取末笔 fill 与 bdib 末行时间的更前者，避免 closing auction fill
        # 时间戳晚于 bdib 末行导致窗口越界
        full_end_time = _min_time(last_fill_time, last_bdib_time)
        full_window = _slice_bars(all_bars, first_fill_time, full_end_time)

        # par_rate_continuous：保持原有逻辑（首笔 fill → 首笔 closing auction fill，不含）
        continuous_window = _slice_bars(all_bars, first_fill_time, first_close_time, inclusive_end=False)

        # par_rate_close：按交易所收盘集合竞价固定时段取 bars，不依赖 fill 时间戳
        close_window = _get_closing_auction_window(all_bars, exchange_code)

        # par_rate
        result["par_rate"] = _compute_par_rate(total_fill, full_window)
        result["par_rate_continuous"] = _compute_par_rate(result["fill_continuous"], continuous_window)
        result["par_rate_close"] = _compute_par_rate(result["fill_close"], close_window)

        # VWAP 与 pnl_vwap
        result["pnl_vwap"] = _compute_pnl_vwap(full_window, result["p_avg"], side_sign)
        result["pnl_vwap_continuous"] = _compute_pnl_vwap(continuous_window, result["p_avg_continuous"], side_sign)

        # PWP：从首笔成交时间开始累计全日线性 bars
        pwp_values = _compute_all_pwp(all_bars, total_fill, result["p_avg"], side_sign, first_fill_time)
        for col, val in pwp_values.items():
            result[col] = val

    # RPM
    result["RPM"] = _compute_rpm(fills, result["p_avg"], total_fill, side)
    result["RPM_continuous"] = _compute_rpm(continuous_fills, result["p_avg_continuous"], result["fill_continuous"], side)

    return result


def _init_result(route: dict[str, Any]) -> dict[str, Any]:
    """初始化结果字典，所有计算字段默认 None。"""
    result = dict(route)
    for col in _OUTPUT_COLUMNS[17:]:
        result[col] = None
    return result


def _prepare_fills(fills: pd.DataFrame) -> pd.DataFrame:
    """标准化 processed_fills 数值列。"""
    fills = fills.copy()
    fills["FillShares"] = pd.to_numeric(fills["FillShares"], errors="coerce")
    fills["FillPrice"] = pd.to_numeric(fills["FillPrice"], errors="coerce")
    fills["is_closing_auction"] = (
        pd.to_numeric(fills["is_closing_auction"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    return fills


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str) -> Optional[float]:
    """计算加权平均值。"""
    if df.empty:
        return None
    values = pd.to_numeric(df[value_col], errors="coerce")
    weights = pd.to_numeric(df[weight_col], errors="coerce")
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return None
    return float((values[mask] * weights[mask]).sum() / weights[mask].sum())


def _pnl_side_sign(side: str) -> int:
    """PnL 约定：Buy=+1, Sell=-1。"""
    if side.startswith("B"):
        return 1
    if side.startswith("S"):
        return -1
    return 0


def _pnl_in_bps(
    benchmark: Optional[float],
    execution_price: Optional[float],
    side_sign: int,
) -> Optional[float]:
    """计算 (benchmark / execution_price - 1) * side_sign * 10000 bps。"""
    if benchmark is None or execution_price is None or execution_price == 0 or side_sign == 0:
        return None
    return (benchmark / execution_price - 1.0) * side_sign * 10000.0


def _get_first_fill_time(fills: pd.DataFrame, exchange_code: Optional[str]) -> Optional[str]:
    """获取路由最早成交的本地交易所时间。"""
    return _get_fill_time(fills, exchange_code, "min")


def _get_last_fill_time(fills: pd.DataFrame, exchange_code: Optional[str]) -> Optional[str]:
    """获取路由最晚成交的本地交易所时间。"""
    return _get_fill_time(fills, exchange_code, "max")


def _get_fill_time(
    fills: pd.DataFrame, exchange_code: Optional[str], mode: str,
) -> Optional[str]:
    """获取路由首笔或末笔成交的本地交易所时间。"""
    if fills.empty or "DateTimeOfFill" not in fills.columns:
        return None
    try:
        local_dts = batch_convert_ny_to_local(
            fills["DateTimeOfFill"],
            pd.Series([exchange_code] * len(fills), index=fills.index),
        )
        times = local_dts.dt.strftime(Config.TIME_FORMAT).dropna().tolist()
    except ValueError:
        # Exchange code 未知时与旧行为保持一致：返回 None
        return None
    if not times:
        return None
    return min(times) if mode == "min" else max(times)



def _get_last_bar_time(bars: pd.DataFrame) -> Optional[str]:
    """返回 bars 中最大的 mkt_timestamp。"""
    if bars is None or bars.empty or "mkt_timestamp" not in bars.columns:
        return None
    return str(bars["mkt_timestamp"].max())


def _min_time(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """返回两个时间字符串中较小者，任一为空则返回另一者。"""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _get_closing_auction_window(
    bars: pd.DataFrame,
    exchange_code: Optional[str],
) -> Optional[pd.DataFrame]:
    """获取交易所收盘集合竞价时段的 bars。

    收盘集合竞价结束时间由 ``closing_auction_times`` 定义；对于需要 +1min
    调整的市场（``EXCHANGE_AUCTION_TIME_ADJUST``），开始时间为结束时间前
    1 分钟，其余市场开始时间与结束时间相同。该定义与 fill_processor 中
    ``is_closing_auction`` 的判定规则保持一致，避免 closing auction fill
    时间戳与 bdib 时间不一致导致的窗口为空问题。
    """
    if bars is None or bars.empty or exchange_code is None:
        return None

    exch_upper = str(exchange_code).strip().upper()
    close_time_str = closing_auction_times.get(exch_upper)
    if close_time_str is None:
        return None

    # 与 fill_processor 保持一致：需要 +1min 调整的市场，auction 从 close-1min 开始
    if exch_upper in EXCHANGE_AUCTION_TIME_ADJUST:
        start_dt = pd.to_datetime(close_time_str, format=Config.TIME_FORMAT) - pd.Timedelta(minutes=1)
        start_time = start_dt.strftime(Config.TIME_FORMAT)
    else:
        start_time = close_time_str

    return _slice_bars(bars, start_time, close_time_str)


def _get_all_day_bars(
    raw_bdib_df: pd.DataFrame,
    equ_ticker: Optional[str],
    date_str: str,
) -> Optional[pd.DataFrame]:
    """获取当日全部 raw_bdib bars。"""
    if not equ_ticker or raw_bdib_df.empty:
        return None
    bars = raw_bdib_df[
        (raw_bdib_df["equ_ticker"] == equ_ticker)
        & (raw_bdib_df["order_as_of_date"] == date_str)
    ].copy()
    if bars.empty:
        return None
    bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce").fillna(0.0)
    bars["value"] = pd.to_numeric(bars["value"], errors="coerce")
    return bars


def _slice_bars(
    bars: pd.DataFrame,
    start_time: Optional[str],
    end_time: Optional[str],
    inclusive_end: bool = True,
) -> Optional[pd.DataFrame]:
    """按时间切片 bars。"""
    if bars is None or bars.empty or start_time is None or end_time is None or start_time > end_time:
        return None
    if inclusive_end:
        sliced = bars[(bars["mkt_timestamp"] >= start_time) & (bars["mkt_timestamp"] <= end_time)]
    else:
        sliced = bars[(bars["mkt_timestamp"] >= start_time) & (bars["mkt_timestamp"] < end_time)]
    return sliced if not sliced.empty else None


def _compute_par_rate(fill_volume: float, bars: Optional[pd.DataFrame]) -> Optional[float]:
    """计算 par_rate = fill / sum(volume)。"""
    if bars is None or bars.empty or fill_volume is None or fill_volume <= 0:
        return None
    total_volume = float(bars["volume"].sum())
    return (fill_volume / total_volume) if total_volume > 0 else None


def _compute_pnl_vwap(
    bars: Optional[pd.DataFrame],
    p_avg: Optional[float],
    side_sign: int,
) -> Optional[float]:
    """计算 pnl_vwap = (vwap / p_avg - 1) * side_sign * 10000 bps。"""
    if bars is None or bars.empty or p_avg is None or p_avg == 0 or side_sign == 0:
        return None
    total_volume = float(bars["volume"].sum())
    total_value = float(bars["value"].sum()) if bars["value"].notna().any() else 0.0
    if total_volume <= 0 or total_value <= 0:
        return None
    vwap = total_value / total_volume
    return _pnl_in_bps(vwap, p_avg, side_sign)


def _compute_all_pwp(
    all_bars: Optional[pd.DataFrame],
    fill_volume: float,
    p_avg: Optional[float],
    side_sign: int,
    start_time: Optional[str],
) -> dict[str, Optional[str | float]]:
    """计算所有 PWP 档位。不满足条件时返回 None。"""
    result: dict[str, Optional[str | float]] = {col: None for col in _PWP_COLUMNS}
    if all_bars is None or all_bars.empty or fill_volume <= 0 or p_avg is None or p_avg == 0 or side_sign == 0 or start_time is None:
        return result

    bars = all_bars[all_bars["mkt_timestamp"] >= start_time].sort_values("mkt_timestamp").copy()
    if bars.empty:
        return result

    cumulative_volume = 0.0
    cumulative_value = 0.0
    thresholds = {col: fill_volume / rate for col, rate in zip(_PWP_COLUMNS, _PWP_RATES)}
    hit: dict[str, bool] = {col: False for col in _PWP_COLUMNS}

    for _, bar in bars.iterrows():
        vol = float(bar["volume"]) if pd.notna(bar["volume"]) else 0.0
        val = float(bar["value"]) if pd.notna(bar["value"]) else 0.0
        cumulative_volume += vol
        cumulative_value += val

        for col, threshold in thresholds.items():
            if hit[col] or threshold <= 0:
                continue
            if cumulative_volume >= threshold:
                pwp = cumulative_value / cumulative_volume if cumulative_volume > 0 else None
                result[col] = _pnl_in_bps(pwp, p_avg, side_sign) if pwp is not None else None
                hit[col] = True

    return result


def _compute_rpm(
    fills: pd.DataFrame,
    p_avg: Optional[float],
    fill_total: Optional[float],
    side: str,
) -> Optional[float]:
    """计算 RPM 指标。"""
    if fills.empty or p_avg is None or fill_total is None or fill_total == 0:
        return None

    prices = pd.to_numeric(fills["FillPrice"], errors="coerce")
    shares = pd.to_numeric(fills["FillShares"], errors="coerce")
    mask = prices.notna() & shares.notna()
    if not mask.any():
        return None

    side_upper = side.upper()
    if side_upper.startswith("B"):
        better = shares[mask & (prices < p_avg)].sum()
    elif side_upper.startswith("S"):
        better = shares[mask & (prices > p_avg)].sum()
    else:
        return None

    return float(better / fill_total) if fill_total > 0 else None
