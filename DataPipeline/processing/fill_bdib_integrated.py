"""
Fill-BDIB Integration — merge processed fills with intraday bar data.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill_bdib_integrated.py.
Merges 10-second aggregated fills with BDIB market data, adds FX rates and
daily equity metrics, and computes TCA-related derived metrics.

All functions use EMSX column names (OrderId, FillShares, FillPrice, etc.).

"""

from __future__ import annotations

import gc
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from DataPipeline.acquisition.bdib_fetcher import fetch_bdib_for_ticker_date
from DataPipeline.config import Config

logger = logging.getLogger(__name__)

def integrate_fills_bdib_for_date(
    agg_fills_df: pd.DataFrame,
    date_str: str,
    bdib_data: Optional[pd.DataFrame] = None,
    fx_rates: Optional[pd.DataFrame] = None,
    daily_equity_data: Optional[Dict[str, pd.DataFrame]] = None,
    ticker_exchange_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Integrate aggregated fills with BDIB market data for a single date.

    Steps:
        A. Merge fills with BDIB on (equ_ticker, order_as_of_date, mkt_timestamp)
        B. Add FX rates
        C. Add daily equity metrics (chg_pct_1d, bid_ask_spread_%)
        D. Rename columns for TCA output
        E. Compute derived metrics (fill_value, cum_*, slippage, etc.)

    Args:
        agg_fills_df: 10-second aggregated fills for this date
        date_str: YYYYMMDD date string
        bdib_data: Pre-fetched BDIB data (or None to fetch on demand)
        fx_rates: FX rates DataFrame (long format: ccy_ticker, Order As of Date, fx_rate)
        daily_equity_data: Dict with keys 'chg_pct_1d', 'bid_ask_spread' → DataFrames
        ticker_exchange_map: equ_ticker -> Exchange mapping from ticker_repository

    Returns:
        Integrated DataFrame with all TCA metrics
    """
    if agg_fills_df.empty:
        return pd.DataFrame()

    df_fills = agg_fills_df.copy()

    # Ensure date column consistency
    if "order_as_of_date" in df_fills.columns:
        df_fills["order_as_of_date"] = df_fills["order_as_of_date"].astype(str)
    else:
        df_fills["order_as_of_date"] = date_str

    # ── A. Fetch and merge BDIB data ──────────────────────────────────────

    if bdib_data is None:
        # Fetch on demand for all tickers in this date's fills
        tickers = df_fills["equ_ticker"].dropna().unique().tolist() if "equ_ticker" in df_fills.columns else []
        exchange_map = ticker_exchange_map or {}
        bdib_list = []
        for ticker in tickers:
            df_bdib = fetch_bdib_for_ticker_date(
                ticker,
                date_str,
                exchange=exchange_map.get(str(ticker)),
            )
            if df_bdib is not None and not df_bdib.empty:
                bdib_list.append(df_bdib)

        bdib_data = pd.concat(bdib_list, ignore_index=True) if bdib_list else pd.DataFrame()

    if not bdib_data.empty:
        # Determine merge keys
        merge_keys = ["equ_ticker", "mkt_timestamp"]
        if "order_as_of_date" in bdib_data.columns:
            merge_keys.append("order_as_of_date")
            bdib_data["order_as_of_date"] = bdib_data["order_as_of_date"].astype(str)

        valid_keys = [k for k in merge_keys if k in df_fills.columns and k in bdib_data.columns]

        if valid_keys:
            for k in valid_keys:
                df_fills[k] = df_fills[k].astype(str)
                bdib_data[k] = bdib_data[k].astype(str)

            df_merged = pd.merge(
                df_fills, bdib_data, on=valid_keys, how="left", suffixes=("", "_bdib")
            )
        else:
            df_merged = df_fills
    else:
        df_merged = df_fills
        # Add empty BDIB columns
        for col in ["open", "high", "low", "close", "volume", "num_trds", "value", "vwap", "fluctuation", "log_chg_pct_10s"]:
            df_merged[col] = np.nan

    # ── B. Add FX rates ───────────────────────────────────────────────────

    if fx_rates is not None and not fx_rates.empty:
        fx_for_date = fx_rates[fx_rates["order_as_of_date"] == date_str].copy()
        if not fx_for_date.empty and "ccy_ticker" in df_merged.columns:
            df_merged = pd.merge(
                df_merged,
                fx_for_date[["order_as_of_date", "ccy_ticker", "fx_rate"]],
                on=["order_as_of_date", "ccy_ticker"],
                how="left",
            )
        else:
            df_merged["fx_rate"] = np.nan
    else:
        df_merged["fx_rate"] = np.nan

    # USD/USD → fx_rate = 1.0。仅规范化后等于 "USD Curncy" 的币种视为 USD；
    # NULL/未知币种不置 1.0（保持 NULL 交由下游按汇率缺失处理），避免
    # "USDKRW Curncy" 等复合币种因 str.contains("USD") 误匹配被强制置 1.0，
    # 导致 KRW 本币金额被当作 USD 造成数量级虚高（KS 市场 16.74B 根因之一）。
    if "ccy_ticker" in df_merged.columns:
        usd_mask = (
            df_merged["ccy_ticker"].astype(str).str.upper().str.strip()
            == "USD CURNCY"
        )
        df_merged.loc[usd_mask & df_merged["fx_rate"].isna(), "fx_rate"] = 1.0

    # ── C. Add daily equity metrics ───────────────────────────────────────

    if daily_equity_data:
        for field_name, field_df in daily_equity_data.items():
            if field_df is None or field_df.empty:
                df_merged[field_name] = np.nan
                continue

            field_df = field_df.copy()
            if "order_as_of_date" in field_df.columns:
                field_df["order_as_of_date"] = field_df["order_as_of_date"].astype(str)
                daily_for_date = field_df[field_df["order_as_of_date"] == date_str]

                if not daily_for_date.empty and "equ_ticker" in df_merged.columns:
                    # If wide format, melt to long
                    if "equ_ticker" not in daily_for_date.columns:
                        equity_cols = [c for c in daily_for_date.columns if c != "order_as_of_date"]
                        daily_for_date = daily_for_date.melt(
                            id_vars=["order_as_of_date"],
                            value_vars=equity_cols,
                            var_name="equ_ticker",
                            value_name=field_name,
                        )

                    df_merged = pd.merge(
                        df_merged,
                        daily_for_date[["order_as_of_date", "equ_ticker", field_name]],
                        on=["order_as_of_date", "equ_ticker"],
                        how="left",
                    )
                else:
                    df_merged[field_name] = np.nan
            else:
                df_merged[field_name] = np.nan
    else:
        df_merged["chg_pct_1d"] = np.nan
        df_merged["bid_ask_spread_%"] = np.nan

    # ── D. Rename columns for TCA output ──────────────────────────────────

    rename_map = {
        "FillShares": "fill_volume",
        "FillPrice": "fill_px",
    }
    existing_renames = {k: v for k, v in rename_map.items() if k in df_merged.columns}
    df_merged.rename(columns=existing_renames, inplace=True)

    # ── E. Compute derived metrics ────────────────────────────────────────

    _compute_derived_metrics(df_merged)

    # Filter out rows with zero fill volume
    if "fill_volume" in df_merged.columns:
        df_merged["fill_volume"] = pd.to_numeric(df_merged["fill_volume"], errors="coerce")
        df_merged = df_merged[df_merged["fill_volume"] > 0].copy()

    logger.info(f"Integrated fills+BDIB for {date_str}: {len(df_merged)} rows")
    return df_merged

def _compute_derived_metrics(df: pd.DataFrame) -> None:
    """计算 TCA 衍生指标 (in-place, 按 OrderId 分组)。

    v4.0-p1 修复:
      - p1a: 参与率使用累计市场成交量 (cum_market_volume) 替代瞬时成交量
      - p1b: 预计算累计市场指标 (_cum_market_volume, _cum_market_value)
      - p1c: 新增 9 个累积 TCA 列计算 (cum_vwap, cum_fill_vwap, cum_slippage_bps,
        cum_slippage_usd, cum_volume_pct, cum_tracking_error, cum_info_ratio,
        cum_interval_volatility, standard_cum_interval_volatility)
      - 安全除法: 所有分母零值替换为 NaN, 避免 inf/-inf
    """
    # ── 1. 基础计算: fill_value, side_sign ──
    if "fill_volume" in df.columns and "fill_px" in df.columns:
        df["fill_volume"] = pd.to_numeric(df["fill_volume"], errors="coerce")
        df["fill_px"] = pd.to_numeric(df["fill_px"], errors="coerce")
        df["fill_value"] = df["fill_volume"] * df["fill_px"]
    else:
        df["fill_value"] = np.nan

    if "Side" in df.columns:
        df["side_sign"] = np.where(
            df["Side"].astype(str).str.upper().str[0] == "S", -1, 1
        )
    else:
        df["side_sign"] = 1

    # ── 2. 中间累计计算 ──
    if "fill_value" in df.columns and "side_sign" in df.columns:
        df["signed_fill_value"] = df["fill_value"] * df["side_sign"]

    if "signed_fill_value" in df.columns and "OrderId" in df.columns:
        df["cum_fill_value"] = df.groupby("OrderId")["signed_fill_value"].cumsum()

    if "fill_volume" in df.columns and "OrderId" in df.columns:
        df["signed_fill_volume"] = df["fill_volume"] * df["side_sign"]
        df["cum_fill_volume"] = df.groupby("OrderId")["fill_volume"].cumsum()
        # 累计成交金额 (无符号, 用于 fill VWAP)
        if "fill_value" in df.columns:
            df["_cum_fill_value_unsigned"] = df.groupby("OrderId")["fill_value"].cumsum()

    # ── 3. 累计市场指标 (Phase 1B) ──
    # 按 OrderId 分组对 BDIB 成交量/成交额做累计求和
    if all(c in df.columns for c in ["volume", "OrderId"]):
        df["_cum_market_volume"] = df.groupby("OrderId")["volume"].cumsum()
    if all(c in df.columns for c in ["value", "OrderId"]):
        df["_cum_market_value"] = df.groupby("OrderId")["value"].cumsum()

    # ── 4. 修正参与率: 使用累计市场成交量 (Phase 1C) ──
    if "_cum_market_volume" in df.columns and "cum_fill_volume" in df.columns:
        df["participation_rate"] = np.where(
            df["_cum_market_volume"] > 0,
            df["cum_fill_volume"] / df["_cum_market_volume"] * 100,
            np.nan,
        )

    # ── 5. VWAP slippage (安全除法) ──
    if "fill_px" in df.columns and "vwap" in df.columns and "side_sign" in df.columns:
        benchmark = df["vwap"].ffill()
        safe_denom = benchmark.replace(0, np.nan)
        raw_slippage = (df["fill_px"] - benchmark) / safe_denom * 10000
        df["vwap_slippage_bps"] = raw_slippage * df["side_sign"]

        if "OrderId" in df.columns:
            first_vwap = df.groupby("OrderId")["vwap"].transform("first")
            safe_first = first_vwap.replace(0, np.nan)
            arrival_slippage = (df["fill_px"] - first_vwap) / safe_first * 10000
            df["arrival_slippage_bps"] = arrival_slippage * df["side_sign"]

    if "fill_px" in df.columns and "vwap" in df.columns:
        safe_vwap = df["vwap"].replace(0, np.nan)
        df["px_diff_bps"] = (df["fill_px"] - df["vwap"]) / safe_vwap * 10000

    # ── 6. 新增 9 个累积 TCA 列 (Phase 1C) ──

    # cum_vwap: 累计市场 VWAP = cum_market_value / cum_market_volume
    if "_cum_market_value" in df.columns and "_cum_market_volume" in df.columns:
        df["cum_vwap"] = np.where(
            df["_cum_market_volume"] > 0,
            df["_cum_market_value"] / df["_cum_market_volume"],
            np.nan,
        )

    # cum_fill_vwap: 累计成交 VWAP = cum_fill_value_unsigned / cum_fill_volume
    if "_cum_fill_value_unsigned" in df.columns and "cum_fill_volume" in df.columns:
        df["cum_fill_vwap"] = np.where(
            df["cum_fill_volume"] > 0,
            df["_cum_fill_value_unsigned"] / df["cum_fill_volume"],
            np.nan,
        )

    # cum_slippage_bps: 累计 slippage = (cum_fill_vwap - cum_vwap) / cum_vwap * 10000 * side_sign
    if all(c in df.columns for c in ["cum_fill_vwap", "cum_vwap", "side_sign"]):
        safe_cum_vwap = df["cum_vwap"].replace(0, np.nan)
        df["cum_slippage_bps"] = np.where(
            safe_cum_vwap.notna() & df["cum_fill_vwap"].notna(),
            (df["cum_fill_vwap"] - df["cum_vwap"]) / safe_cum_vwap * 10000 * df["side_sign"],
            np.nan,
        )

    # cum_slippage_usd: 累计 slippage 美元金额
    if "cum_slippage_bps" in df.columns and "cum_fill_value" in df.columns:
        df["cum_slippage_usd"] = np.where(
            df["cum_slippage_bps"].notna(),
            df["cum_slippage_bps"] / 10000 * df["cum_fill_value"].abs(),
            np.nan,
        )

    # cum_volume_pct: 累计成交量占比 (%) = cum_fill_volume / cum_market_volume * 100
    if "cum_fill_volume" in df.columns and "_cum_market_volume" in df.columns:
        df["cum_volume_pct"] = np.where(
            df["_cum_market_volume"] > 0,
            df["cum_fill_volume"] / df["_cum_market_volume"] * 100,
            np.nan,
        )

    # cum_tracking_error: 每订单内 (fill_px - vwap) / vwap 的扩展标准差 (bps)
    if "px_diff_bps" in df.columns and "OrderId" in df.columns:
        df["cum_tracking_error"] = df.groupby("OrderId")["px_diff_bps"].transform(
            lambda x: x.expanding().std()
        )

    # cum_info_ratio: cum_slippage_bps / cum_tracking_error
    if "cum_slippage_bps" in df.columns and "cum_tracking_error" in df.columns:
        safe_te = df["cum_tracking_error"].replace(0, np.nan)
        df["cum_info_ratio"] = np.where(
            safe_te.notna() & df["cum_slippage_bps"].notna(),
            df["cum_slippage_bps"] / safe_te,
            np.nan,
        )

    # cum_interval_volatility: 每 bar 对数收益率的扩展标准差 (bps)
    if "log_chg_pct_10s" in df.columns and "OrderId" in df.columns:
        df["cum_interval_volatility"] = df.groupby("OrderId")["log_chg_pct_10s"].transform(
            lambda x: x.expanding().std()
        )

    # standard_cum_interval_volatility: 除以全局非零均值做标准化
    if "cum_interval_volatility" in df.columns:
        global_mean = df["cum_interval_volatility"].replace(0, np.nan).mean()
        if pd.notna(global_mean) and global_mean > 0:
            df["standard_cum_interval_volatility"] = (
                df["cum_interval_volatility"] / global_mean
            )
        else:
            df["standard_cum_interval_volatility"] = df["cum_interval_volatility"]

    # ── 7. 清理临时列 ──
    for tmp_col in [
        "signed_fill_value", "signed_fill_volume", "_exec_val",
        "_cum_fill_value_unsigned", "_cum_market_volume", "_cum_market_value",
    ]:
        if tmp_col in df.columns:
            df.drop(columns=[tmp_col], inplace=True)

    gc.collect()
