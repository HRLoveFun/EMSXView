"""A14/227 — `get_intraday_features` 特征化测试（拆分前先锁行为）。

固定一份最小 BDIB 夹具，逐字段断言桶、开/收盘窗口、VWAP 与 ADV20 占比。
拆分函数后本测试必须逐字通过（除实现细节外行为不变）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from platform_data.adapters.market import MarketReferenceDataAdapter


class _Connection:
    def __init__(self, path: Path) -> None:
        self.raw_connection = sqlite3.connect(str(path))
        self.raw_connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.raw_connection.close()


class _Manager:
    """最小 ConnectionManager 替身：所有库名都指向同一临时 SQLite。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def get_connection(self, db_name: str, tier=None) -> _Connection:  # noqa: ANN001
        return _Connection(self.path)


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE raw_bdib ("
        "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "num_trds INTEGER, value REAL)"
    )
    conn.execute(
        "CREATE TABLE bdib_daily_summary ("
        "equ_ticker TEXT, trade_date TEXT, total_volume REAL, daily_vwap REAL, "
        "daily_close REAL, daily_volatility REAL, intraday_volatility REAL, "
        "adv_5d REAL, adv_20d REAL)"
    )

    # AAA: 6 bars, 2 x 30-min buckets; 09:30/09:31/09:59 then 10:00/10:01/10:02
    aaa = [
        ("09:30:00", 100.0, 100.0, 10.0),
        ("09:31:00", 101.0, 101.0, 10.0),
        ("09:59:00", 102.0, 102.0, 10.0),
        ("10:00:00", 103.0, 103.0, 10.0),
        ("10:01:00", 104.0, 104.0, 10.0),
        ("10:02:00", 105.0, 105.0, 10.0),
    ]
    for ts, close, high, volume in aaa:
        conn.execute(
            "INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("AAA US Equity", "20261120", ts, close, high, close, close, volume, 1, close * volume),
        )

    # BBB: 2 bars in one bucket
    for ts, close, volume in [("09:30:00", 200.0, 5.0), ("09:31:00", 201.0, 5.0)]:
        conn.execute(
            "INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("BBB US Equity", "20261120", ts, close, close, close, close, volume, 1, close * volume),
        )

    conn.execute(
        "INSERT INTO bdib_daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("AAA US Equity", "20261120", 60.0, 102.5, 105.0, 1.2, 0.3, 5000.0, 6000.0),
    )
    conn.execute(
        "INSERT INTO bdib_daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("BBB US Equity", "20261120", 10.0, 200.5, 201.0, 2.0, 0.4, 4000.0, 5000.0),
    )
    conn.commit()
    conn.close()
    return db


def _adapter(tmp_path: Path) -> MarketReferenceDataAdapter:
    return MarketReferenceDataAdapter(connection_manager=_Manager(_make_db(tmp_path)))


def test_intraday_features_characterization(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.get_intraday_features(
        equ_tickers=["AAA US Equity", "BBB US Equity", "CCC US Equity"],
        trade_date="20261120",
        bucket_minutes=30,
    )

    assert snap.trade_date == "20261120"
    assert snap.bucket_minutes == 30
    assert snap.ticker_count == 2
    assert snap.missing_tickers == ["CCC US Equity"]

    aaa = next(t for t in snap.tickers if t.equ_ticker == "AAA US Equity")
    assert aaa.bar_count == 6
    assert aaa.first_bar_time == "09:30"
    assert aaa.last_bar_time == "10:02"
    assert aaa.total_volume == pytest.approx(60.0)
    assert aaa.daily_vwap == pytest.approx(102.5)
    assert aaa.daily_close == pytest.approx(105.0)
    assert aaa.daily_volatility == pytest.approx(1.2)
    assert aaa.intraday_volatility == pytest.approx(0.3)
    assert aaa.adv_20d == pytest.approx(6000.0)
    assert aaa.volume_vs_adv20_pct == pytest.approx(1.0)

    assert len(aaa.buckets) == 2
    first, second = aaa.buckets
    assert (first.bucket_start, first.bucket_end) == ("09:30", "10:00")
    assert first.bar_count == 3
    assert first.volume == pytest.approx(30.0)
    assert first.cumulative_volume == pytest.approx(30.0)
    assert first.cumulative_volume_pct == pytest.approx(50.0)
    assert first.vwap == pytest.approx(101.0)
    assert first.close == pytest.approx(102.0)
    assert first.high == pytest.approx(102.0)
    assert first.low == pytest.approx(100.0)
    assert first.realized_vol_annualized is not None
    assert first.volume_vs_adv20_pct == pytest.approx(0.5)

    assert (second.bucket_start, second.bucket_end) == ("10:00", "10:30")
    assert second.bar_count == 3
    assert second.volume == pytest.approx(30.0)
    assert second.cumulative_volume == pytest.approx(60.0)
    assert second.cumulative_volume_pct == pytest.approx(100.0)
    assert second.vwap == pytest.approx(104.0)
    assert second.close == pytest.approx(105.0)

    assert aaa.open_window_volume == pytest.approx(20.0)
    assert aaa.open_window_vwap == pytest.approx(100.5)
    assert aaa.open_window_share_pct == pytest.approx(33.3333, abs=1e-4)
    assert aaa.close_window_volume == pytest.approx(40.0)
    assert aaa.close_window_vwap == pytest.approx(103.5)
    assert aaa.close_window_share_pct == pytest.approx(66.6667, abs=1e-4)

    bbb = next(t for t in snap.tickers if t.equ_ticker == "BBB US Equity")
    assert bbb.bar_count == 2
    assert bbb.total_volume == pytest.approx(10.0)
    assert bbb.daily_vwap == pytest.approx(200.5)
    assert len(bbb.buckets) == 1
    assert bbb.buckets[0].vwap == pytest.approx(200.5)
    assert bbb.open_window_volume == pytest.approx(10.0)
    assert bbb.close_window_volume == pytest.approx(10.0)


def test_validation_and_empty_paths(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    with pytest.raises(ValueError):
        adapter.get_intraday_features(equ_tickers=["A"], trade_date="20261120", bucket_minutes=7)
    with pytest.raises(ValueError):
        adapter.get_intraday_features(equ_tickers=[], trade_date="20261120")

    empty = adapter.get_intraday_features(equ_tickers=["AAA US Equity"], trade_date=None)
    assert empty.ticker_count == 0
    assert empty.missing_tickers == ["AAA US Equity"]

    no_manager = MarketReferenceDataAdapter(connection_manager=None)
    snapshot = no_manager.get_intraday_features(
        equ_tickers=["AAA US Equity"], trade_date="20261120",
    )
    assert snapshot.ticker_count == 0
    assert snapshot.missing_tickers == ["AAA US Equity"]
