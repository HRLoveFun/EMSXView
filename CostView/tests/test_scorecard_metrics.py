"""Scorecard cohort 指标口径回归（2026-11-27 口径修正）。

覆盖：
- avg_fill_pct = Σfill / ΣRouteShares × 100（不再是平均股数）
- avg_volume_pct_adv20 = 逐路由 fill / adv_20d × 100 的简单平均
- avg_daily_volatility = daily_volatility 简单平均（不再用 RPM 代理）
- avg_intraday_volatility 显式为 None，代理量回落 avg_abs_pnl_vwap_continuous_bps
- avg_price_movement_pct = |p_close/p_arrival − 1| × 100 的简单平均
- metric_coverage 逐指标披露 n_used / n_total / pct
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from CostView.src.tca_utils import aggregate_cohorts


def _route(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "OrderId": "O1", "RouteId": "R1", "order_as_of_date": "20260418",
        "Broker": "BROKERA", "algo": "VWAP", "equ_ticker": "AAPL US Equity",
        "Exchange": "US",
        "RouteShares": 1000.0, "fill": 900.0, "par_rate": 0.01,
        "par_rate_continuous": 0.2, "pnl_vwap": 5.0,
        "pnl_vwap_continuous": -100.0, "RPM": 0.3,
        "adv_20d": 10000.0, "daily_volatility": 30.0,
        "p_close": 110.0, "p_arrival": 100.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cohort_metric_formulas_and_coverage() -> None:
    routes = [
        _route(RouteId="R1", fill=500.0, RouteShares=1000.0,
               par_rate_continuous=0.20, adv_20d=10000.0,
               daily_volatility=30.0, pnl_vwap_continuous=-100.0,
               p_close=110.0, p_arrival=100.0, pnl_vwap=5.0),
        _route(RouteId="R2", fill=1000.0, RouteShares=1000.0,
               par_rate_continuous=0.40, adv_20d=20000.0,
               daily_volatility=50.0, pnl_vwap_continuous=200.0,
               p_close=90.0, p_arrival=100.0, pnl_vwap=-15.0),
    ]

    cohort = aggregate_cohorts(routes, "broker", 1)[0]

    # 完成率：Σfill / ΣRouteShares × 100 = 1500/2000 = 75%
    assert cohort.avg_fill_pct == pytest.approx(75.0)
    # ADV20 参与率：两条各 5% → 5%
    assert cohort.avg_volume_pct_adv20 == pytest.approx(5.0)
    # 区间参与率：20% / 40% → 30%
    assert cohort.avg_volume_pct_interval == pytest.approx(30.0)
    # 日波动率：30 / 50 → 40（年化百分数）
    assert cohort.avg_daily_volatility == pytest.approx(40.0)
    # 真实日内波动率不可得；代理量为 |−100|/|200| 的均值 = 150 bps
    assert cohort.avg_intraday_volatility is None
    assert cohort.avg_abs_pnl_vwap_continuous_bps == pytest.approx(150.0)
    # 价格变动：10% / 10% → 10%
    assert cohort.avg_price_movement_pct == pytest.approx(10.0)

    # 覆盖率：所有指标两条路由都可用
    for metric in (
        "pnl_vwap", "fill_pct", "volume_pct_adv20", "volume_pct_interval",
        "daily_volatility", "abs_pnl_vwap_continuous", "price_movement_pct",
    ):
        assert cohort.metric_coverage[metric] == {
            "n_used": 2, "n_total": 2, "pct": 100.0,
        }

    # 完成率 75% 触发 low_fill_rate（旧口径 mean(fill)=750 永不触发）
    assert "low_fill_rate" in cohort.anomaly_flags


def test_cohort_metric_missing_values_disclosed() -> None:
    routes = [
        _route(RouteId="R1"),
        _route(RouteId="R2", adv_20d=None, daily_volatility=None,
               p_close=None, p_arrival=None, pnl_vwap=None,
               par_rate_continuous=None, pnl_vwap_continuous=None),
    ]

    cohort = aggregate_cohorts(routes, "broker", 1)[0]

    assert cohort.metric_coverage["volume_pct_adv20"] == {
        "n_used": 1, "n_total": 2, "pct": 50.0,
    }
    assert cohort.metric_coverage["daily_volatility"] == {
        "n_used": 1, "n_total": 2, "pct": 50.0,
    }
    assert cohort.metric_coverage["price_movement_pct"] == {
        "n_used": 1, "n_total": 2, "pct": 50.0,
    }
    assert cohort.metric_coverage["pnl_vwap"] == {
        "n_used": 1, "n_total": 2, "pct": 50.0,
    }
    # 缺失指标不补 0
    assert cohort.avg_price_movement_pct == pytest.approx(10.0)
