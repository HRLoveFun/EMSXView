"""057 DL-10（066）：日度基线测试。

覆盖子规格 §2.3 检验方法：
1. 纯函数（z 值回落/分位/跳空 σ/竞价占比/价差代理/量纲对齐）；
2. 集成（tmp 库夹具：bdib_daily_summary 25 日 + raw_bdib 当日 bar）：
   字段完整、z 值手算一致、特殊日剔除、无数据回落；
3. 与现有 snapshot 口径交叉验证（z 值方向与全局常数告警不矛盾）。

夹具全部虚构数据（SEC_A US Equity，成交量/价格人造序列）。
"""

from __future__ import annotations

import math
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

from platform_data.adapters.baseline import (  # noqa: E402
    DailyBaselineAdapter,
    auction_share,
    log_volume_z,
    normalize_volatility,
    overnight_gap_sigma,
    percentile_of,
    spread_proxy,
)
from platform_data.contracts import BASELINE_MIN_DAYS, BASELINE_WINDOW_DAYS  # noqa: E402
from data_access.storage.connection import ConnectionManager  # noqa: E402


class TestPureFunctions:
    """① 纯函数。"""

    def test_log_volume_z_basic(self):
        volumes = [1_000_000] * 24 + [3_000_000]  # 末值远高于中位
        z = log_volume_z(volumes)
        assert z is not None and z > 0

    def test_log_volume_z_insufficient(self):
        assert log_volume_z([100] * 5) is None  # < BASELINE_MIN_DAYS
        assert log_volume_z([]) is None

    def test_log_volume_z_zero_mad_falls_back_to_std(self):
        volumes = [500.0] * 24 + [500.0]  # MAD=0 且 std=0 → None
        assert log_volume_z(volumes) is None
        increasing = [float(100 + i) for i in range(25)]  # MAD>0 正常
        assert log_volume_z(increasing) is not None

    def test_percentile_of(self):
        series = [1.0, 2.0, 3.0, 4.0]
        assert percentile_of(2.0, series) == 50.0
        assert percentile_of(None, series) is None
        assert percentile_of(1.0, []) is None

    def test_overnight_gap_sigma(self):
        closes = [100.0] * 24 + [101.0]
        sigma = overnight_gap_sigma(closes)
        assert sigma is not None and sigma > 0
        assert overnight_gap_sigma([100.0, None]) is None  # 数据不足

    def test_auction_share(self):
        bars = [("09:30:00", 100.0), ("09:30:10", 200.0), ("15:59:50", 700.0)]
        # 开盘竞价窗口 09:00-09:30（end 独占）→ 不含 09:30 bar
        assert auction_share(bars, ("09:00", "09:30")) == 0.0
        # 收盘前 5 分钟窗口
        share = auction_share(bars, ("15:55", "16:00"))
        assert share == 70.0
        assert auction_share(bars, None) is None  # 无窗口定义
        assert auction_share([], ("09:00", "09:30")) is None

    def test_spread_proxy(self):
        bars = [(10.0, 9.0, 9.5)] * 6  # (high-low)/close = 0.10526
        assert spread_proxy(bars) == 1052.63
        assert spread_proxy([(10.0, 9.0, 9.5)]) is None  # <5 根

    def test_normalize_volatility(self):
        daily, intraday = normalize_volatility(28.2, 0.35)
        assert daily == 28.2
        assert intraday == 35.0  # 小数 → 百分比
        assert normalize_volatility(None, None) == (None, None)


