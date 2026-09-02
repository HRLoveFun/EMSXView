"""TCA 路由级指标计算引擎。

负责从 raw_fills、processed_fills 和 raw_bdib 计算新 schema 的字段
（17 个源值 + 计算指标），并组装为 tca_route_summary 表的数据。

★ bar 时间戳区间语义（2026-09 覆盖率修复固化）：
    BDIB bar 的时间戳为区间起点 —— 末 bar 覆盖 [timestamp, 收盘竞价结束)，
    已包含收盘竞价时段的全部成交量（xbbg bdib day session 不返回独立竞价
    bar）；fill 时间戳为成交回报时刻，可能晚于竞价结束（回报链路延迟）。
    因此纯竞价路由（fill 晚于全部 bar）的窗口计算钳制到末 bar，见
    ``_is_auction_fill`` / ``_last_bar_window``；禁止再按时间点语义将
    竞价时段成交判定为"窗口越界"。
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
    # 003-tca-core-benchmarks: Phase 0 核心基准
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
    # 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击分解
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "cost_stddev", "cost_p95", "cost_cvar",
    "order_duration_sec", "exec_rate_shares_per_min",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "recovery_truncated",
    # 007-costview-report-filters: 路由级 USD 汇率（fill 量加权，成交金额换算）
    "fx_rate",
]


def compute_route_metrics_for_date(
    raw_fills_df: pd.DataFrame,
    processed_fills_df: pd.DataFrame,
    raw_bdib_df: pd.DataFrame,
    date_str: str,
    daily_summary_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """计算单个交易日的所有路由级 TCA 指标。

    Args:
        raw_fills_df: raw_fills 表数据，至少包含源值字段。
        processed_fills_df: processed_fills 表数据，至少包含成交明细。
        raw_bdib_df: raw_bdib 表数据，包含市场分时行情。
        date_str: 交易日（YYYYMMDD），用于过滤和日志。
        daily_summary_df: bdib_daily_summary 表数据（可选，Phase 0 起用于
            收盘价基准；缺失时 p_close/close_cost_bps/opportunity_cost 保持 None）。

    Returns:
        包含 55 个字段的 DataFrame，每行对应一个 (OrderId, RouteId, order_as_of_date)。
    """
    if raw_fills_df.empty or processed_fills_df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    source_df = _build_source_values(raw_fills_df, processed_fills_df, date_str)
    if source_df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    routes = source_df.to_dict("records")
    rows: list[dict[str, Any]] = []

    for route in routes:
        row = _compute_route_metrics(
            route, processed_fills_df, raw_bdib_df, date_str,
            daily_summary_df=daily_summary_df,
        )
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
        ``volume``、``value``、``close``、``open`` 的 DataFrame。
    """
    db_path = raw_bdib_db_path or Config.RAW_BDIB_DB
    parquet_dir = parquet_dir or Config.BDIB_PARQUET_DIR
    columns = [
        "equ_ticker", "order_as_of_date", "mkt_timestamp",
        "volume", "value", "close", "open",
    ]
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
        "NyOrderCreateAsOfDateTime",
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
        NyOrderCreateAsOfDateTime=("NyOrderCreateAsOfDateTime", lambda x: _first_non_null(x)),
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
    daily_summary_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """计算单个路由的 55 个字段。"""
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

    # 007-costview-report-filters: 路由级 fx_rate（fill 量加权，USD per 1 单位本币）
    result["fx_rate"] = _weighted_average(fills, "fx_rate", "FillShares")

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
        # bar 语义对齐：纯竞价路由的 fill 时间戳（含回报延迟）晚于全部 bar，
        # 时间点切片为空；末 bar 覆盖区间已含竞价成交量，市场分母钳制到末 bar
        if full_window is None and _is_auction_fill(first_fill_time, last_bdib_time, exchange_code):
            full_window = _last_bar_window(all_bars)

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

    # ── 003-tca-core-benchmarks: Phase 0 核心基准（flag 门控）──
    if Config.TCA_CORE_BENCHMARKS_ENABLED:
        # 到达价 P0：首笔成交时间之前最近 bar 的 close
        p_arrival = _compute_arrival_price(all_bars, first_fill_time)
        result["p_arrival"] = p_arrival
        # 收盘价 Pn：bdib_daily_summary.daily_close（缺省回退到当日最后 bar close）
        p_close = _compute_close_price(daily_summary_df, equ_ticker, date_str, all_bars)
        result["p_close"] = p_close

        result["arrival_cost_bps"] = _pnl_in_bps(p_arrival, result["p_avg"], side_sign)
        result["close_cost_bps"] = _pnl_in_bps(p_close, result["p_avg"], side_sign)

        # 机会成本 = (RouteShares - fill) * (Pn - P0) * side_sign
        route_shares = route.get("RouteShares")
        if route_shares is not None and p_arrival is not None and p_close is not None and side_sign != 0:
            try:
                unexecuted = float(route_shares) - total_fill
                result["opportunity_cost"] = unexecuted * (p_close - p_arrival) * side_sign
            except (TypeError, ValueError):
                result["opportunity_cost"] = None

        # ── 003-tca-core-benchmarks: Phase 1（flag 门控）──
        if Config.TCA_RISK_IMPACT_ENABLED:
            # 决策价 Pd：NyOrderCreateAsOfDateTime 之前最近 bar close；盘前取首 bar open
            order_create = route.get("NyOrderCreateAsOfDateTime")
            p_decision = _compute_decision_price(all_bars, order_create, exchange_code)
            result["p_decision"] = p_decision

            # Wagner IS 分解（全部为货币成本，单位与成交价一致）
            if p_decision is not None and side_sign != 0:
                route_shares = route.get("RouteShares")
                if route_shares is not None:
                    try:
                        rs = float(route_shares)
                        result["delay_cost"] = rs * (p_arrival - p_decision) * side_sign if p_arrival is not None else None
                    except (TypeError, ValueError):
                        result["delay_cost"] = None
                result["trading_cost"] = (
                    total_fill * (result["p_avg"] - p_arrival) * side_sign
                    if p_arrival is not None and result["p_avg"] is not None
                    else None
                )
                # wagner_is = delay + trading + opportunity
                parts = [result.get("delay_cost"), result.get("trading_cost"), result.get("opportunity_cost")]
                if all(p is not None for p in parts):
                    result["wagner_is"] = parts[0] + parts[1] + parts[2]
                    if p_decision != 0:
                        try:
                            result["wagner_is_bps"] = result["wagner_is"] / (rs * p_decision) * 10000
                        except (TypeError, ZeroDivisionError):
                            result["wagner_is_bps"] = None

            # 风险维度：fill_bdib cum_slippage_bps 时间序列
            risk_metrics = _compute_risk_metrics(
                processed_fills_df, order_id, route_id, date_str
            )
            result.update(risk_metrics)

            # 订单历时与执行速率
            duration, rate = _compute_order_duration(fills, total_fill, exchange_code)
            result["order_duration_sec"] = duration
            result["exec_rate_shares_per_min"] = rate

            # 暂时/永久冲击分解（4 恢复窗口：5/10/30min + 次日收盘）
            impact = _compute_impact_metrics(
                all_bars, daily_summary_df, result["p_avg"],
                p_arrival, last_fill_time, side_sign, date_str,
                equ_ticker,
            )
            for col, val in impact.items():
                result[col] = val

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
    if "fx_rate" in fills.columns:
        fills["fx_rate"] = pd.to_numeric(fills["fx_rate"], errors="coerce")
    return fills


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str) -> Optional[float]:
    """计算加权平均值。"""
    if df.empty or value_col not in df.columns or weight_col not in df.columns:
        return None
    values = pd.to_numeric(df[value_col], errors="coerce")
    weights = pd.to_numeric(df[weight_col], errors="coerce")
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return None
    return float((values[mask] * weights[mask]).sum() / weights[mask].sum())


