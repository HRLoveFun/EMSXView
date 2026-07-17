"""tca_route_metrics 单元测试。

覆盖 _compute_all_pwp 与 compute_route_metrics_for_date 的核心路径，
防止 _PWP_RATES 命名等回归问题。
"""

from __future__ import annotations

import pandas as pd
import pytest

from DataPipeline.processing.tca_route_metrics import (
    _compute_all_pwp,
    compute_route_metrics_for_date,
)


def _make_bars(
    times: list[str],
    volumes: list[float],
    prices: list[float],
) -> pd.DataFrame:
    """构造 raw_bdib bars DataFrame。"""
    return pd.DataFrame({
        "equ_ticker": ["AAPL US Equity"] * len(times),
        "order_as_of_date": ["20260421"] * len(times),
        "mkt_timestamp": times,
        "volume": volumes,
        "value": [v * p for v, p in zip(volumes, prices)],
    })


class TestComputeAllPwp:
    """测试 PWP 各档位计算。"""

    def test_hits_all_thresholds_for_buy(self) -> None:
        """当累计成交量足够时，所有 PWP 档位都应命中。"""
        # 成交量 1000，5% 档位需要市场成交量 20000
        bars = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20", "09:30:30", "09:30:40"],
            volumes=[5000.0] * 5,
            prices=[100.0] * 5,
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")

        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is not None
            assert result[col] == pytest.approx(0.0)

    def test_returns_none_when_not_enough_volume(self) -> None:
        """累计成交量不足以达到任何档位阈值时，所有值为 None。"""
        bars = _make_bars(
            times=["09:30:00", "09:30:10"],
            volumes=[100.0, 200.0],
            prices=[100.0, 100.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")

        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is None

    def test_respects_start_time(self) -> None:
        """只统计 start_time 之后的 bars。"""
        bars = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20"],
            volumes=[5000.0, 5000.0, 5000.0],
            prices=[100.0, 100.0, 100.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:15")

        # start_time 之后只有 1 个 bar（5000），无法达到 5% 档位阈值 20000
        assert result["pwp_5"] is None

    def test_sell_side_produces_negative_pnl(self) -> None:
        """Sell 方向：PWP 价格高于成交价时 PnL 为负。"""
        bars = _make_bars(
            times=["09:30:00"],
            volumes=[50000.0],
            prices=[101.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=-1, start_time="09:30:00")

        # pwp=101, p_avg=100, sell side_sign=-1 => (101/100 - 1) * -1 * 10000 = -100 bps
        assert result["pwp_5"] is not None
        assert result["pwp_5"] == pytest.approx(-100.0)

    def test_empty_bars_returns_all_none(self) -> None:
        """空 bars 输入不应抛异常，所有 PWP 值为 None。"""
        result = _compute_all_pwp(pd.DataFrame(), fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")
        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is None


class TestComputeRouteMetricsForDate:
    """测试整日期路由指标计算。"""

    def test_empty_inputs_return_empty_frame(self) -> None:
        """空输入返回空 DataFrame，列顺序与 schema 一致。"""
        result = compute_route_metrics_for_date(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "20260421"
        )
        assert result.empty
        assert list(result.columns) == [
            "OrderId", "RouteId", "order_as_of_date", "Exchange", "Account",
            "equ_ticker", "Currency", "Side", "Amount", "RouteShares",
            "Type", "LimitPrice", "StopPrice", "Broker", "StrategyType",
            "algo", "TraderName",
            "fill_count", "fill", "fill_continuous", "fill_close",
            "par_rate", "par_rate_continuous", "par_rate_close",
            "p_avg", "p_avg_continuous",
            "pnl_vwap", "pnl_vwap_continuous",
            "RPM", "RPM_continuous",
            "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
        ]

    def test_computes_pwp_columns_for_single_route(self) -> None:
        """单路由有 fills 和 bars 时，PWP 列应正常计算。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        processed_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "equ_ticker": ["AAPL US Equity"],
            "FillId": ["F1"],
            "FillShares": [1000.0],
            "FillPrice": [100.0],
            "DateTimeOfFill": ["2026-04-21T09:30:00-04:00"],
            "is_closing_auction": [0],
        })

        raw_bdib = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20", "09:30:30", "09:30:40"],
            volumes=[5000.0] * 5,
            prices=[100.0] * 5,
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["fill_count"] == 1
        assert row["fill"] == pytest.approx(1000.0)
        assert row["p_avg"] == pytest.approx(100.0)
        assert row["par_rate"] == pytest.approx(1000.0 / 5000.0)
        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert row[col] is not None
            assert row[col] == pytest.approx(0.0)

    def test_normalizes_raw_fills_date_format(self) -> None:
        """raw_fills 的 order_as_of_date 为 YYYY-MM-DD 时仍能与 processed_fills 匹配。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["2026-04-21"],  # 与 processed_fills 格式不同
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        processed_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "equ_ticker": ["AAPL US Equity"],
            "FillId": ["F1"],
            "FillShares": [1000.0],
            "FillPrice": [100.0],
            "DateTimeOfFill": ["2026-04-21T09:30:00-04:00"],
            "is_closing_auction": [0],
        })

        raw_bdib = _make_bars(
            times=["09:30:00"],
            volumes=[5000.0],
            prices=[100.0],
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        assert result.iloc[0]["fill"] == pytest.approx(1000.0)