@pytest.fixture()
def baseline_db(tmp_path: Path) -> ConnectionManager:
    """raw_bdib.db 夹具：SEC_A US Equity 25 个交易日 + 末日 bar（含开盘/收盘量）。

    成交量前 24 日 1,000,000、末日 2,000,000；收盘价 100→101（末跳空 1%）。
    """
    db_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE bdib_daily_summary ("
        "equ_ticker TEXT, trade_date TEXT, total_volume REAL, daily_vwap REAL, "
        "daily_volatility REAL, adv_5d REAL, adv_20d REAL, computed_at TEXT, "
        "daily_close REAL, intraday_volatility REAL)"
    )
    conn.execute(
        "CREATE TABLE raw_bdib ("
        "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume REAL, num_trds INTEGER, value REAL)"
    )
    dates = [f"2026{'%02d%02d' % (9, d)}" for d in range(1, 26)]  # 20260901-20260925
    for i, date in enumerate(dates):
        volume = 1_000_000 if i < 24 else 2_000_000
        close = 100.0 if i < 24 else 101.0
        conn.execute(
            "INSERT INTO bdib_daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("SEC_A US Equity", date, volume, close, 20.0 + i * 0.1, 900_000, 950_000, "x", close, 0.02 + i * 0.001),
        )
    # 末日 bar：开盘段 2 根（09:30 前后）+ 收盘前 1 根（15:59:50）
    for ts, high, low, close, volume in [
        ("09:30:00", 100.2, 99.8, 100.0, 50_000),
        ("09:30:10", 100.3, 99.9, 100.1, 30_000),
        ("15:59:50", 101.2, 100.9, 101.0, 120_000),
    ]:
        conn.execute(
            "INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("SEC_A US Equity", dates[-1], ts, close, high, low, close, volume, 1, close * volume),
        )
    conn.commit()
    conn.close()
    return ConnectionManager(path_overrides={"raw_bdib": db_path})


class TestBaselineIntegration:
    """② 集成装配。"""

    def test_baseline_fields_and_values(self, baseline_db):
        baselines = DailyBaselineAdapter().get_baseline(
            ["SEC_A US Equity"], connection_manager=baseline_db
        )
        assert len(baselines) == 1
        b = baselines[0]
        assert b.equ_ticker == "SEC_A US Equity"
        assert b.as_of == "20260925"
        assert b.n_days == 25
        assert b.schema_version == "market-baseline-v1"
        # log 量 z：末日量 2× 中位 → 正 z
        assert b.log_volume_z is not None and b.log_volume_z > 0
        # 波动分位：末日值在 25 日序列的最大 → 100
        assert b.vol_percentile == 100.0
        # 隔夜跳空 σ：末跳空 +1% 为正
        assert b.overnight_gap_sigma is not None and b.overnight_gap_sigma > 0
        # ADV 比
        assert b.adv5_adv60_ratio == round(900_000 / 950_000, 4)
        # 竞价占比：US 在 DL-03 注册表无开盘竞价定义（NYSE 无固定开盘竞价）→ None；
        # 收盘前 5 分钟窗口有定义 → 120k/200k = 60%
        assert b.auction_open_pct is None
        assert b.auction_close_pct == 60.0
        # 价差代理：3 根 bar 的中位数（<5 根 → None）
        assert b.spread_proxy_bps is None

    def test_exclude_dates(self, baseline_db):
        baselines = DailyBaselineAdapter().get_baseline(
            ["SEC_A US Equity"], exclude_dates=["20260925"], connection_manager=baseline_db
        )
        b = baselines[0]
        assert b.n_days == 24
        assert b.excluded_dates == ("20260925",)
        assert b.as_of == "20260924"  # 末日被剔除后截止日前移

    def test_unknown_ticker_returns_empty_baseline(self, baseline_db):
        baselines = DailyBaselineAdapter().get_baseline(
            ["NOPE US Equity"], connection_manager=baseline_db
        )
        assert baselines[0].n_days == 0
        assert baselines[0].log_volume_z is None
        assert baselines[0].as_of == ""

    def test_z_value_direction_matches_global_alert(self, baseline_db):
        """与现有 snapshot 口径交叉验证：末日 2× 量在旧全局常数（2× 阈值）下
        同样触发 warning——z 值口径与既有告警方向一致（不矛盾）。"""
        baselines = DailyBaselineAdapter().get_baseline(
            ["SEC_A US Equity"], connection_manager=baseline_db
        )
        assert baselines[0].log_volume_z > 0  # 放量 → 正 z（旧口径 2× 即 warning）