def _pnl_side_sign(side: str) -> int:
    """PnL 约定：Buy=-1, Sell=+1（负=差，与 PnL 指标一致）。

    与 _pnl_in_bps 配合：benchmark 在前、execution 在后，
    (execution / benchmark - 1) * side_sign * 10000 即 PnL 符号
    （负=跑输基准，正=跑赢基准）。
    """
    if side.startswith("B"):
        return -1
    if side.startswith("S"):
        return 1
    return 0


def _pnl_in_bps(
    benchmark: Optional[float],
    execution_price: Optional[float],
    side_sign: int,
) -> Optional[float]:
    """计算 (execution_price / benchmark - 1) * side_sign * 10000 bps。

    PnL 约定：负=跑输基准（差），正=跑赢基准（优）。
    benchmark 为基准价（到达价/收盘价/VWAP/恢复价），execution_price 为成交均价。
    """
    if benchmark is None or benchmark == 0 or execution_price is None or side_sign == 0:
        return None
    return (execution_price / benchmark - 1.0) * side_sign * 10000.0


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


#: 竞价成交回报延迟容差（分钟）：fill 时间戳可能晚于竞价结束时刻（回报链路延迟），
#: 容差内仍视为竞价时段成交；超出容差属异常数据，不触发末 bar fallback
_AUCTION_FILL_TOLERANCE_MINUTES = 5


