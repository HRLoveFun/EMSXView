"""057 DL-09：日度基线优先读快照表（竞价占比/价差代理），缺失回退 bar 扫描。

锁死行为：
1. 快照表有该票当日行 → 三列取快照值，不再扫 10 秒 bar；
2. 旧数据目录无该表 → 回退 bar 计算（与 DL-10 原口径一致）；
3. 快照表存在但该票无行 → 走空基线（summary 也无行）。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_access import ConnectionManager  # noqa: E402
from platform_data.adapters.baseline import DailyBaselineAdapter  # noqa: E402

TICKER = "SEC_A US Equity"
DATES = [f"2026{'%02d%02d' % (9, d)}" for d in range(1, 26)]


def _seed(tmp_path: Path, *, snapshot: tuple | None) -> ConnectionManager:
    """summary 25 日 + 末日三根 bar；可选快照表一行。"""
    db_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE bdib_daily_summary (equ_ticker TEXT, trade_date TEXT, total_volume REAL, "
        "daily_vwap REAL, daily_volatility REAL, adv_5d REAL, adv_20d REAL, computed_at TEXT, "
        "daily_close REAL, intraday_volatility REAL)"
    )
    conn.execute(
        "CREATE TABLE raw_bdib (equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume REAL, num_trds INTEGER, value REAL)"
    )
    for i, date in enumerate(DATES):
        conn.execute(
            "INSERT INTO bdib_daily_summary VALUES (?,?,?,?,?,?,?,?,?,?)",
            (TICKER, date, 1_000_000 + i * 1000, 100.0, 20.0, 900_000, 950_000, "x", 100.0, 0.02),
        )
    for ts, high, low, close, volume in [
        ("09:30:00", 100.2, 99.8, 100.0, 50_000),
        ("09:30:10", 100.3, 99.9, 100.1, 30_000),
        ("15:59:50", 101.2, 100.9, 101.0, 120_000),
    ]:
        conn.execute(
            "INSERT INTO raw_bdib VALUES (?,?,?,?,?,?,?,?,?,?)",
            (TICKER, DATES[-1], ts, close, high, low, close, volume, 1, close * volume),
        )
    if snapshot is not None:
        conn.execute(
            "CREATE TABLE bdib_market_snapshot (equ_ticker TEXT, trade_date TEXT, "
            "auction_open_pct REAL, auction_close_pct REAL, spread_proxy_bps REAL)"
        )
        conn.execute(
            "INSERT INTO bdib_market_snapshot VALUES (?,?,?,?,?)",
            (TICKER, DATES[-1], *snapshot),
        )
    conn.commit()
    conn.close()
    return ConnectionManager(path_overrides={"raw_bdib": db_path})


def test_snapshot_columns_take_precedence(tmp_path):
    cm = _seed(tmp_path, snapshot=(7.5, 12.5, 33.3))
    [baseline] = DailyBaselineAdapter().get_baseline([TICKER], connection_manager=cm)
    assert baseline.auction_open_pct == 7.5
    assert baseline.auction_close_pct == 12.5
    assert baseline.spread_proxy_bps == 33.3


def test_falls_back_to_bars_without_snapshot_table(tmp_path):
    cm = _seed(tmp_path, snapshot=None)
    [baseline] = DailyBaselineAdapter().get_baseline([TICKER], connection_manager=cm)
    # US 无开盘集合竞价窗口；收盘窗口取 15:55–16:00 的 bar
    assert baseline.auction_open_pct is None
    assert baseline.auction_close_pct == pytest.approx(60.0, abs=1e-3)
    assert baseline.spread_proxy_bps is None  # 有效 bar 3 根 < 5


def test_unknown_ticker_stays_empty_even_with_snapshot_table(tmp_path):
    cm = _seed(tmp_path, snapshot=(7.5, 12.5, 33.3))
    [baseline] = DailyBaselineAdapter().get_baseline(["OTHER US Equity"], connection_manager=cm)
    assert baseline.auction_open_pct is None
    assert baseline.n_days == 0
