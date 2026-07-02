"""add_equity_ticker 单元测试 (S1 数据修复 v2)

覆盖三个用例：
1. 空 Exchange → equ_ticker 为 None
2. 空 Ticker → equ_ticker 为 None
3. EUR 缓存/查询都未命中 → equ_ticker 为 None
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 添加项目根到 sys.path 以便 import
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from DataPipeline.processing.fill_processor import add_equity_ticker


class TestAddEquityTicker:
    def test_add_equity_ticker_empty_exchange(self):
        """当 Exchange 为空时，equ_ticker 应为 None（不是 'Ticker  Equity' 双空格）。"""
        df = pd.DataFrame({
            "Ticker": ["AAPL"],
            "Exchange": [""],  # 空字符串
            "Currency": ["USD"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] is None or pd.isna(result["equ_ticker"].iloc[0]), (
            f"空 Exchange 应输出 None，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_none_exchange(self):
        """当 Exchange 为 None 时，equ_ticker 应为 None。"""
        df = pd.DataFrame({
            "Ticker": ["AAPL"],
            "Exchange": [None],
            "Currency": ["USD"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] is None or pd.isna(result["equ_ticker"].iloc[0]), (
            f"None Exchange 应输出 None，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_nan_exchange(self):
        """当 Exchange 为 NaN 时，equ_ticker 应为 None。"""
        df = pd.DataFrame({
            "Ticker": ["AAPL"],
            "Exchange": [np.nan],
            "Currency": ["USD"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] is None or pd.isna(result["equ_ticker"].iloc[0]), (
            f"NaN Exchange 应输出 None，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_empty_ticker(self):
        """当 Ticker 为空时，equ_ticker 应为 None（不是 ' Equity'）。"""
        df = pd.DataFrame({
            "Ticker": [""],
            "Exchange": ["US"],
            "Currency": ["USD"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] is None or pd.isna(result["equ_ticker"].iloc[0]), (
            f"空 Ticker 应输出 None，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_normal(self):
        """正常字段：equ_ticker 应为 'AAPL US Equity'。"""
        df = pd.DataFrame({
            "Ticker": ["AAPL"],
            "Exchange": ["US"],
            "Currency": ["USD"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] == "AAPL US Equity", (
            f"正常拼接应得到 'AAPL US Equity'，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_krw_zfill(self):
        """KRW 股票应 zfill(6)。"""
        df = pd.DataFrame({
            "Ticker": ["1234"],
            "Exchange": ["KS"],
            "Currency": ["KRW"],
        })
        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] == "001234 KS Equity", (
            f"KRW zfill 后应为 '001234 KS Equity'，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_eur_cache_miss(self, monkeypatch):
        """EUR 缓存/查询都未命中 → equ_ticker 应保留原始拼接值（fallback）。"""
        df = pd.DataFrame({
            "Ticker": ["BMW"],
            "Exchange": ["GR"],
            "Currency": ["EUR"],
        })

        # Mock 缓存加载返回空 + BBG 查询返回空
        from DataPipeline.processing import fill_processor

        monkeypatch.setattr(fill_processor, "_load_composite_cache", lambda: {})
        monkeypatch.setattr(fill_processor, "_fetch_composite_tickers", lambda tickers: {})
        monkeypatch.setattr(fill_processor, "_save_composite_cache", lambda m: None)

        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] == "BMW GR Equity", (
            f"EUR 缓存/查询都未命中应保留原始拼接值 'BMW GR Equity'，实际: {result['equ_ticker'].iloc[0]!r}"
        )

    def test_add_equity_ticker_eur_partial_cache_hit(self, monkeypatch):
        """EUR 部分缓存命中 → 命中行映射为 composite，未命中行保留原始拼接值。"""
        df = pd.DataFrame({
            "Ticker": ["BMW", "VOW3", "SAN"],
            "Exchange": ["GR", "GR", "FP"],
            "Currency": ["EUR", "EUR", "EUR"],
        })

        from DataPipeline.processing import fill_processor

        # Mock: BMW GR Equity 命中缓存，VOW3/SAN 未命中且 BBG 无返回
        monkeypatch.setattr(
            fill_processor,
            "_load_composite_cache",
            lambda: {"BMW GR Equity": "BMW EU Equity"},
        )
        monkeypatch.setattr(fill_processor, "_fetch_composite_tickers", lambda tickers: {})
        monkeypatch.setattr(fill_processor, "_save_composite_cache", lambda m: None)

        result = add_equity_ticker(df)
        assert result["equ_ticker"].iloc[0] == "BMW EU Equity", (
            f"命中缓存应映射为 'BMW EU Equity'，实际: {result['equ_ticker'].iloc[0]!r}"
        )
        assert result["equ_ticker"].iloc[1] == "VOW3 GR Equity", (
            f"未命中应保留原始拼接值 'VOW3 GR Equity'，实际: {result['equ_ticker'].iloc[1]!r}"
        )
        assert result["equ_ticker"].iloc[2] == "SAN FP Equity", (
            f"未命中应保留原始拼接值 'SAN FP Equity'，实际: {result['equ_ticker'].iloc[2]!r}"
        )

    def test_add_equity_ticker_eur_empty_composite_map(self, monkeypatch):
        """EUR 缓存为空且 BBG 查询失败 → 全部保留原始拼接值（不设为 NaN）。"""
        df = pd.DataFrame({
            "Ticker": ["BMW", "VOW3", "SAN"],
            "Exchange": ["GR", "GR", "FP"],
            "Currency": ["EUR", "EUR", "EUR"],
        })

        from DataPipeline.processing import fill_processor

        # Mock: 缓存为空 + BBG 返回空 → composite_map 为空，走 else 分支
        monkeypatch.setattr(fill_processor, "_load_composite_cache", lambda: {})
        monkeypatch.setattr(fill_processor, "_fetch_composite_tickers", lambda tickers: {})
        monkeypatch.setattr(fill_processor, "_save_composite_cache", lambda m: None)

        result = add_equity_ticker(df)
        expected = ["BMW GR Equity", "VOW3 GR Equity", "SAN FP Equity"]
        for i, exp in enumerate(expected):
            assert result["equ_ticker"].iloc[i] == exp, (
                f"第 {i} 行应保留原始拼接值 {exp!r}，实际: {result['equ_ticker'].iloc[i]!r}"
            )
