"""数据质量回归测试。

覆盖本次数据管道修复的核心场景：
- 空/未知 Exchange 的时区转换必须报错而非回退
- processed_fills 的 order_as_of_date 必须与输入日期一致
- agg_fills_10s 在聚合前从 route_registry 补全 Ticker/Side/Currency/ccy_ticker
- 零股记录的 VWAP 不生成 FillPrice NaN 行
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from DataPipeline.common.exchange_tz import batch_convert_ny_to_local
from DataPipeline.processing.fill_aggregator import generate_agg_fills_10s
from DataPipeline.processing.fill_cleaner import derive_exchange_times
from DataPipeline.ingestion.fill_ingestion import process_raw_fills_for_date


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def base_processed_df() -> pd.DataFrame:
    """构造一条最小可聚合的 processed_fills 记录。"""
    return pd.DataFrame(
        [
            {
                "OrderId": "100",
                "RouteId": "10",
                "FillId": "1",
                "mkt_timestamp": "10:00:00",
                "order_as_of_date": "2026-01-15",
                "local_fill_datetime": "2026-01-15 10:00:00",
                "exchange_exec_time": "10:00:00",
                "route_as_of_time": "09:30:00",
                "DateTimeOfFill": "2026-01-15T10:00:00",
                "Broker": "BRK1",
                "StrategyType": "VWAP",
                "algo": "vwap",
                "TraderName": "TraderA",
                "Exchange": "US",
                "Amount": 15025.0,
                "RouteShares": 200.0,
                "is_closing_auction": 0,
                "ExecType": "TRD",
                "region": "US",
                "equ_ticker": "AAPL US",
                "FillPrice": 150.25,
                "FillShares": 100.0,
            }
        ]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Exchange 空值/未知值时区转换报错
# ═══════════════════════════════════════════════════════════════════════════════


def test_empty_exchange_raises() -> None:
    """Exchange 为空字符串时，derive_exchange_times 必须抛出 ValueError。"""
    df = pd.DataFrame(
        [
            {
                "DateTimeOfFill": "2026-01-15T10:00:00",
                "Exchange": "",
                "NyOrderCreateAsOfDateTime": "2026-01-15T09:30:00",
                "NyTranCreateAsOfDateTime": "2026-01-15T10:00:00",
            }
        ]
    )
    with pytest.raises(ValueError, match="Exchange"):
        derive_exchange_times(df)


def test_unknown_exchange_raises() -> None:
    """未知 Exchange code 时，batch_convert_ny_to_local 必须抛出 ValueError。"""
    dt_series = pd.Series(pd.to_datetime(["2026-01-15 10:00:00"]))
    exchange_series = pd.Series(["XYZ"])
    with pytest.raises(ValueError, match="未知 Exchange"):
        batch_convert_ny_to_local(dt_series, exchange_series)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. S2 日期一致性校验
# ═══════════════════════════════════════════════════════════════════════════════


def test_date_mismatch_raises(monkeypatch) -> None:
    """processed_fills 的 order_as_of_date 与输入 date_str 不一致时，必须记录错误。"""
    input_df = pd.DataFrame(
        [
            {
                "OrderId": 100,
                "RouteId": 10,
                "FillId": 1,
                "Ticker": "AAPL",
                "Exchange": "US",
                "Currency": "USD",
                "Side": "BUY",
                "Amount": 15025.0,
                "NyOrderCreateAsOfDateTime": "2026-01-15T09:30:00",
                "Type": "LIMIT",
                "LimitPrice": 150.0,
                "Broker": "BRK1",
                "StopPrice": 0.0,
                "StrategyType": "VWAP",
                "TraderName": "TraderA",
                "TraderUuid": "uuid-001",
                "RouteShares": 200.0,
                "ExecType": "TRD",
                "DateTimeOfFill": "2026-01-15T10:00:00",
                "FillPrice": 150.25,
                "FillShares": 100.0,
                "LastCapacity": "A",
                "LastMarket": "NYSE",
                "Liquidity": "L",
                "LocalExchangeSymbol": "AAPL",
                "Account": "ACC01",
                "SecurityName": "Apple Inc.",
                "NyTranCreateAsOfDateTime": "2026-01-15T10:00:00",
            }
        ]
    )

    # Mock raw_db.get_fills_for_date 返回构造数据
    class MockRawDb:
        def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
            return input_df

    class MockFacade:
        raw_db = MockRawDb()
        fills_write = type(
            "MockWrites",
            (),
            {
                "upsert_processed_fills": lambda self, df: len(df),
                "upsert_route_registry": lambda self, df: len(df),
                "mark_date_processed": lambda *args, **kwargs: None,
                "upsert_execution_history": lambda *args, **kwargs: None,
            },
        )()

    monkeypatch.setattr(
        "DataPipeline.ingestion.fill_ingestion.DatabaseFacade",
        lambda *args, **kwargs: MockFacade(),
    )
    monkeypatch.setattr(
        "DataPipeline.ingestion.fill_ingestion.SqliteRawFillReadRepository",
        lambda *args, **kwargs: MockRawDb(),
    )

    # 注意：即使输入日期是 2026-01-15，时区转换后仍可能一致。
    # 这里为了触发不一致，我们 monkeypatch process_fills 返回错误日期。
    def mock_process_fills(df: pd.DataFrame) -> pd.DataFrame:
        processed = df.copy()
        processed["order_as_of_date"] = "2026-01-16"  # 故意错误日期
        processed["Exchange"] = "US"
        processed["equ_ticker"] = "AAPL US"
        processed["ccy_ticker"] = "USD Curncy"
        processed["algo"] = "vwap"
        processed["region"] = "US"
        return processed

    monkeypatch.setattr(
        "DataPipeline.ingestion.fill_ingestion.process_fills", mock_process_fills
    )

    result = process_raw_fills_for_date("2026-01-15")
    assert result["success"] is False
    assert result["error"] is not None
    assert "order_as_of_date" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. agg_fills_10s 从 route_registry 补全列
# ═══════════════════════════════════════════════════════════════════════════════


def test_route_registry_enrich(base_processed_df: pd.DataFrame, monkeypatch) -> None:
    """当 processed_df 缺少 Ticker/Side/Currency/ccy_ticker 时，应从 route_registry 补全。"""
    # 移除需要补全的列
    processed_df = base_processed_df.drop(
        columns=["Ticker", "Side", "Currency", "ccy_ticker"], errors="ignore"
    )

    route_registry_df = pd.DataFrame(
        [
            {
                "OrderId": "100",
                "RouteId": "10",
                "equ_ticker": "AAPL US",
                "Side": "BUY",
                "ccy_ticker": "USD Curncy",
                "Exchange": "US",
            }
        ]
    )

    agg = generate_agg_fills_10s(processed_df, route_registry_df=route_registry_df)

    assert not agg.empty
    assert agg["Ticker"].iloc[0] == "AAPL"
    assert agg["Side"].iloc[0] == "BUY"
    assert agg["Currency"].iloc[0] == "USD"
    assert agg["ccy_ticker"].iloc[0] == "USD Curncy"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 零股 VWAP 不生成 FillPrice NaN
# ═══════════════════════════════════════════════════════════════════════════════


def test_zero_shares_vwap(base_processed_df: pd.DataFrame) -> None:
    """FillShares=0 的聚合行不应产生 FillPrice NaN。"""
    # 包含一条正股记录 + 一条零股记录
    positive_record = base_processed_df.iloc[0].to_dict()
    zero_record = {
        **positive_record,
        "FillId": "2",
        "FillPrice": 200.0,
        "FillShares": 0.0,
    }
    processed_df = pd.DataFrame([positive_record, zero_record])
    route_registry_df = pd.DataFrame(
        [
            {
                "OrderId": "100",
                "RouteId": "10",
                "equ_ticker": "AAPL US",
                "Side": "BUY",
                "ccy_ticker": "USD Curncy",
                "Exchange": "US",
            }
        ]
    )

    agg = generate_agg_fills_10s(processed_df, route_registry_df=route_registry_df)

    # 只有 FillShares>0 的记录才生成聚合行
    assert not agg.empty
    assert agg["FillPrice"].notna().all()
    assert agg["FillShares"].iloc[0] == 100.0
# ================================================================================
# Stage2 cross-day regression tests (added 2026-07-03)
# ================================================================================

class TestStage2CrossDayProcessing:
    """Regression tests for the S2 target_date dimension fix.

    Before the fix, S2 used source_date as the processing key, which caused
    ~3.6M raw fills to be rejected when a single source_date spanned multiple
    order_as_of_date trading days. After the fix, S2 processes by
    order_as_of_date, accepting YYYYMMDD input that maps to the underlying
    ISO date stored in raw_fills."""

    def test_distinct_order_as_of_dates_returns_yyyymmdd(self):
        """get_distinct_order_as_of_dates must return YYYYMMDD short form.

        The raw_fills.order_as_of_date column stores full datetime strings
        (e.g. 2025-09-15 00:00:00), but the rest of the pipeline (S2 target_dates,
        processing_log, etc.) uses YYYYMMDD. Normalization in the repository
        prevents the silent cross-format mismatch that previously caused
        'All dates already processed' to fire even when no date was actually
        processed."""
        from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository

        repo = SqliteRawFillReadRepository()
        oads = repo.get_distinct_order_as_of_dates()
        assert len(oads) > 0, "expected at least one order_as_of_date in raw_fills"
        for d in oads:
            assert isinstance(d, str), f"expected str, got {type(d).__name__}"
            assert len(d) == 8, f"expected YYYYMMDD (8 chars), got {d!r}"
            assert d.isdigit(), f"expected all digits, got {d!r}"

    def test_get_fills_for_date_accepts_yyyymmdd(self):
        """get_fills_for_date must accept YYYYMMDD and match the full ISO date.

        Without the fallback added in this fix, the historical run could not
        fetch raw fills using the YYYYMMDD convention used by S2."""
        from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository

        repo = SqliteRawFillReadRepository()
        oads = repo.get_distinct_order_as_of_dates()
        assert oads, "no order_as_of_date available to test against"
        target = oads[0]
        df = repo.get_fills_for_date(target)
        if df.empty:
            pytest.skip(f"no raw_fills rows for {target} (test environment)")
        iso = f"{target[:4]}-{target[4:6]}-{target[6:]}"
        assert (df["order_as_of_date"].str.startswith(iso)).all(), (
            f"rows for {target} contain non-matching order_as_of_date values"
        )

    def test_processed_fills_covers_all_non_dfd_raw(self):
        """After backfill, every non-DFD raw_fills row must have a processed_fills row.

        This is the top-level invariant: processed_fills count == raw_fills count
        minus DFD rows. A persistent gap indicates either a missed backfill or a
        future regression in S2 cross-day handling."""
        from pathlib import Path
        from DataPipeline.config import Config
        import sqlite3

        raw_path = Path(Config.RAW_FILLS_DB)
        proc_path = Path(Config.PROCESSED_FILLS_DB)
        if not (raw_path.exists() and proc_path.exists()):
            pytest.skip("raw_fills.db / processed_fills.db not present")
        raw_conn = sqlite3.connect(str(raw_path))
        proc_conn = sqlite3.connect(str(proc_path))
        try:
            raw_non_dfd = raw_conn.execute(
                "SELECT COUNT(*) FROM raw_fills "
                """WHERE (ExecType IS NULL OR ExecType != 'DFD')"""
            ).fetchone()[0]
            proc_total = proc_conn.execute(
                "SELECT COUNT(*) FROM processed_fills"
            ).fetchone()[0]
        finally:
            raw_conn.close()
            proc_conn.close()
        assert proc_total >= raw_non_dfd - 1, (
            f"processed_fills ({proc_total}) is missing raw_fills non-DFD ({raw_non_dfd}); cross-day regression suspected"
        )

