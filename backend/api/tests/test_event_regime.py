"""057 DL-11（067）：事件与市场级状态适配器测试（端点测试见 MarketView/tests/test_regime_router.py）。

覆盖子规格 §2.3 检验方法 1/2：
1. 适配器集成（tmp regime 库夹具）：三状态读取、宏观事件窗口命中（内/外）、
   config_version 透传、未知市场 None、批量 missing；
2. event_flags_for_ticker：半日市命中、导出财报/除息标记、无导出行 coverage 披露。

夹具全部虚构数据（市场码 ZZ、事件类型 fictional_event）。
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

from platform_data.adapters.events import (  # noqa: E402
    SOURCE_EMSX_EXPORT,
    SOURCE_HALF_DAY_TABLE,
    SOURCE_MACRO_CALENDAR,
    EventRegimeAdapter,
)
from data_access.storage.connection import ConnectionManager  # noqa: E402


@pytest.fixture()
def regime_db(tmp_path: Path) -> ConnectionManager:
    """regime.db 夹具：ZZ 市场 3 个日期的三状态 + 2 条宏观事件（窗口内/外）。"""
    db_path = tmp_path / "regime.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE daily_liquidity_regime (market_code TEXT, trade_date TEXT, config_version TEXT, "
        "liq_regime TEXT, turnover_zscore REAL, method TEXT, source_version TEXT, ingested_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE daily_vol_regime (market_code TEXT, trade_date TEXT, config_version TEXT, "
        "vol_regime TEXT, vol_score REAL, method TEXT, source_version TEXT, ingested_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE daily_trend_regime (market_code TEXT, trade_date TEXT, config_version TEXT, "
        "trend_regime TEXT, ma_signal TEXT, rsi_30d REAL, dist_52w_high_pct REAL, method TEXT, "
        "source_version TEXT, ingested_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE ref_macro_event_calendar (event_date TEXT, market_code TEXT, event_type TEXT, "
        "severity TEXT, window_days INTEGER, description TEXT, source_file_version TEXT, synced_at TEXT)"
    )

    for date, liq, vol, trend in [
        ("20261020", "thin", "high", "downtrend"),
        ("20261021", "normal", "normal", "range"),
        ("20261022", "thick", "low", "uptrend"),
    ]:
        conn.execute(
            "INSERT INTO daily_liquidity_regime "
            "(market_code, trade_date, config_version, liq_regime, turnover_zscore, method, source_version, ingested_at) "
            "VALUES (?, ?, 'v0_test', ?, -1.5, 'turnover_zscore', 'x', 'y')",
            ("ZZ", date, liq),
        )
        conn.execute(
            "INSERT INTO daily_vol_regime "
            "(market_code, trade_date, config_version, vol_regime, vol_score, method, source_version, ingested_at) "
            "VALUES (?, ?, 'v0_test', ?, 30.0, 'vix_absolute', 'x', 'y')",
            ("ZZ", date, vol),
        )
        conn.execute(
            "INSERT INTO daily_trend_regime "
            "(market_code, trade_date, config_version, trend_regime, ma_signal, rsi_30d, dist_52w_high_pct, method, source_version, ingested_at) "
            "VALUES (?, ?, 'v0_test', ?, 'ma50<ma200', 30.0, -0.2, 'ma_rsi_combo', 'x', 'y')",
            ("ZZ", date, trend),
        )
    # 窗口内：event 2026-10-22、window 2 天 → 20261020–20261022 命中；20261023 不命中
    # （event_date 用横线格式，与 regime 库真实数据一致；trade_date 参数为 YYYYMMDD，
    # 适配器内部归一化）
    conn.execute(
        "INSERT INTO ref_macro_event_calendar VALUES ('2026-10-22', 'ZZ', 'fictional_event', 'high', 2, '虚构事件', 'v1', 'y')"
    )
    # 窗口外：event 2026-10-10、window 1 天 → 对 20261021 不可见
    conn.execute(
        "INSERT INTO ref_macro_event_calendar VALUES ('2026-10-10', 'ZZ', 'old_event', 'normal', 1, '旧事件', 'v1', 'y')"
    )
    conn.commit()
    conn.close()
    return ConnectionManager(path_overrides={"regime": db_path})


class TestMarketState:
    """① 市场级状态。"""

    def test_reads_three_regimes_and_config(self, regime_db):
        state = EventRegimeAdapter().get_market_state("ZZ", as_of="20261021", connection_manager=regime_db)

        assert state is not None
        assert state.liq_regime == "normal"
        assert state.vol_regime == "normal"
        assert state.trend_regime == "range"
        assert state.config_version == "v0_test"
        assert state.schema_version == "market-regime-v1"
        assert state.as_of == "20261021"

    def test_macro_event_window_hit_and_miss(self, regime_db):
        state = EventRegimeAdapter().get_market_state("ZZ", as_of="20261021", connection_manager=regime_db)

        codes = [e.code for e in state.macro_events]
        assert codes == ["fictional_event"]  # 窗口内命中；old_event 窗口外不可见
        event = state.macro_events[0]
        assert event.severity == "high"
        assert event.source == SOURCE_MACRO_CALENDAR
        assert event.window_days == 2

    def test_latest_date_default(self, regime_db):
        # as_of 缺省 → 各表最近交易日（20261022）
        state = EventRegimeAdapter().get_market_state("ZZ", connection_manager=regime_db)

        assert state.as_of == "20261022"
        assert state.liq_regime == "thick"

    def test_unknown_market_returns_none(self, regime_db):
        assert EventRegimeAdapter().get_market_state("NOPE", connection_manager=regime_db) is None

    def test_batch_reports_missing(self, regime_db):
        states = EventRegimeAdapter().get_market_states(["ZZ", "NOPE"], connection_manager=regime_db)

        assert [s.market_code for s in states] == ["ZZ"]


class TestTickerEvents:
    """② 逐票事件（半日市 + 导出尽力而为）。"""

    def test_half_day_hit(self):
        flags, covered = EventRegimeAdapter().event_flags_for_ticker(
            "SEC_A US Equity", trade_date="2026-11-27"  # DL-03 静态条目
        )

        assert covered is False  # 无导出行
        codes = [f.code for f in flags]
        assert "half_day" in codes
        half_day = next(f for f in flags if f.code == "half_day")
        assert half_day.source == SOURCE_HALF_DAY_TABLE
        assert half_day.evidence == "close 13:00"

    def test_export_fields_mark_earnings_and_dividend(self):
        flags, covered = EventRegimeAdapter().event_flags_for_ticker(
            "SEC_A US Equity",
            trade_date="2026-10-22",
            export_row={"Exp Earn Rpt Time": "2026-10-28", "Ex-Dvd Flag": "Y"},
        )

        assert covered is True
        codes = {f.code for f in flags}
        assert codes == {"earnings", "ex_dividend"}
        earnings = next(f for f in flags if f.code == "earnings")
        assert earnings.source == SOURCE_EMSX_EXPORT
        assert earnings.evidence == "2026-10-28"

    def test_export_row_without_values(self):
        flags, covered = EventRegimeAdapter().event_flags_for_ticker(
            "SEC_A US Equity",
            trade_date="2026-10-22",
            export_row={"Exp Earn Rpt Time": "", "Ex-Dvd Flag": "N"},
        )

        assert covered is True
        assert flags == []  # 导出存在但无事件值 → 无标记（不伪造）

    def test_no_half_day_no_export(self):
        flags, covered = EventRegimeAdapter().event_flags_for_ticker(
            "SEC_A US Equity", trade_date="2026-10-22"
        )

        assert flags == []
        assert covered is False