def _last_bar_window(bars: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """返回按时间排序后的末 bar（单根窗口）。

    bar 时间戳为区间起点语义：末 bar 覆盖 [timestamp, 收盘竞价结束)，已包含
    收盘竞价时段的全部成交量。纯竞价路由（fill 时间戳晚于全部 bar）的市场
    分母应取末 bar，而非因时间点比较得出空窗口。
    """
    if bars is None or bars.empty:
        return None
    return bars.sort_values("mkt_timestamp").tail(1)


def _is_auction_fill(
    first_fill_time: Optional[str],
    last_bdib_time: Optional[str],
    exchange_code: Optional[str],
) -> bool:
    """判定 fill 是否为收盘竞价时段成交（fill 时间戳晚于全部 BDIB bar）。

    条件：
    - 必要：first_fill_time 晚于 last_bdib_time（fill 落在全部 bar 之后）
    - 充分：且未超出收盘竞价结束时刻 + 回报延迟容差（超出属异常数据，不 fallback）
    - 交易所无竞价定义（closing_auction_times 无映射）时不 fallback，保持 NULL
    """
    if first_fill_time is None or last_bdib_time is None or first_fill_time <= last_bdib_time:
        return False
    close_time_str = closing_auction_times.get(str(exchange_code or "").strip().upper())
    if close_time_str is None:
        return False
    try:
        close_dt = pd.to_datetime(close_time_str, format=Config.TIME_FORMAT)
        fill_dt = pd.to_datetime(first_fill_time, format=Config.TIME_FORMAT)
    except ValueError:
        return False
    return fill_dt <= close_dt + pd.Timedelta(minutes=_AUCTION_FILL_TOLERANCE_MINUTES)


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

    close_window = _slice_bars(bars, start_time, close_time_str)
    if close_window is None:
        # bar 语义对齐：末 bar 覆盖 [timestamp, 竞价结束)，其时间戳早于竞价结束
        # 时刻时覆盖区间与竞价窗口重叠 —— 竞价撮合量实际落在末 bar，分母取末 bar
        bars_sorted = bars.sort_values("mkt_timestamp")
        if str(bars_sorted["mkt_timestamp"].iloc[-1]) < close_time_str:
            return bars_sorted.tail(1)
    return close_window


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
    """计算 pnl_vwap = (p_avg / vwap - 1) * side_sign * 10000 bps（PnL 约定：负=差）。"""
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


# ═══════════════════════════════════════════════════════════════════════════
# 003-tca-core-benchmarks: Phase 0 + Phase 1 新增计算函数
# 理论依据: Perold (1988) "The Implementation Shortfall"; Kissell (2014)
# *The Science of Algorithmic Trading and Portfolio Management* §3.7-3.13
# ═══════════════════════════════════════════════════════════════════════════


def _compute_arrival_price(
    all_bars: Optional[pd.DataFrame],
    first_fill_time: Optional[str],
) -> Optional[float]:
    """到达价 P0：首笔成交时间之前最近 bar 的 close。

    理论依据: Kissell (2014) §3.11 Arrival Cost —— P0 为订单进入市场时点
    的市场价格。取首笔成交前最近 10s bar 的 close 作为到达价。

    边界处理:
    - 首笔成交在开盘前（无更早 bar）→ 取当日首个 bar 的 close
    - 无 BDIB 数据 / 无成交时间 → None
    """
    if all_bars is None or all_bars.empty or first_fill_time is None:
        return None
    prior = all_bars[all_bars["mkt_timestamp"] < first_fill_time]
    if not prior.empty:
        last = prior.sort_values("mkt_timestamp").iloc[-1]
        return float(last["close"]) if pd.notna(last["close"]) else None
    # 首笔成交在开盘前或正好等于首 bar 时间：取当日首 bar close 作为到达参考价
    first = all_bars.sort_values("mkt_timestamp").iloc[0]
    return float(first["close"]) if pd.notna(first["close"]) else None


def _compute_close_price(
    daily_summary_df: Optional[pd.DataFrame],
    equ_ticker: Optional[str],
    date_str: str,
    all_bars: Optional[pd.DataFrame] = None,
) -> Optional[float]:
    """收盘价 Pn：bdib_daily_summary.daily_close。

    理论依据: Kissell (2014) §3.13 Benchmark PnL —— 收盘价基准用于
    端到端跟踪误差评估。

    数据源优先级:
    1. bdib_daily_summary.daily_close（Bloomberg PX_LAST，权威值）
    2. 回退：raw_bdib 当日最后一个 bar 的 close（当 S7 未跑时，
       用日内收盘 bar 近似，保证 p_close 覆盖率不依赖 Bloomberg 补跑）
    """
    if equ_ticker:
        if daily_summary_df is not None and not daily_summary_df.empty:
            # 兼容 trade_date 的 YYYYMMDD / YYYY-MM-DD 两种格式
            match = daily_summary_df[
                (daily_summary_df["equ_ticker"] == equ_ticker)
                & (daily_summary_df["trade_date"].astype(str).str.replace("-", "", regex=False) == date_str)
            ]
            if not match.empty:
                val = match.iloc[0].get("daily_close")
                if val is not None and not pd.isna(val):
                    return float(val)

    # 回退：取当日最后一个 bar 的 close（收盘集合竞价后的最后价格）
    if all_bars is not None and not all_bars.empty:
        last = all_bars.sort_values("mkt_timestamp").iloc[-1]
        if pd.notna(last.get("close")):
            return float(last["close"])
    return None


def _compute_decision_price(
    all_bars: Optional[pd.DataFrame],
    order_create: Optional[Any],
    exchange_code: Optional[str],
) -> Optional[float]:
    """决策价 Pd：订单创建时间（NyOrderCreateAsOfDateTime）之前最近 bar close。

    理论依据: Perold (1988) "The Implementation Shortfall: Paper versus Reality"
    —— Pd 为投资决策时点的市场价格，用于 Wagner IS 的延迟成本分量
    （Kissell 2014 §3.7）。

    边界处理:
    - 订单在盘前创建（无更早 bar）→ 取当日首个 bar 的 open（开盘参考价）
    - 无 NyOrderCreateAsOfDateTime / 转换失败 → None
    """
    if all_bars is None or all_bars.empty or order_create is None:
        return None
    if isinstance(order_create, str) and not order_create.strip():
        return None
    try:
        # 与 _get_fill_time 保持一致：用 Series + batch_convert_ny_to_local 处理字符串时间戳
        s = pd.Series([order_create])
        local_dts = batch_convert_ny_to_local(s, pd.Series([exchange_code], index=s.index))
        local_dt = local_dts.iloc[0]
    except (ValueError, TypeError, KeyError):
        return None
    if local_dt is None or pd.isna(local_dt):
        return None
    local_time = local_dt.strftime(Config.TIME_FORMAT)
    prior = all_bars[all_bars["mkt_timestamp"] < local_time]
    if not prior.empty:
        last = prior.sort_values("mkt_timestamp").iloc[-1]
        return float(last["close"]) if pd.notna(last["close"]) else None
    # 盘前订单：取当日首 bar 的 open 作为决策参考价
    first = all_bars.sort_values("mkt_timestamp").iloc[0]
    return float(first["open"]) if pd.notna(first["open"]) else None


def _compute_risk_metrics(
    processed_fills_df: pd.DataFrame,
    order_id: str,
    route_id: str,
    date_str: str,
) -> dict[str, Optional[float]]:
    """成本风险维度：从成交时间序列计算成本标准差 / P95 / CVaR。

    理论依据: Bertsimas & Lo (1998) "Optimal Control of Execution Costs";
    Almgren & Chriss (1999) "Optimal Execution of Portfolio Transactions"
    —— 成本-风险权衡需报告成本分布的离散程度与尾部风险。

    实现: 用 processed_fills 中该路由每笔成交的 FillPrice 偏离 p_avg 的
    bps 序列近似 cum_slippage 分布（pipeline 未直接落库逐笔 slippage 时）。
    """
    result: dict[str, Optional[float]] = {
        "cost_stddev": None, "cost_p95": None, "cost_cvar": None,
    }
    fills = processed_fills_df[
        (processed_fills_df["OrderId"] == order_id)
        & (processed_fills_df["RouteId"] == route_id)
        & (processed_fills_df["order_as_of_date"] == date_str)
    ]
    if fills.empty or "FillPrice" not in fills.columns:
        return result
    prices = pd.to_numeric(fills["FillPrice"], errors="coerce").dropna()
    shares = pd.to_numeric(fills["FillShares"], errors="coerce")
    mask = prices.index.isin(shares[shares > 0].index)
    prices = prices[mask]
    if prices.empty or len(prices) < 2:
        return result
    p_avg = float((prices * shares.loc[prices.index]).sum() / shares.loc[prices.index].sum())
    if p_avg <= 0:
        return result
    bps = (prices / p_avg - 1.0) * 10000.0
    result["cost_stddev"] = float(bps.std(ddof=1)) if len(bps) >= 2 else None
    result["cost_p95"] = float(np.percentile(bps, 95))
    tail = bps[bps > result["cost_p95"]]
    result["cost_cvar"] = float(tail.mean()) if not tail.empty else result["cost_p95"]
    return result


def _compute_order_duration(
    fills: pd.DataFrame,
    total_fill: float,
    exchange_code: Optional[str],
) -> tuple[Optional[float], Optional[float]]:
    """订单历时（秒）与执行速率（股/分钟）。

    历时 = 首笔成交 → 末笔成交（本地交易所时间）。
    执行速率 = 总成交股数 / (历时/60)。
    """
    if fills.empty:
        return None, None
    times = []
    if "DateTimeOfFill" in fills.columns and not fills["DateTimeOfFill"].isna().all():
        try:
            local_dts = batch_convert_ny_to_local(
                fills["DateTimeOfFill"],
                pd.Series([exchange_code] * len(fills), index=fills.index),
            )
            times = local_dts.dt.strftime(Config.TIME_FORMAT).dropna().tolist()
        except ValueError:
            times = []
    if len(times) < 2:
        return None, None
    try:
        t_first = pd.to_datetime(min(times), format=Config.TIME_FORMAT)
        t_last = pd.to_datetime(max(times), format=Config.TIME_FORMAT)
        duration_sec = float((t_last - t_first).total_seconds())
    except (ValueError, TypeError):
        return None, None
    if duration_sec <= 0 or total_fill is None or total_fill <= 0:
        return duration_sec if duration_sec > 0 else None, None
    rate = total_fill / (duration_sec / 60.0)
    return duration_sec, rate


def _compute_recovery_price(
    all_bars: Optional[pd.DataFrame],
    last_fill_time: Optional[str],
    recovery_minutes: int,
) -> tuple[Optional[float], bool]:
    """恢复价格：末笔成交 + N 分钟后的最近 bar close。

    返回 (recovery_price, truncated)。truncated=True 表示末笔成交 + N 分钟
    已超出当日最后 bar。越界时本函数返回当日最后 bar close 仅作占位，
    调用方（_compute_impact_metrics）会改用次日收盘价作为跨日恢复价格。
    """
    if all_bars is None or all_bars.empty or last_fill_time is None:
        return None, False
    try:
        base = pd.to_datetime(last_fill_time, format=Config.TIME_FORMAT)
        target = base + pd.Timedelta(minutes=recovery_minutes)
    except (ValueError, TypeError):
        return None, False
    target_str = target.strftime(Config.TIME_FORMAT)
    after = all_bars[all_bars["mkt_timestamp"] >= target_str]
    if not after.empty:
        first = after.sort_values("mkt_timestamp").iloc[0]
        return (float(first["close"]) if pd.notna(first["close"]) else None), False
    # 越界：取当日最后 bar close，标记截断
    last = all_bars.sort_values("mkt_timestamp").iloc[-1]
    return (float(last["close"]) if pd.notna(last["close"]) else None), True


def _get_next_day_close(
    daily_summary_df: Optional[pd.DataFrame],
    equ_ticker: Optional[str],
    date_str: str,
) -> Optional[float]:
    """次日收盘价（跨日恢复窗口）：下一交易日的 daily_close。

    理论依据: 论文 B2.2 市场冲击 —— 用次日收盘价区分暂时/永久冲击
    （Almgren & Chriss 1999; Obizhaeva & Wang 2013）。跨日数据通过
    bdib_daily_summary 的逐日 daily_close 获取。
    """
    if daily_summary_df is None or daily_summary_df.empty or not equ_ticker:
        return None
    ticker_df = daily_summary_df[daily_summary_df["equ_ticker"] == equ_ticker].copy()
    if ticker_df.empty:
        return None
    ticker_df["trade_date_compact"] = (
        ticker_df["trade_date"].astype(str).str.replace("-", "", regex=False)
    )
    target_dates = ticker_df["trade_date_compact"].sort_values().tolist()
    if date_str not in target_dates:
        return None
    idx = target_dates.index(date_str)
    if idx + 1 >= len(target_dates):
        return None  # 无下一交易日数据
    next_row = ticker_df[ticker_df["trade_date_compact"] == target_dates[idx + 1]]
    if next_row.empty:
        return None
    val = next_row.iloc[0].get("daily_close")
    if pd.isna(val):
        return None
    return float(val)


def _compute_impact_metrics(
    all_bars: Optional[pd.DataFrame],
    daily_summary_df: Optional[pd.DataFrame],
    p_avg: Optional[float],
    p_arrival: Optional[float],
    last_fill_time: Optional[str],
    side_sign: int,
    date_str: str,
    equ_ticker: Optional[str],
) -> dict[str, Any]:
    """暂时/永久市场冲击分解（4 恢复窗口：5/10/30min + 次日收盘）。

    理论依据:
    - 暂时冲击: Obizhaeva & Wang (2013) "Optimal Trading Strategy and
      Supply/Demand Dynamics" —— 流动性消耗导致的暂时价格偏离，随时间恢复
    - 永久冲击: Gatheral (2010) "No-Dynamic-Arbitrage and Market Impact"
      —— 信息含量导致的永久价格移动

    4 恢复窗口:
    - 暂时冲击: 执行结束后 5/10/30min 恢复价格 vs 成交均价；
      末笔成交 + N min 越出当日最后 bar 时改用次日收盘价
      （跨日/隔夜恢复，recovery_truncated=1 标记）
    - 永久冲击: 次日收盘价 vs 到达价（跨日区分暂时/永久，决策#4）
    """
    result: dict[str, Any] = {
        "temp_impact_5min_bps": None,
        "temp_impact_10min_bps": None,
        "temp_impact_30min_bps": None,
        "perm_impact_bps": None,
        "recovery_truncated": 0,
    }
    if p_avg is None or p_avg == 0 or side_sign == 0:
        return result

    # 次日收盘（跨日恢复价格）：窗口越界时替代当日最后 bar 近似
    next_close = _get_next_day_close(daily_summary_df, equ_ticker, date_str)

    # 暂时冲击：执行结束后 5/10/30min 恢复价格 vs 成交均价。
    # 订单成交时刻是客观事实，恢复窗口定义不变；仅当末笔成交 + N min
    # 越出当日最后 bar 时，恢复价格改用次日收盘价（隔夜恢复，
    # Almgren & Chriss 1999 / Obizhaeva & Wang 2013），并标记 truncated。
    truncated = False
    for minutes, col in ((5, "temp_impact_5min_bps"), (10, "temp_impact_10min_bps"), (30, "temp_impact_30min_bps")):
        recovery, is_trunc = _compute_recovery_price(all_bars, last_fill_time, minutes)
        if is_trunc:
            truncated = True
            recovery = next_close
        if recovery is not None and recovery != 0:
            result[col] = _pnl_in_bps(recovery, p_avg, side_sign)
    result["recovery_truncated"] = 1 if truncated else 0

    # 永久冲击：次日收盘价 vs 到达价（跨日恢复窗口，决策#4）
    if next_close is not None and p_arrival is not None and p_arrival != 0:
        result["perm_impact_bps"] = (next_close / p_arrival - 1.0) * side_sign * 10000.0

    return result
