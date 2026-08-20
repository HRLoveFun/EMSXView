"""H2 回归测试: Parquet 合并写防护 (2026-08-14)。

背景:
    S5 按 50 ticker 分块循环写同一日期 Parquet 文件, 旧实现 write_batch
    直接 to_parquet 覆盖, 后写覆盖前写 → 每个日期仅存最后一个 chunk。

校验:
    1. 同日期分块写入合并而非覆盖
    2. 重复 K 线去重 (keep=last), 行数不增
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from DataPipeline.storage.market_store import MarketStoreWriter


def _make_chunk(ticker: str, date_str: str) -> pd.DataFrame:
    """构造单 ticker 的 2 根 10 秒 K 线。"""
    return pd.DataFrame({
        "equ_ticker": [ticker, ticker],
        "order_as_of_date": [date_str, date_str],
        "mkt_timestamp": ["09:30:00", "09:30:10"],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.5, 101.5],
        "volume": [1000, 2000], "num_trds": [10, 20],
        "value": [100500.0, 203000.0],
    })


def test_chunked_write_merges_instead_of_overwrites():
    """同日期分块写入: 第二块不得覆盖第一块数据。"""
    with tempfile.TemporaryDirectory() as tmp:
        writer = MarketStoreWriter(Path(tmp))

        chunk_a = _make_chunk("AAA US", "20250701")
        chunk_b = _make_chunk("BBB US", "20250701")

        assert writer.write_batch(chunk_a) == 2
        writer.write_batch(chunk_b)

        files = list(Path(tmp).rglob("*.parquet"))
        assert len(files) == 1, f"应只有 1 个日期文件, 实际 {len(files)}"

        merged = pd.read_parquet(files[0])
        assert set(merged["equ_ticker"]) == {"AAA US", "BBB US"}
        assert len(merged) == 4, f"合并后行数错误: {len(merged)}"


def test_duplicate_bars_deduplicated_keep_last():
    """重复写入同根 K 线: 去重后行数不增。"""
    with tempfile.TemporaryDirectory() as tmp:
        writer = MarketStoreWriter(Path(tmp))

        chunk = _make_chunk("AAA US", "20250701")
        writer.write_batch(chunk)
        writer.write_batch(chunk)  # 重复块

        files = list(Path(tmp).rglob("*.parquet"))
        merged = pd.read_parquet(files[0])
        assert len(merged) == 2, f"去重后应保留 2 行, 实际 {len(merged)}"
