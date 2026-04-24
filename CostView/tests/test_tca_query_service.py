"""
Unit tests for TcaQueryService.

Tests:
- Filter application (date, order_id, algo, broker, symbol)
- SQL injection safety
- Default date resolution
- fill_bdib empty â†’ data_source_warning
- fill_pct calculation
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from CostView.src.tca_query_service import TcaFilters, TcaQueryService


# â”€â”€â”€ Fixtures â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _make_proc_fills_db(path: str) -> None:
    """Create a minimal processed_fills.db with test data."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS processed_fills (
            FillId TEXT, OrderId TEXT, RouteId TEXT,
            mkt_timestamp TEXT, order_as_of_date TEXT,
            local_fill_datetime TEXT, exchange_exec_time TEXT,
            route_as_of_time TEXT, DateTimeOfFill TEXT,
            Broker TEXT, StrategyType TEXT, algo TEXT,
            TraderName TEXT, Exchange TEXT,
            Amount REAL, RouteShares REAL, is_closing_auction INTEGER,
            ExecType TEXT, region TEXT, FillPrice REAL, FillShares REAL,
            PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
        );
        CREATE TABLE IF NOT EXISTS route_registry (
            OrderId TEXT, RouteId TEXT,
            equ_ticker TEXT, Exchange TEXT, ccy_ticker TEXT, Side TEXT,
            count_fill INTEGER, count_broker INTEGER,
            count_algo INTEGER, count_trader INTEGER,
            PRIMARY KEY (OrderId, RouteId)
        );
        CREATE TABLE IF NOT EXISTS order_history (
            OrderId TEXT, order_as_of_date TEXT,
            equ_ticker TEXT, ccy_ticker TEXT, Side TEXT,
            Broker TEXT, algo TEXT, TraderName TEXT, Exchange TEXT,
            route_count INTEGER, fill_count INTEGER,
            total_fill_shares REAL, order_amount REAL, average_fill_price REAL,
            first_fill_time TEXT, last_fill_time TEXT,
            primary_source TEXT, source_priority TEXT,
            refresh_strategy TEXT, source_refreshed_at TEXT, source_lineage TEXT,
            PRIMARY KEY (OrderId, order_as_of_date)
        );
        CREATE TABLE IF NOT EXISTS route_history (
            OrderId TEXT, RouteId TEXT, order_as_of_date TEXT,
            equ_ticker TEXT, ccy_ticker TEXT, Side TEXT,
            Broker TEXT, algo TEXT, TraderName TEXT, Exchange TEXT,
            fill_count INTEGER, total_fill_shares REAL,
            order_amount REAL, route_shares REAL, average_fill_price REAL,
            first_fill_time TEXT, last_fill_time TEXT,
            primary_source TEXT, source_priority TEXT,
            refresh_strategy TEXT, source_refreshed_at TEXT, source_lineage TEXT,
            PRIMARY KEY (OrderId, RouteId, order_as_of_date)
        );
        CREATE TABLE IF NOT EXISTS route_event_history (
            event_id TEXT PRIMARY KEY,
            OrderId TEXT, RouteId TEXT, FillId TEXT, order_as_of_date TEXT,
            event_timestamp TEXT, event_type TEXT, event_source TEXT,
            event_action TEXT, ExecType TEXT, Broker TEXT, algo TEXT,
            TraderName TEXT, Exchange TEXT, equ_ticker TEXT, ccy_ticker TEXT,
            Side TEXT, FillPrice REAL, FillShares REAL, Amount REAL, RouteShares REAL,
            source_refreshed_at TEXT, refresh_strategy TEXT, source_lineage TEXT
        );

        INSERT INTO processed_fills VALUES
            ('F1','O1','R1','20260418 10:00:00','20260418','2026-04-18 10:00:00',
             '10:00:00','10:00:00','2026-04-18T10:00:00',
             'BrokerA','VWAP','VWAP','Trader1','US',
             1000.0,500.0,0,'FILL','US',50.00,500.0),
            ('F2','O1','R1','20260418 10:10:00','20260418','2026-04-18 10:10:00',
             '10:10:00','10:10:00','2026-04-18T10:10:00',
             'BrokerA','VWAP','VWAP','Trader1','US',
             1000.0,500.0,0,'FILL','US',50.50,500.0),
            ('F3','O2','R2','20260418 11:00:00','20260418','2026-04-18 11:00:00',
             '11:00:00','11:00:00','2026-04-18T11:00:00',
             'BrokerB','TWAP','TWAP','Trader2','US',
             2000.0,1000.0,0,'FILL','US',100.00,1000.0);

        INSERT INTO route_registry VALUES
            ('O1','R1','AAPL US Equity','US','USD US Curncy','Buy',2,1,1,1),
            ('O2','R2','MSFT US Equity','US','USD US Curncy','Sell',1,1,1,1);

        INSERT INTO order_history VALUES
            ('O1','20260418','AAPL US Equity','USD US Curncy','Buy','BrokerA','VWAP','Trader1','US',1,2,1000.0,1000.0,50.25,'2026-04-18 10:00:00','2026-04-18 10:10:00','costview.fill-rollup','costview.fill-rollup > executionview.orders_projection','rebuild-per-processed-date','2026-04-23T12:00:00','processed_fills -> order_history'),
            ('O2','20260418','MSFT US Equity','USD US Curncy','Sell','BrokerB','TWAP','Trader2','US',1,1,1000.0,2000.0,100.0,'2026-04-18 11:00:00','2026-04-18 11:00:00','costview.fill-rollup','costview.fill-rollup > executionview.orders_projection','rebuild-per-processed-date','2026-04-23T12:00:00','processed_fills -> order_history');

        INSERT INTO route_history VALUES
            ('O1','R1','20260418','AAPL US Equity','USD US Curncy','Buy','BrokerA','VWAP','Trader1','US',2,1000.0,1000.0,500.0,50.25,'2026-04-18 10:00:00','2026-04-18 10:10:00','costview.fill-rollup','costview.fill-rollup > executionview.routes_projection','rebuild-per-processed-date','2026-04-23T12:00:00','processed_fills -> route_history'),
            ('O2','R2','20260418','MSFT US Equity','USD US Curncy','Sell','BrokerB','TWAP','Trader2','US',1,1000.0,2000.0,1000.0,100.0,'2026-04-18 11:00:00','2026-04-18 11:00:00','costview.fill-rollup','costview.fill-rollup > executionview.routes_projection','rebuild-per-processed-date','2026-04-23T12:00:00','processed_fills -> route_history');

        INSERT INTO route_event_history VALUES
            ('fill:O1:R1:F1:20260418','O1','R1','F1','20260418','2026-04-18 10:00:00','FILL','emsx.history:GetFills','FILL','FILL','BrokerA','VWAP','Trader1','US','AAPL US Equity','USD US Curncy','Buy',50.0,500.0,1000.0,500.0,'2026-04-23T12:00:00','append-per-fill','emsx.history:GetFills > executionview.audit_events'),
            ('fill:O1:R1:F2:20260418','O1','R1','F2','20260418','2026-04-18 10:10:00','FILL','emsx.history:GetFills','FILL','FILL','BrokerA','VWAP','Trader1','US','AAPL US Equity','USD US Curncy','Buy',50.5,500.0,1000.0,500.0,'2026-04-23T12:00:00','append-per-fill','emsx.history:GetFills > executionview.audit_events'),
            ('fill:O2:R2:F3:20260418','O2','R2','F3','20260418','2026-04-18 11:00:00','FILL','emsx.history:GetFills','FILL','FILL','BrokerB','TWAP','Trader2','US','MSFT US Equity','USD US Curncy','Sell',100.0,1000.0,2000.0,1000.0,'2026-04-23T12:00:00','append-per-fill','emsx.history:GetFills > executionview.audit_events');
    """)
    conn.commit()
    conn.close()


def _make_fill_bdib_db(path: str, empty: bool = False) -> None:
    """Create a minimal fill_bdib.db with optional test data."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fill_bdib (
            OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, mkt_timestamp TEXT,
            equ_ticker TEXT, ccy_ticker TEXT, fill_volume REAL, fill_px REAL,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, value REAL, vwap REAL, log_chg_pct_10s REAL,
            fx_rate REAL, cum_vwap REAL, cum_fill_vwap REAL,
            cum_slippage_bps REAL, cum_slippage_usd REAL,
            cum_volume_pct REAL, cum_tracking_error REAL,
            cum_info_ratio REAL, cum_interval_volatility REAL,
            standard_cum_interval_volatility REAL,
            PRIMARY KEY (OrderId, RouteId, order_as_of_date, mkt_timestamp)
        )
    """)
    if not empty:
        conn.execute("""
            INSERT INTO fill_bdib VALUES
                ('O1','R1','20260418','20260418 10:10:00',
                 'AAPL US Equity','USD US Curncy',500.0,50.25,
                 50.0,51.0,49.5,50.5,
                 1000000.0,50250000.0,50.1,0.001,
                 1.0,50.1,50.25,-30.0,-150.0,
                 0.02,-28.0,0.15,0.18,0.20)
        """)
    conn.commit()
    conn.close()


def _make_raw_bdib_db(path: str) -> None:
    """Create a minimal raw_bdib.db."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_bdib (
            equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, num_trds REAL, value REAL,
            fetched_at TEXT, source TEXT,
            PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
        );
        CREATE TABLE IF NOT EXISTS bdib_daily_summary (
            equ_ticker TEXT, trade_date TEXT,
            total_volume REAL, daily_vwap REAL, daily_volatility REAL,
            adv_5d REAL, adv_20d REAL, computed_at TEXT,
            daily_close REAL, intraday_volatility REAL,
            PRIMARY KEY (equ_ticker, trade_date)
        );

        INSERT INTO raw_bdib VALUES
            ('AAPL US Equity','20260418','20260418 09:50:00',49.5,50.0,49.0,49.8,500000.0,500,24900000.0,datetime('now'),'bloomberg'),
            ('AAPL US Equity','20260418','20260418 10:00:00',50.0,50.5,49.8,50.1,600000.0,600,30060000.0,datetime('now'),'bloomberg'),
            ('AAPL US Equity','20260418','20260418 10:10:00',50.1,51.0,50.0,50.5,700000.0,700,35350000.0,datetime('now'),'bloomberg');

        INSERT INTO bdib_daily_summary VALUES
            ('AAPL US Equity','20260418',5000000.0,50.1,0.20,4800000.0,4600000.0,datetime('now'),50.5,1.25);
    """)
    conn.commit()
    conn.close()


def _make_raw_fills_db(path: str) -> None:
    """Create a minimal raw_fills.db."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_fills (
            OrderId TEXT, Account TEXT, SecurityName TEXT, Ticker TEXT,
            Exchange TEXT, Currency TEXT, Side TEXT, Amount TEXT,
            NyOrderCreateAsOfDateTime TEXT, Type TEXT, LimitPrice TEXT,
            Broker TEXT, StopPrice TEXT, StrategyType TEXT,
            TraderName TEXT, TraderUuid TEXT, RouteId TEXT,
            NyTranCreateAsOfDateTime TEXT, RouteShares TEXT, FillId TEXT,
            ExecType TEXT, DateTimeOfFill TEXT, FillPrice TEXT,
            FillShares TEXT, LastCapacity TEXT, LastMarket TEXT,
            Liquidity TEXT, LocalExchangeSymbol TEXT,
            order_as_of_date TEXT, order_as_of_time TEXT,
            exchange_exec_time TEXT, route_as_of_time TEXT,
            local_fill_datetime TEXT,
            source_date TEXT, fetched_at TEXT, ingested_at TEXT,
            PRIMARY KEY (OrderId, RouteId, FillId)
        )
    """)
    conn.executemany(
        "INSERT OR IGNORE INTO raw_fills (OrderId, RouteId, FillId, Amount, FillShares) VALUES (?,?,?,?,?)",
        [
            ("O1", "R1", "F1", "1000", "500"),
            ("O1", "R1", "F2", "1000", "500"),
            ("O2", "R2", "F3", "2000", "1000"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_dbs(tmp_path: Path):
    """Create all four test databases and return their paths."""
    proc = str(tmp_path / "processed_fills.db")
    bdib = str(tmp_path / "fill_bdib.db")
    raw_bdib = str(tmp_path / "raw_bdib.db")
    raw_fills = str(tmp_path / "raw_fills.db")

    _make_proc_fills_db(proc)
    _make_fill_bdib_db(bdib)
    _make_raw_bdib_db(raw_bdib)
    _make_raw_fills_db(raw_fills)

    return proc, bdib, raw_bdib, raw_fills


def _make_service(tmp_dbs) -> TcaQueryService:
    proc, bdib, raw_bdib, raw_fills = tmp_dbs
    return TcaQueryService(
        proc_fills_db_path=proc,
        fill_bdib_db_path=bdib,
        raw_bdib_db_path=raw_bdib,
        raw_fills_db_path=raw_fills,
    )


# â”€â”€â”€ Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestTcaFilters:
    def test_default_date_resolution(self):
        """Empty filters should resolve to the last weekday."""
        from datetime import date, timedelta
        filters = TcaFilters()
        resolved = TcaQueryService._resolve_date_defaults(filters)
        assert resolved.start_date is not None
        assert resolved.end_date is not None
        # Resolved date should be a weekday â‰¤ today
        d = date.fromisoformat(
            f"{resolved.start_date[:4]}-{resolved.start_date[4:6]}-{resolved.start_date[6:]}"
        )
        assert d < date.today()
        assert d.weekday() < 5  # Mon-Fri

    def test_explicit_dates_not_overridden(self):
        filters = TcaFilters(start_date="20260401", end_date="20260415")
        resolved = TcaQueryService._resolve_date_defaults(filters)
        assert resolved.start_date == "20260401"
        assert resolved.end_date == "20260415"

    def test_order_id_filter_prevents_default(self):
        """When order_ids are set, date defaults should not apply."""
        filters = TcaFilters(order_ids=["O1"])
        resolved = TcaQueryService._resolve_date_defaults(filters)
        assert resolved.start_date is None
        assert resolved.end_date is None


class TestGetMatchingRoutes:
    def test_route_history_is_preferred_when_present(self, tmp_dbs):
        proc, _bdib, _raw_bdib, _raw_fills = tmp_dbs
        conn = sqlite3.connect(proc)
        try:
            conn.execute(
                "UPDATE route_history SET Broker = ? WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ?",
                ("HistoryBroker", "O1", "R1", "20260418"),
            )
            conn.commit()
        finally:
            conn.close()

        svc = _make_service(tmp_dbs)
        rows, total = svc._get_matching_routes(
            TcaFilters(start_date="20260418", end_date="20260418", broker="HistoryBroker")
        )
        assert total == 1
        assert rows[0]["order_id"] == "O1"

    def test_date_filter(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(start_date="20260418", end_date="20260418")
        rows, total = svc._get_matching_routes(filters)
        assert total == 2  # O1/R1 and O2/R2

    def test_order_id_filter(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(order_ids=["O1"])
        rows, total = svc._get_matching_routes(filters)
        assert total == 1
        assert rows[0]["order_id"] == "O1"

    def test_algo_filter(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(start_date="20260418", end_date="20260418", algo="TWAP")
        rows, total = svc._get_matching_routes(filters)
        assert total == 1
        assert rows[0]["order_id"] == "O2"

    def test_broker_filter(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(start_date="20260418", end_date="20260418", broker="BrokerA")
        rows, total = svc._get_matching_routes(filters)
        assert total == 1
        assert rows[0]["order_id"] == "O1"

    def test_symbol_filter(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(
            start_date="20260418", end_date="20260418",
            symbol="MSFT US Equity"
        )
        rows, total = svc._get_matching_routes(filters)
        assert total == 1
        assert rows[0]["order_id"] == "O2"

    def test_pagination(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(
            start_date="20260418", end_date="20260418",
            limit=1, offset=0
        )
        rows, total = svc._get_matching_routes(filters)
        assert total == 2      # total without pagination
        assert len(rows) == 1  # only 1 row returned

    def test_no_results_for_unknown_algo(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(start_date="20260418", end_date="20260418", algo="NONEXISTENT")
        rows, total = svc._get_matching_routes(filters)
        assert total == 0
        assert rows == []


class TestSqlInjectionSafety:
    """Verify that malicious filter values cannot execute arbitrary SQL."""

    INJECTION_STRINGS = [
        "'; DROP TABLE processed_fills; --",
        "\" OR 1=1 --",
        "1' UNION SELECT 1,2,3 --",
        "'; INSERT INTO route_registry VALUES('x','x','x','x','x','x',0,0,0,0); --",
    ]

    def test_order_id_injection(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        for payload in self.INJECTION_STRINGS:
            filters = TcaFilters(order_ids=[payload])
            rows, total = svc._get_matching_routes(filters)
            # Must return 0 rows (payload doesn't match real data)
            assert total == 0, f"Injection payload returned rows: {payload!r}"

    def test_algo_injection(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        for payload in self.INJECTION_STRINGS:
            filters = TcaFilters(start_date="20260418", end_date="20260418", algo=payload)
            rows, total = svc._get_matching_routes(filters)
            assert total == 0, f"Injection payload returned rows: {payload!r}"

    def test_broker_injection(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        for payload in self.INJECTION_STRINGS:
            filters = TcaFilters(start_date="20260418", end_date="20260418", broker=payload)
            rows, total = svc._get_matching_routes(filters)
            assert total == 0

    def test_symbol_injection(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        for payload in self.INJECTION_STRINGS:
            filters = TcaFilters(start_date="20260418", end_date="20260418", symbol=payload)
            rows, total = svc._get_matching_routes(filters)
            assert total == 0

    def test_processed_fills_table_still_exists(self, tmp_dbs):
        """After injection attempts the table must still exist."""
        svc = _make_service(tmp_dbs)
        # Try the most aggressive payload
        filters = TcaFilters(order_ids=["'; DROP TABLE processed_fills; --"])
        try:
            svc._get_matching_routes(filters)
        except Exception:
            pass
        # If table was dropped, this query would raise
        conn = svc._proc_fills_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM processed_fills")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3, "processed_fills was modified by injection attempt"


class TestFillBdibEmpty:
    def test_data_source_warning_when_empty(self, tmp_path: Path):
        """If fill_bdib.db is empty, report must include data_source_warning."""
        proc = str(tmp_path / "processed_fills.db")
        bdib = str(tmp_path / "fill_bdib_empty.db")
        raw_bdib = str(tmp_path / "raw_bdib.db")
        raw_fills = str(tmp_path / "raw_fills.db")

        _make_proc_fills_db(proc)
        _make_fill_bdib_db(bdib, empty=True)
        _make_raw_bdib_db(raw_bdib)
        _make_raw_fills_db(raw_fills)

        svc = TcaQueryService(
            proc_fills_db_path=proc,
            fill_bdib_db_path=bdib,
            raw_bdib_db_path=raw_bdib,
            raw_fills_db_path=raw_fills,
        )
        filters = TcaFilters(start_date="20260418", end_date="20260418")
        report = svc.build_tca_report(filters)
        assert report.data_source_warning is not None
        assert "fill_bdib" in report.data_source_warning.lower()


class TestFillPercentages:
    def test_fill_pct_prefers_order_history_table(self, tmp_dbs):
        proc, _bdib, _raw_bdib, _raw_fills = tmp_dbs
        conn = sqlite3.connect(proc)
        try:
            conn.execute(
                "UPDATE order_history SET total_fill_shares = ? WHERE OrderId = ? AND order_as_of_date = ?",
                (900.0, "O1", "20260418"),
            )
            conn.commit()
        finally:
            conn.close()

        svc = _make_service(tmp_dbs)
        pcts = svc._get_fill_percentages(["O1"])
        assert pcts.get("O1") == pytest.approx(90.0)

    def test_fill_pct_100(self, tmp_dbs):
        """O1 filled 1000 shares out of 1000 â†’ 100%."""
        svc = _make_service(tmp_dbs)
        pcts = svc._get_fill_percentages(["O1"])
        assert pcts.get("O1") == pytest.approx(100.0)

    def test_fill_pct_50(self, tmp_dbs):
        """O2 filled 1000 out of 2000 â†’ 50%."""
        svc = _make_service(tmp_dbs)
        pcts = svc._get_fill_percentages(["O2"])
        assert pcts.get("O2") == pytest.approx(50.0)

    def test_unknown_order_returns_empty(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        pcts = svc._get_fill_percentages(["UNKNOWN"])
        assert pcts.get("UNKNOWN") is None


class TestBuildTcaReport:
    def test_report_structure(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(
            start_date="20260418", end_date="20260418",
            order_ids=["O1"]
        )
        report = svc.build_tca_report(filters)
        assert report.total_orders == 1
        assert len(report.orders) == 1
        order = report.orders[0]
        assert order.order_id == "O1"
        assert order.equ_ticker == "AAPL US Equity"
        assert order.fill_pct == pytest.approx(100.0)
        assert len(order.routes) == 1

    def test_report_adv_from_summary(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(
            start_date="20260418", end_date="20260418",
            order_ids=["O1"]
        )
        report = svc.build_tca_report(filters)
        order = report.orders[0]
        # ADV values come from bdib_daily_summary fixture
        assert order.volume_pct_adv5 is not None
        assert order.volume_pct_adv20 is not None

    def test_report_uses_filled_volume_for_adv_percentages(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_tca_report(
            TcaFilters(start_date="20260418", end_date="20260418", order_ids=["O1"])
        )

        order = report.orders[0]
        assert order.volume_pct_adv20 == pytest.approx(1000.0 / 4600000.0 * 100.0)

    def test_report_uses_daily_volatility_for_order_summary(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_tca_report(
            TcaFilters(start_date="20260418", end_date="20260418", order_ids=["O1"])
        )

        assert report.orders[0].daily_volatility == pytest.approx(0.20)

    def test_matching_routes_derives_local_exchange_times_from_datetime(self, tmp_dbs):
        proc, _bdib, _raw_bdib, _raw_fills = tmp_dbs
        conn = sqlite3.connect(proc)
        try:
            conn.execute(
                "UPDATE processed_fills SET Exchange = ?, DateTimeOfFill = ?, exchange_exec_time = ? WHERE OrderId = ? AND RouteId = ? AND FillId = ?",
                ("NZ", "2026-04-18T01:00:00-04:00", "01:00:00", "O1", "R1", "F1"),
            )
            conn.execute(
                "UPDATE processed_fills SET Exchange = ?, DateTimeOfFill = ?, exchange_exec_time = ? WHERE OrderId = ? AND RouteId = ? AND FillId = ?",
                ("NZ", "2026-04-18T01:10:00-04:00", "01:10:00", "O1", "R1", "F2"),
            )
            conn.execute(
                "UPDATE route_registry SET Exchange = ?, equ_ticker = ? WHERE OrderId = ? AND RouteId = ?",
                ("NZ", "AIA NZ Equity", "O1", "R1"),
            )
            conn.execute("DROP TABLE route_history")
            conn.execute("DROP TABLE order_history")
            conn.commit()
        finally:
            conn.close()

        svc = _make_service(tmp_dbs)
        rows, total = svc._get_matching_routes(
            TcaFilters(start_date="20260418", end_date="20260418", order_ids=["O1"])
        )

        assert total == 1
        assert rows[0]["start_time"] == "15:00:00"
        assert rows[0]["end_time"] == "15:10:00"

    def test_market_context_supports_time_only_bdib_timestamps(self, tmp_path: Path):
        raw_bdib = str(tmp_path / "raw_bdib.db")
        _make_raw_bdib_db(raw_bdib)

        conn = sqlite3.connect(raw_bdib)
        try:
            conn.execute("DELETE FROM raw_bdib")
            conn.executemany(
                "INSERT INTO raw_bdib VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("AAPL US Equity", "20260418", "09:59:50", 49.5, 50.0, 49.0, 49.8, 500000.0, 500, 24900000.0, "now", "bloomberg"),
                    ("AAPL US Equity", "20260418", "10:00:00", 50.0, 50.5, 49.8, 50.1, 600000.0, 600, 30060000.0, "now", "bloomberg"),
                    ("AAPL US Equity", "20260418", "10:10:00", 50.1, 51.0, 50.0, 50.5, 700000.0, 700, 35350000.0, "now", "bloomberg"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        svc = TcaQueryService(raw_bdib_db_path=raw_bdib)
        market_ctx = svc._get_market_context(
            {("AAPL US Equity", "20260418")},
            [{"equ_ticker": "AAPL US Equity", "order_as_of_date": "20260418", "start_time": "10:00:00", "end_time": "10:10:00"}],
            {},
        )

        row = market_ctx[("AAPL US Equity", "20260418")]
        assert row["before_interval_close"] == pytest.approx(49.8)
        assert row["interval_close"] == pytest.approx(50.5)
        assert row["price_movement_pct"] == pytest.approx((50.5 / 49.8 - 1.0) * 100.0)

    def test_report_falls_back_to_raw_bdib_for_missing_route_market_metrics(self, tmp_dbs):
        proc, bdib, raw_bdib, raw_fills = tmp_dbs
        conn = sqlite3.connect(bdib)
        try:
            conn.execute(
                "UPDATE fill_bdib SET cum_vwap = NULL, cum_tracking_error = NULL, cum_volume_pct = NULL WHERE OrderId = ? AND RouteId = ?",
                ("O1", "R1"),
            )
            conn.commit()
        finally:
            conn.close()

        svc = TcaQueryService(
            proc_fills_db_path=proc,
            fill_bdib_db_path=bdib,
            raw_bdib_db_path=raw_bdib,
            raw_fills_db_path=raw_fills,
        )
        report = svc.build_tca_report(
            TcaFilters(start_date="20260418", end_date="20260418", order_ids=["O1"])
        )

        route = report.orders[0].routes[0]
        assert route.interval_vwap == pytest.approx((30060000.0 + 35350000.0) / (600000.0 + 700000.0))
        assert route.volume_pct_interval == pytest.approx(1000.0 / (600000.0 + 700000.0) * 100.0)
        assert route.tracking_error_bps is not None

    def test_report_filters_reflected(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        filters = TcaFilters(start_date="20260418", end_date="20260418", algo="VWAP")
        report = svc.build_tca_report(filters)
        assert report.filters["algo"] == "VWAP"
        assert report.filters["start_date"] == "20260418"


# --- Scorecard tests ---------------------------------------------------------

from CostView.src.tca_query_service import ScorecardFilters


class TestScorecardBucketing:
    def test_time_of_day_buckets(self):
        assert TcaQueryService._bucket_time_of_day("09:45:00")[0] == "open"
        assert TcaQueryService._bucket_time_of_day("10:30:00")[0] == "mid"
        assert TcaQueryService._bucket_time_of_day("15:30:00")[0] == "close"
        assert TcaQueryService._bucket_time_of_day(None)[0] == "unknown"

    def test_liquidity_buckets(self):
        assert TcaQueryService._bucket_liquidity(0.4)[0] == "low"
        assert TcaQueryService._bucket_liquidity(3.0)[0] == "mid"
        assert TcaQueryService._bucket_liquidity(9.0)[0] == "high"
        assert TcaQueryService._bucket_liquidity(None)[0] == "unknown"

    def test_volatility_buckets(self):
        assert TcaQueryService._bucket_volatility(1.0)[0] == "calm"
        assert TcaQueryService._bucket_volatility(2.5)[0] == "typical"
        assert TcaQueryService._bucket_volatility(5.0)[0] == "stressed"

    def test_asset_class_derivation(self):
        assert TcaQueryService._asset_class_from_ticker("AAPL US Equity")[0] == "equity"
        assert TcaQueryService._asset_class_from_ticker("EURUSD Curncy")[0] == "fx"
        assert TcaQueryService._asset_class_from_ticker(None)[0] == "unknown"


class TestScorecardStatistics:
    def test_safe_percentile_handles_singletons(self):
        assert TcaQueryService._safe_percentile([5.0], 95) == 5.0
        assert TcaQueryService._safe_percentile([], 50) is None

    def test_safe_percentile_interpolates(self):
        values = [0.0, 10.0, 20.0, 30.0, 40.0]
        assert TcaQueryService._safe_percentile(values, 50) == pytest.approx(20.0)
        assert TcaQueryService._safe_percentile(values, 95) == pytest.approx(38.0)

    def test_safe_stddev_requires_multiple(self):
        assert TcaQueryService._safe_stddev([5.0]) is None
        assert TcaQueryService._safe_stddev([1.0, 3.0]) == pytest.approx(1.4142135, rel=1e-4)


class TestBuildScorecard:
    def test_invalid_cohort_raises(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        with pytest.raises(ValueError):
            svc.build_scorecard(ScorecardFilters(cohort="not_a_real_cohort"))

    def test_broker_strategy_cohort(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_scorecard(
            ScorecardFilters(
                cohort="broker_strategy",
                start_date="20260418",
                end_date="20260418",
                min_sample_size=1,
            )
        )
        assert report.cohort == "broker_strategy"
        assert report.total_orders_considered == 2
        assert report.total_orders_capped is False
        labels = {c.cohort_label for c in report.cohorts}
        # Only O1 (BrokerA/VWAP) has fill_bdib metrics in the fixture; O2 is
        # silently skipped because it lacks both exec_price and tracking error.
        assert "BrokerA | VWAP" in labels
        assert all(c.sample_size == 1 for c in report.cohorts)
        assert all(c.sample_size_warning is False for c in report.cohorts)

    def test_broker_cohort_sample_warning(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_scorecard(
            ScorecardFilters(
                cohort="broker",
                start_date="20260418",
                end_date="20260418",
                min_sample_size=5,
            )
        )
        assert all(c.sample_size_warning for c in report.cohorts)
        assert all("sample_size" in c.anomaly_flags for c in report.cohorts)

    def test_strategy_cohort_stats_match_order(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_scorecard(
            ScorecardFilters(
                cohort="strategy",
                start_date="20260418",
                end_date="20260418",
                order_ids=["O1"],
                min_sample_size=1,
            )
        )
        assert len(report.cohorts) == 1
        cohort = report.cohorts[0]
        assert cohort.cohort_label == "VWAP"
        assert cohort.sample_size == 1
        # Median and avg of a single sample equal the sample value.
        assert cohort.median_tracking_error_bps == cohort.avg_tracking_error_bps
        # Stddev is undefined for a single sample.
        assert cohort.stddev_tracking_error_bps is None

    def test_empty_bdib_reports_warning(self, tmp_path: Path):
        proc = str(tmp_path / "processed_fills.db")
        bdib = str(tmp_path / "fill_bdib_empty.db")
        raw_bdib = str(tmp_path / "raw_bdib.db")
        raw_fills = str(tmp_path / "raw_fills.db")
        _make_proc_fills_db(proc)
        _make_fill_bdib_db(bdib, empty=True)
        _make_raw_bdib_db(raw_bdib)
        _make_raw_fills_db(raw_fills)
        svc = TcaQueryService(
            proc_fills_db_path=proc,
            fill_bdib_db_path=bdib,
            raw_bdib_db_path=raw_bdib,
            raw_fills_db_path=raw_fills,
        )
        report = svc.build_scorecard(
            ScorecardFilters(
                cohort="broker",
                start_date="20260418",
                end_date="20260418",
                min_sample_size=1,
            )
        )
        assert report.data_source_warning is not None
        assert report.cohorts == []

    def test_filters_serialized_in_report(self, tmp_dbs):
        svc = _make_service(tmp_dbs)
        report = svc.build_scorecard(
            ScorecardFilters(
                cohort="broker",
                start_date="20260418",
                end_date="20260418",
                min_sample_size=3,
            )
        )
        assert report.filters["cohort"] == "broker"
        assert report.filters["start_date"] == "20260418"
        assert report.min_sample_size == 3
