"""fill_aggregator 回归测试：RouteShares/Amount 不再返回 'Mult' 字符串。

背景（2026-08-21）：_unique_or_mult 对 RouteShares 数值列返回 'Mult'，
upsert 到 REAL 列时 float('Mult') 失败，S3 聚合死循环。修复：RouteShares/Amount
改用 sum 聚合，从 unique_cols 移出。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from DataPipeline.processing.fill_aggregator import (
    _unique_or_mult,
    generate_agg_fills_10s,
)


def _make_processed_df() -> pd.DataFrame:
    """构造同一 route 在同一 10s 窗口内有多笔不同股数的场景。"""
    return pd.DataFrame({
        "OrderId": ["O1", "O1", "O1"],
        "RouteId": ["R1", "R1", "R1"],
        "mkt_timestamp": ["10:00:00", "10:00:00", "10:00:00"],
        "FillShares": [100, 200, 50],
        "FillPrice": [10.0, 10.5, 10.2],
        "RouteShares": [1000, 2000, 500],
        "Amount": [50000.0, 100000.0, 25000.0],
        "Ticker": ["AAPL", "AAPL", "AAPL"],
        "Side": ["BUY", "BUY", "BUY"],
        "Exchange": ["US", "US", "US"],
        "order_as_of_date": ["20260805", "20260805", "20260805"],
        "Broker": ["B1", "B1", "B1"],
    })


def _make_route_registry_df() -> pd.DataFrame:
    """构造内联 route_registry（009：单测解耦真实库，READ 不再隐式建库）。

    聚合前置的 S3 列补全需要 Ticker/Side/Currency/ccy_ticker；
    _make_processed_df 缺后两列，不传内联 registry 会触发真实库查询。
    """
    return pd.DataFrame({
        "OrderId": ["O1"],
        "RouteId": ["R1"],
        "equ_ticker": ["AAPL US"],
        "Side": ["BUY"],
        "ccy_ticker": ["USD Curncy"],
        "Exchange": ["US"],
    })


def test_route_shares_is_sum_not_mult():
    """RouteShares 应为 sum 聚合（350），不是 'Mult' 字符串。"""
    df = _make_processed_df()
    result = generate_agg_fills_10s(df, route_registry_df=_make_route_registry_df())
    assert len(result) == 1
    # RouteShares = 1000 + 2000 + 500 = 3500（sum，不是 'Mult'）
    assert result.iloc[0]["RouteShares"] == 3500
    # Amount = 50000 + 100000 + 25000 = 175000（sum，不是 'Mult'）
    assert result.iloc[0]["Amount"] == 175000.0


def test_fill_shares_is_sum():
    """FillShares 仍为 sum 聚合（350）。"""
    df = _make_processed_df()
    result = generate_agg_fills_10s(df, route_registry_df=_make_route_registry_df())
    assert result.iloc[0]["FillShares"] == 350


def test_categorical_still_uses_unique_or_mult():
    """纯分类列（如 Broker）值唯一时返回原值，多值时返回 'Mult'。"""
    s_unique = pd.Series(["B1", "B1", "B1"])
    assert _unique_or_mult(s_unique) == "B1"

    s_mult = pd.Series(["B1", "B2", "B1"])
    assert _unique_or_mult(s_mult) == "Mult"


def test_agg_result_route_shares_is_numeric():
    """聚合后 RouteShares 列类型为数值，可安全 float() 转换。"""
    df = _make_processed_df()
    result = generate_agg_fills_10s(df, route_registry_df=_make_route_registry_df())
    val = result.iloc[0]["RouteShares"]
    # 模拟 _upsert_fixed_schema 的 float() 转换，不应抛异常
    assert float(val) == 3500.0
