"""fill_aggregator 单元测试。

覆盖 ccy_ticker → Currency 推导（008 修复）：
- "USD Curncy" -> "USD"（本币即美元）
- "USDKRW Curncy" -> "KRW"（取后 3 字符本币，修复此前误取前 3 字符 -> "USD"）
Currency 直接影响 minor_unit 修正与 USD 成交金额换算的汇率兜底判断，
错误推导会与非 USD 币种汇率缺失叠加造成数量级虚高（KS 市场 16.74B 根因之一）。
"""

from __future__ import annotations

import pandas as pd

from DataPipeline.processing.fill_aggregator import generate_agg_fills_10s


def _make_processed_df() -> pd.DataFrame:
    """两条 processed_fills 行：KS(KRW) + US(USD)。"""
    return pd.DataFrame([
        {
            "OrderId": "O1", "RouteId": "R1", "mkt_timestamp": "09:30:00",
            "order_as_of_date": "20260820", "FillShares": 100.0,
            "FillPrice": 50000.0, "RouteShares": 100.0, "Amount": 5000000.0,
        },
        {
            "OrderId": "O2", "RouteId": "R2", "mkt_timestamp": "09:30:00",
            "order_as_of_date": "20260820", "FillShares": 100.0,
            "FillPrice": 150.0, "RouteShares": 100.0, "Amount": 15000.0,
        },
    ])


def _make_registry_df() -> pd.DataFrame:
    """route_registry：KS 行 ccy_ticker=USDKRW Curncy，US 行 USD Curncy。"""
    return pd.DataFrame([
        {
            "OrderId": "O1", "RouteId": "R1", "equ_ticker": "005490 KS Equity",
            "ccy_ticker": "USDKRW Curncy", "Side": "BUY", "Exchange": "KS",
        },
        {
            "OrderId": "O2", "RouteId": "R2", "equ_ticker": "AAPL US Equity",
            "ccy_ticker": "USD Curncy", "Side": "BUY", "Exchange": "US",
        },
    ])


class TestCurrencyExtraction:
    def test_currency_is_local_ccy_not_usd_prefix(self) -> None:
        """"USDKRW Curncy" 推导出 "KRW" 而非 "USD"（008 修复回归）。"""
        result = generate_agg_fills_10s(
            _make_processed_df(), route_registry_df=_make_registry_df(),
        )
        cur_by_route = dict(zip(result["RouteId"], result["Currency"]))
        assert cur_by_route["R1"] == "KRW"
        assert cur_by_route["R2"] == "USD"

    def test_currency_still_works_for_usd(self) -> None:
        """"USD Curncy" 推导出 "USD"（纯美元币种不受影响）。"""
        result = generate_agg_fills_10s(
            _make_processed_df(), route_registry_df=_make_registry_df(),
        )
        assert "USD" in result["Currency"].values
