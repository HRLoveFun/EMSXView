"""fill_bdib_integrated 单元测试。

覆盖集成阶段 USD 汇率兜底（usd_mask 008 修复）：
- 仅规范化后等于 "USD Curncy" 的币种在 fx_rate 缺失时置 1.0
- "USDKRW Curncy" 等复合币种不再被 str.contains("USD") 误判为 USD
- NULL/未知币种保持 fx_rate 缺失（不置 1.0）
避免 KRW 本币金额被当作 USD 造成数量级虚高（KS 市场 16.74B 根因之一）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from DataPipeline.processing.fill_bdib_integrated import integrate_fills_bdib_for_date

_DATE = "20260820"


def _make_agg_df() -> pd.DataFrame:
    """三条聚合成交：KS(KRW) + US(USD) + HK(ccy_ticker 缺失)。"""
    return pd.DataFrame([
        {
            "OrderId": "O1", "RouteId": "R1", "order_as_of_date": _DATE,
            "mkt_timestamp": "09:30:00", "equ_ticker": "005490 KS Equity",
            "ccy_ticker": "USDKRW Curncy", "FillShares": 100.0,
            "FillPrice": 50000.0, "Side": "BUY", "Exchange": "KS",
        },
        {
            "OrderId": "O2", "RouteId": "R2", "order_as_of_date": _DATE,
            "mkt_timestamp": "09:30:00", "equ_ticker": "AAPL US Equity",
            "ccy_ticker": "USD Curncy", "FillShares": 100.0,
            "FillPrice": 150.0, "Side": "BUY", "Exchange": "US",
        },
        {
            "OrderId": "O3", "RouteId": "R3", "order_as_of_date": _DATE,
            "mkt_timestamp": "09:30:00", "equ_ticker": "1 HK Equity",
            "ccy_ticker": None, "FillShares": 100.0,
            "FillPrice": 10.0, "Side": "BUY", "Exchange": "HK",
        },
    ])


def _make_bdib_df() -> pd.DataFrame:
    """最小 BDIB bars（三只 ticker 各一行），列对齐集成 merge 键。"""
    rows = []
    for ticker in ("005490 KS Equity", "AAPL US Equity", "1 HK Equity"):
        rows.append({
            "equ_ticker": ticker, "order_as_of_date": _DATE,
            "mkt_timestamp": "09:30:00", "open": 10.0, "close": 10.0,
            "volume": 1000.0, "value": 10000.0, "vwap": 10.0,
        })
    return pd.DataFrame(rows)


class TestUsdMaskFxFallback:
    def test_usd_gets_one_only_for_exact_usd_ccy(self) -> None:
        """fx_rates=None 时：USD Curncy → 1.0；USDKRW/NULL → 保持缺失。"""
        result = integrate_fills_bdib_for_date(
            _make_agg_df(), _DATE, bdib_data=_make_bdib_df(), fx_rates=None,
        )
        fx_by_route = dict(zip(result["RouteId"], result["fx_rate"]))
        # USD Curncy：USD 兜底 1.0
        assert fx_by_route["R2"] == 1.0
        # USDKRW Curncy：复合币种不再误判为 USD，保持 NaN
        assert np.isnan(fx_by_route["R1"])
        # NULL ccy_ticker：未知币种保持 NaN（不置 1.0，避免掩盖汇率缺失）
        assert np.isnan(fx_by_route["R3"])

    def test_usd_ccy_lowercase_still_matches(self) -> None:
        """小写 "usd curncy" 经规范化后仍置 1.0。"""
        agg = _make_agg_df()
        agg.loc[agg["RouteId"] == "R2", "ccy_ticker"] = "usd curncy"
        result = integrate_fills_bdib_for_date(
            agg, _DATE, bdib_data=_make_bdib_df(), fx_rates=None,
        )
        fx_by_route = dict(zip(result["RouteId"], result["fx_rate"]))
        assert fx_by_route["R2"] == 1.0
