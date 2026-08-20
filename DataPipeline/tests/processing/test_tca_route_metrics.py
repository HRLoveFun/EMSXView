"""tca_route_metrics 单元测试。

覆盖 _compute_all_pwp 与 compute_route_metrics_for_date 的核心路径，
防止 _PWP_RATES 命名等回归问题。
"""

from __future__ import annotations

import pandas as pd
import pytest

from DataPipeline.processing.tca_route_metrics import (
    _compute_all_pwp,
    compute_route_metrics_for_date,
    load_raw_bdib_for_date,
)


def _make_bars(
    times: list[str],
    volumes: list[float],
    prices: list[float],
) -> pd.DataFrame:
    """构造 raw_bdib bars DataFrame（含 close/open 列）。"""
    return pd.DataFrame({
        "equ_ticker": ["AAPL US Equity"] * len(times),
        "order_as_of_date": ["20260421"] * len(times),
        "mkt_timestamp": times,
        "volume": volumes,
        "value": [v * p for v, p in zip(volumes, prices)],
        "close": prices,
        "open": prices,
    })


class TestComputeAllPwp:
    """测试 PWP 各档位计算。"""

    def test_hits_all_thresholds_for_buy(self) -> None:
        """当累计成交量足够时，所有 PWP 档位都应命中。"""
        # 成交量 1000，5% 档位需要市场成交量 20000
        bars = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20", "09:30:30", "09:30:40"],
            volumes=[5000.0] * 5,
            prices=[100.0] * 5,
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")

        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is not None
            assert result[col] == pytest.approx(0.0)

    def test_returns_none_when_not_enough_volume(self) -> None:
        """累计成交量不足以达到任何档位阈值时，所有值为 None。"""
        bars = _make_bars(
            times=["09:30:00", "09:30:10"],
            volumes=[100.0, 200.0],
            prices=[100.0, 100.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")

        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is None

    def test_respects_start_time(self) -> None:
        """只统计 start_time 之后的 bars。"""
        bars = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20"],
            volumes=[5000.0, 5000.0, 5000.0],
            prices=[100.0, 100.0, 100.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:15")

        # start_time 之后只有 1 个 bar（5000），无法达到 5% 档位阈值 20000
        assert result["pwp_5"] is None

    def test_sell_side_produces_negative_pnl(self) -> None:
        """Sell 方向：PWP 价格高于成交价时 PnL 为负。"""
        bars = _make_bars(
            times=["09:30:00"],
            volumes=[50000.0],
            prices=[101.0],
        )

        result = _compute_all_pwp(bars, fill_volume=1000.0, p_avg=100.0, side_sign=-1, start_time="09:30:00")

        # pwp=101, p_avg=100, sell side_sign=-1 => (101/100 - 1) * -1 * 10000 = -100 bps
        assert result["pwp_5"] is not None
        assert result["pwp_5"] == pytest.approx(-100.0)

    def test_empty_bars_returns_all_none(self) -> None:
        """空 bars 输入不应抛异常，所有 PWP 值为 None。"""
        result = _compute_all_pwp(pd.DataFrame(), fill_volume=1000.0, p_avg=100.0, side_sign=1, start_time="09:30:00")
        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert result[col] is None


class TestLoadRawBdibForDate:
    """测试 load_raw_bdib_for_date 的 SQLite/Parquet 双源读取。"""

    def _write_sqlite(
        self,
        tmp_path: Path,
        data: list[dict[str, Any]],
        date_str: str = "20260201",
    ) -> Path:
        """构造临时 SQLite raw_bdib 文件（含 close/open 列，对齐生产 schema）。"""
        db_path = tmp_path / "raw_bdib.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE raw_bdib ("
            "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
            "volume REAL, value REAL, close REAL, open REAL)"
        )
        if data:
            rows = [
                (
                    row["equ_ticker"], date_str, row["mkt_timestamp"],
                    row.get("volume"), row.get("value"),
                    row.get("close", row.get("value")),
                    row.get("open", row.get("value")),
                )
                for row in data
            ]
            conn.executemany(
                "INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?, ?, ?)", rows
            )
        conn.commit()
        conn.close()
        return db_path

    def _write_parquet(
        self,
        tmp_path: Path,
        data: list[dict[str, Any]],
        date_str: str = "20260201",
    ) -> Path:
        """构造临时按年月分区的 Parquet 文件。"""
        pytest.importorskip("pyarrow")
        parquet_dir = tmp_path / "bdib_10s"
        parquet_dir.mkdir(parents=True, exist_ok=True)
        year = date_str[:4]
        month = date_str[4:6]
        partition_dir = parquet_dir / f"year={year}" / f"month={month}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(data)
        df["order_as_of_date"] = date_str
        df["close"] = df.get("close", df["value"])
        df["open"] = df.get("open", df["value"])
        df["year"] = int(year)
        df["month"] = month
        out_path = partition_dir / f"data_{date_str}.parquet"
        df.to_parquet(out_path, index=False)
        return parquet_dir

    def test_prefers_sqlite_when_data_exists(self, tmp_path: Path) -> None:
        """SQLite 中存在目标日期数据时，直接返回，不依赖 Parquet。"""
        pytest.importorskip("duckdb")
        pytest.importorskip("pyarrow")
        bars = [
            {"equ_ticker": "AAPL US Equity", "mkt_timestamp": "09:30:00", "volume": 100.0, "value": 10000.0},
        ]
        db_path = self._write_sqlite(tmp_path, bars)
        parquet_dir = tmp_path / "empty_parquet"
        parquet_dir.mkdir(parents=True, exist_ok=True)

        df = load_raw_bdib_for_date(
            "20260201", raw_bdib_db_path=db_path, parquet_dir=parquet_dir
        )

        assert len(df) == 1
        assert df.iloc[0]["equ_ticker"] == "AAPL US Equity"

    def test_falls_back_to_parquet_when_sqlite_empty(self, tmp_path: Path) -> None:
        """SQLite 中无数据时，回退到 Parquet 分区读取。"""
        pytest.importorskip("duckdb")
        pytest.importorskip("pyarrow")
        db_path = self._write_sqlite(tmp_path, [])
        parquet_dir = self._write_parquet(
            tmp_path,
            [{"equ_ticker": "TSLA US Equity", "mkt_timestamp": "10:00:00", "volume": 200.0, "value": 40000.0}],
            "20260201",
        )

        df = load_raw_bdib_for_date(
            "20260201", raw_bdib_db_path=db_path, parquet_dir=parquet_dir
        )

        assert len(df) == 1
        assert df.iloc[0]["equ_ticker"] == "TSLA US Equity"
        assert df.iloc[0]["volume"] == pytest.approx(200.0)

    def test_filters_by_equ_tickers(self, tmp_path: Path) -> None:
        """Parquet 回退时支持按 equ_ticker 列表过滤。"""
        pytest.importorskip("duckdb")
        pytest.importorskip("pyarrow")
        db_path = self._write_sqlite(tmp_path, [])
        parquet_dir = self._write_parquet(
            tmp_path,
            [
                {"equ_ticker": "AAPL US Equity", "mkt_timestamp": "09:30:00", "volume": 100.0, "value": 10000.0},
                {"equ_ticker": "TSLA US Equity", "mkt_timestamp": "10:00:00", "volume": 200.0, "value": 40000.0},
            ],
            "20260201",
        )

        df = load_raw_bdib_for_date(
            "20260201",
            equ_tickers=["TSLA US Equity"],
            raw_bdib_db_path=db_path,
            parquet_dir=parquet_dir,
        )

        assert len(df) == 1
        assert df.iloc[0]["equ_ticker"] == "TSLA US Equity"

    def test_returns_empty_when_both_sources_empty(self, tmp_path: Path) -> None:
        """SQLite 和 Parquet 均无数据时返回空 DataFrame。"""
        pytest.importorskip("duckdb")
        pytest.importorskip("pyarrow")
        db_path = self._write_sqlite(tmp_path, [])
        parquet_dir = tmp_path / "empty_parquet"
        parquet_dir.mkdir(parents=True, exist_ok=True)

        df = load_raw_bdib_for_date(
            "20260201", raw_bdib_db_path=db_path, parquet_dir=parquet_dir
        )

        assert df.empty
        assert list(df.columns) == ["equ_ticker", "order_as_of_date", "mkt_timestamp", "volume", "value", "close", "open"]


class TestComputeRouteMetricsForDate:
    """测试整日期路由指标计算。"""

    def test_empty_inputs_return_empty_frame(self) -> None:
        """空输入返回空 DataFrame，列顺序与 schema 一致。"""
        result = compute_route_metrics_for_date(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "20260421"
        )
        assert result.empty
        assert list(result.columns) == [
            "OrderId", "RouteId", "order_as_of_date", "Exchange", "Account",
            "equ_ticker", "Currency", "Side", "Amount", "RouteShares",
            "Type", "LimitPrice", "StopPrice", "Broker", "StrategyType",
            "algo", "TraderName",
            "fill_count", "fill", "fill_continuous", "fill_close",
            "par_rate", "par_rate_continuous", "par_rate_close",
            "p_avg", "p_avg_continuous",
            "pnl_vwap", "pnl_vwap_continuous",
            "RPM", "RPM_continuous",
            "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
            # 003-tca-core-benchmarks: Phase 0
            "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
            "opportunity_cost",
            # 003-tca-core-benchmarks: Phase 1
            "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
            "cost_stddev", "cost_p95", "cost_cvar",
            "order_duration_sec", "exec_rate_shares_per_min",
            "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
            "perm_impact_bps", "recovery_truncated",
        ]

    def test_computes_pwp_columns_for_single_route(self) -> None:
        """单路由有 fills 和 bars 时，PWP 列应正常计算。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        processed_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "equ_ticker": ["AAPL US Equity"],
            "FillId": ["F1"],
            "FillShares": [1000.0],
            "FillPrice": [100.0],
            "DateTimeOfFill": ["2026-04-21T09:30:00-04:00"],
            "is_closing_auction": [0],
        })

        raw_bdib = _make_bars(
            times=["09:30:00", "09:30:10", "09:30:20", "09:30:30", "09:30:40"],
            volumes=[5000.0] * 5,
            prices=[100.0] * 5,
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["fill_count"] == 1
        assert row["fill"] == pytest.approx(1000.0)
        assert row["p_avg"] == pytest.approx(100.0)
        assert row["par_rate"] == pytest.approx(1000.0 / 5000.0)
        for col in ["pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"]:
            assert row[col] is not None
            assert row[col] == pytest.approx(0.0)

    def test_normalizes_raw_fills_date_format(self) -> None:
        """raw_fills 的 order_as_of_date 为 YYYY-MM-DD 时仍能与 processed_fills 匹配。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["2026-04-21"],  # 与 processed_fills 格式不同
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        processed_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "equ_ticker": ["AAPL US Equity"],
            "FillId": ["F1"],
            "FillShares": [1000.0],
            "FillPrice": [100.0],
            "DateTimeOfFill": ["2026-04-21T09:30:00-04:00"],
            "is_closing_auction": [0],
        })

        raw_bdib = _make_bars(
            times=["09:30:00"],
            volumes=[5000.0],
            prices=[100.0],
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        assert result.iloc[0]["fill"] == pytest.approx(1000.0)

    def test_par_rate_close_uses_closing_auction_window_not_fill_time(self) -> None:
        """closing auction fill 时间戳晚于 bdib 末行时，par_rate_close 仍按交易所固定时段计算。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        # fill 发生在 US 收盘集合竞价时段（15:59:40），但晚于 bdib 末行（15:59:50）之前，
        # 用于验证 par_rate 终点被 bdib 末行限制，par_rate_close 按固定窗口计算。
        processed_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "equ_ticker": ["AAPL US Equity"],
            "FillId": ["F1"],
            "FillShares": [1000.0],
            "FillPrice": [100.0],
            # NY 15:59:40 -> local 15:59:40
            "DateTimeOfFill": ["2026-04-21T15:59:40-04:00"],
            "is_closing_auction": [1],
        })

        # US closing auction 窗口：15:59:00 - 16:00:00
        raw_bdib = _make_bars(
            times=["15:58:50", "15:59:00", "15:59:10", "15:59:20", "15:59:30", "15:59:40", "15:59:50"],
            volumes=[1000.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0],
            prices=[100.0] * 7,
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        row = result.iloc[0]
        # fill_close = 1000，closing auction 窗口成交量 = 3000
        assert row["par_rate_close"] == pytest.approx(1000.0 / 3000.0)
        # par_rate 分母终点取 min(15:59:40, 15:59:50) = 15:59:40，仅含该时刻 1 根 bar
        assert row["par_rate"] == pytest.approx(1000.0 / 500.0)

    def test_par_rate_capped_by_last_bdib_time(self) -> None:
        """fill 结束时间晚于 bdib 末行时，par_rate 分母终点不超过 bdib 末行。"""
        raw_fills = pd.DataFrame({
            "OrderId": ["O1"],
            "RouteId": ["R1"],
            "order_as_of_date": ["20260421"],
            "Exchange": ["US"],
            "Account": ["A1"],
            "Currency": ["USD"],
            "Side": ["Buy"],
            "Amount": [1000.0],
            "RouteShares": [1000.0],
            "Type": ["Limit"],
            "LimitPrice": [100.0],
            "StopPrice": [90.0],
            "Broker": ["BRK"],
            "StrategyType": ["TEST"],
            "TraderName": ["TRADER"],
        })

        # 两笔 fill：首笔在 bdib 范围内，末笔晚于 bdib 末行
        processed_fills = pd.DataFrame({
            "OrderId": ["O1", "O1"],
            "RouteId": ["R1", "R1"],
            "order_as_of_date": ["20260421", "20260421"],
            "equ_ticker": ["AAPL US Equity", "AAPL US Equity"],
            "FillId": ["F1", "F2"],
            "FillShares": [500.0, 500.0],
            "FillPrice": [100.0, 100.0],
            "DateTimeOfFill": ["2026-04-21T09:30:00-04:00", "2026-04-21T09:30:30-04:00"],
            "is_closing_auction": [0, 0],
        })

        raw_bdib = _make_bars(
            times=["09:30:00", "09:30:10"],
            volumes=[300.0, 700.0],
            prices=[100.0, 100.0],
        )

        result = compute_route_metrics_for_date(
            raw_fills, processed_fills, raw_bdib, "20260421"
        )

        assert len(result) == 1
        # par_rate 终点取 min(09:30:30, 09:30:10) = 09:30:10，分母 1000
        assert result.iloc[0]["par_rate"] == pytest.approx(1000.0 / 1000.0)


# ═══════════════════════════════════════════════════════════════════════════
# 003-tca-core-benchmarks: Phase 0 核心基准测试
# 理论依据: Perold (1988) "The Implementation Shortfall: Paper versus Reality";
# Kissell (2014) *The Science of Algorithmic Trading and Portfolio Management*
# ═══════════════════════════════════════════════════════════════════════════

def _make_raw_fills(
    side: str = "Buy", route_shares: float = 5000.0,
    amount: float = 5000.0, order_create: str | None = None,
) -> pd.DataFrame:
    """构造标准 raw_fills 输入。"""
    return pd.DataFrame({
        "OrderId": ["O1"],
        "RouteId": ["R1"],
        "order_as_of_date": ["20260421"],
        "Exchange": ["US"],
        "Account": ["A1"],
        "Currency": ["USD"],
        "Side": [side],
        "Amount": [amount],
        "RouteShares": [route_shares],
        "Type": ["Limit"],
        "LimitPrice": [100.0],
        "StopPrice": [90.0],
        "Broker": ["BRK"],
        "StrategyType": ["TEST"],
        "TraderName": ["TRADER"],
        "NyOrderCreateAsOfDateTime": [order_create],
    })


def _make_processed_fills(
    prices: list[float], shares: list[float],
    times: list[str], ticker: str = "AAPL US Equity",
) -> pd.DataFrame:
    """构造 processed_fills 输入（times 为本地 NY 时间 ISO 格式）。"""
    return pd.DataFrame({
        "OrderId": ["O1"] * len(prices),
        "RouteId": ["R1"] * len(prices),
        "order_as_of_date": ["20260421"] * len(prices),
        "equ_ticker": [ticker] * len(prices),
        "FillId": [f"F{i}" for i in range(1, len(prices) + 1)],
        "FillShares": shares,
        "FillPrice": prices,
        "DateTimeOfFill": times,
        "is_closing_auction": [0] * len(prices),
    })


def _make_daily_summary(close: float, next_close: float | None = None) -> pd.DataFrame:
    """构造 bdib_daily_summary 输入。"""
    rows = [
        {"equ_ticker": "AAPL US Equity", "trade_date": "20260421", "daily_close": close},
    ]
    if next_close is not None:
        rows.append({"equ_ticker": "AAPL US Equity", "trade_date": "20260422", "daily_close": next_close})
    return pd.DataFrame(rows)


class TestPhase0CoreBenchmarks:
    """Phase 0 核心基准：到达价 / 收盘价 / 机会成本。"""

    def _compute_with_flag(
        self, raw_fills, processed_fills, raw_bdib, daily_summary,
        enable: bool = True,
    ) -> pd.DataFrame:
        import DataPipeline.config as cfg
        from DataPipeline.processing import tca_route_metrics as trm

        # 保存原 flag 值
        orig = cfg.Config.TCA_CORE_BENCHMARKS_ENABLED
        cfg.Config.TCA_CORE_BENCHMARKS_ENABLED = enable
        try:
            return trm.compute_route_metrics_for_date(
                raw_fills, processed_fills, raw_bdib, "20260421",
                daily_summary_df=daily_summary,
            )
        finally:
            cfg.Config.TCA_CORE_BENCHMARKS_ENABLED = orig

    def test_arrival_price_before_first_fill(self) -> None:
        """到达价 = 首笔成交前最近 bar 的 close。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T10:15:30-04:00"],
        )
        # bars: 10:15:10 close=99.5, 10:15:20 close=100.5（首笔成交 10:15:30 前最近）
        raw_bdib = _make_bars(
            times=["10:15:00", "10:15:10", "10:15:20", "10:15:30"],
            volumes=[1000.0] * 4,
            prices=[99.0, 99.5, 100.5, 101.0],
        )
        daily_summary = _make_daily_summary(close=102.0)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        assert row["p_arrival"] == pytest.approx(100.5)

    def test_arrival_price_premarket_first_bar(self) -> None:
        """首笔成交在开盘前（无更早 bar）时，取当日首 bar close。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T09:25:00-04:00"],  # 开盘前
        )
        raw_bdib = _make_bars(
            times=["09:30:00", "09:30:10"],
            volumes=[1000.0] * 2,
            prices=[99.0, 99.5],
        )
        daily_summary = _make_daily_summary(close=102.0)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        assert result.iloc[0]["p_arrival"] == pytest.approx(99.0)

    def test_no_bdib_returns_none(self) -> None:
        """无 BDIB 数据时到达价/收盘价相关列全为 None。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        result = self._compute_with_flag(raw_fills, processed_fills, pd.DataFrame(), None)

        row = result.iloc[0]
        assert row["p_arrival"] is None
        assert row["p_close"] is None
        assert row["arrival_cost_bps"] is None
        assert row["close_cost_bps"] is None

    def test_buy_arrival_cost_bps(self) -> None:
        """买入：到达价偏离 = (P0/p_avg - 1) * side_sign * 10000。"""
        raw_fills = _make_raw_fills(side="Buy")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        # 首笔成交前最近 bar close = 10.00
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[1000.0] * 2,
            prices=[10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=10.20)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # (10.00/10.50 - 1) * 1 * 10000 = -476.19
        assert row["arrival_cost_bps"] == pytest.approx(-476.19, abs=0.01)

    def test_sell_arrival_cost_bps(self) -> None:
        """卖出：到达价偏离符号反转。"""
        raw_fills = _make_raw_fills(side="Sell")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[1000.0] * 2,
            prices=[11.00, 11.10],
        )
        daily_summary = _make_daily_summary(close=11.20)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # (11.00/10.50 - 1) * (-1) * 10000 = -476.19
        assert row["arrival_cost_bps"] == pytest.approx(-476.19, abs=0.01)

    def test_close_cost_bps(self) -> None:
        """收盘价偏离 = (Pn/p_avg - 1) * side_sign * 10000。"""
        raw_fills = _make_raw_fills(side="Buy")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[1000.0] * 2,
            prices=[10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=11.00)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # (11.00/10.50 - 1) * 1 * 10000 = 476.19
        assert row["close_cost_bps"] == pytest.approx(476.19, abs=0.01)

    def test_close_price_fallback_to_last_bar(self) -> None:
        """daily_summary 缺失时，p_close 回退到当日最后一个 bar 的 close。"""
        raw_fills = _make_raw_fills(side="Buy")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        # bars 最后 close = 11.00（S7 未跑，daily_summary 为空）
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00", "15:59:50", "16:00:00"],
            volumes=[1000.0] * 4,
            prices=[10.00, 10.10, 10.90, 11.00],
        )

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, None)

        row = result.iloc[0]
        # 回退：p_close = 最后 bar close = 11.00
        assert row["p_close"] == pytest.approx(11.00)
        # (11.00/10.50 - 1) * 1 * 10000 = 476.19
        assert row["close_cost_bps"] == pytest.approx(476.19, abs=0.01)

    def test_opportunity_cost_complete_execution(self) -> None:
        """完全成交时机会成本 = 0。"""
        raw_fills = _make_raw_fills(route_shares=5000.0)
        processed_fills = _make_processed_fills(
            prices=[100.0] * 5, shares=[1000.0] * 5,
            times=[f"2026-04-21T10:00:0{i}-04:00" for i in range(5)],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[100.0, 100.0],
        )
        daily_summary = _make_daily_summary(close=101.0)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        # 完全成交：RouteShares(5000) - fill(5000) = 0
        assert result.iloc[0]["opportunity_cost"] == pytest.approx(0.0)

    def test_opportunity_cost_partial_execution(self) -> None:
        """部分成交：机会成本 = (RouteShares - fill) * (Pn - P0) * side_sign。"""
        raw_fills = _make_raw_fills(route_shares=5000.0)
        processed_fills = _make_processed_fills(
            prices=[10.50] * 4, shares=[1000.0] * 4,
            times=[f"2026-04-21T10:00:0{i}-04:00" for i in range(4)],
        )
        # P0 = 10.00, Pn = 11.00
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=11.00)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary)

        # (5000 - 4000) * (11 - 10) * 1 = 1000
        assert result.iloc[0]["opportunity_cost"] == pytest.approx(1000.0)

    def test_flag_disabled_leaves_new_columns_none(self) -> None:
        """flag 关闭时，新列保持 None（不写 Phase 0 计算）。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[100.0, 100.0],
        )
        daily_summary = _make_daily_summary(close=101.0)

        result = self._compute_with_flag(raw_fills, processed_fills, raw_bdib, daily_summary, enable=False)

        row = result.iloc[0]
        assert row["p_arrival"] is None
        assert row["arrival_cost_bps"] is None
        assert row["close_cost_bps"] is None
        assert row["opportunity_cost"] is None


class TestPhase1RiskImpact:
    """Phase 1 Wagner IS / 风险 / 冲击分解。"""

    def _compute_with_flags(
        self, raw_fills, processed_fills, raw_bdib, daily_summary,
        core: bool = True, risk: bool = True,
    ) -> pd.DataFrame:
        import DataPipeline.config as cfg
        from DataPipeline.processing import tca_route_metrics as trm

        orig_core = cfg.Config.TCA_CORE_BENCHMARKS_ENABLED
        orig_risk = cfg.Config.TCA_RISK_IMPACT_ENABLED
        cfg.Config.TCA_CORE_BENCHMARKS_ENABLED = core
        cfg.Config.TCA_RISK_IMPACT_ENABLED = risk
        try:
            return trm.compute_route_metrics_for_date(
                raw_fills, processed_fills, raw_bdib, "20260421",
                daily_summary_df=daily_summary,
            )
        finally:
            cfg.Config.TCA_CORE_BENCHMARKS_ENABLED = orig_core
            cfg.Config.TCA_RISK_IMPACT_ENABLED = orig_risk

    def test_decision_price_premarket_open(self) -> None:
        """盘前订单决策价取当日首 bar open。"""
        raw_fills = _make_raw_fills(order_create="2026-04-21T09:00:00-04:00")
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        # NyOrderCreate=09:00（盘前），bars 从 09:30 开始
        raw_bdib = _make_bars(
            times=["09:30:00", "09:30:10"],
            volumes=[5000.0] * 2,
            prices=[99.0, 99.5],
        )
        daily_summary = _make_daily_summary(close=100.0)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        # 盘前订单：取首 bar open = 99.0
        assert result.iloc[0]["p_decision"] == pytest.approx(99.0)

    def test_decision_price_intraday_close(self) -> None:
        """盘中订单决策价取订单创建时间前最近 bar close。"""
        raw_fills = _make_raw_fills(order_create="2026-04-21T10:00:00-04:00")
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        # NyOrderCreate=09:00:00，bars 09:00 前最近 close = 09:59:50 的 99.8
        raw_bdib = _make_bars(
            times=["09:59:40", "09:59:50", "10:00:00"],
            volumes=[5000.0] * 3,
            prices=[99.5, 99.8, 100.0],
        )
        daily_summary = _make_daily_summary(close=100.5)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        assert result.iloc[0]["p_decision"] == pytest.approx(99.8)

    def test_wagner_is_decomposition(self) -> None:
        """Wagner IS = delay + trading + opportunity。"""
        # 买入订单，RouteShares=5000，成交 4000 @ 10.50
        raw_fills = _make_raw_fills(side="Buy", route_shares=5000.0, order_create="2026-04-21T09:00:00-04:00")
        processed_fills = _make_processed_fills(
            prices=[10.50] * 4, shares=[1000.0] * 4,
            times=[f"2026-04-21T10:00:0{i}-04:00" for i in range(4)],
        )
        # Pd = 10.00（订单创建前 bar close），P0 = 10.00，Pn = 11.00
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00", "10:00:10"],
            volumes=[5000.0] * 3,
            prices=[10.00, 10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=11.00)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # delay = 5000 * (10.00 - 10.00) * 1 = 0
        assert row["delay_cost"] == pytest.approx(0.0, abs=0.01)
        # trading = 4000 * (10.50 - 10.00) * 1 = 2000
        assert row["trading_cost"] == pytest.approx(2000.0, abs=0.01)
        # opportunity = (5000-4000) * (11.00 - 10.00) * 1 = 1000
        assert row["opportunity_cost"] == pytest.approx(1000.0, abs=0.01)
        # wagner_is = 0 + 2000 + 1000 = 3000
        assert row["wagner_is"] == pytest.approx(3000.0, abs=0.01)

    def test_wagner_is_complete_execution(self) -> None:
        """完全成交时 Wagner IS = delay + trading（opportunity=0）。"""
        raw_fills = _make_raw_fills(side="Buy", route_shares=5000.0, order_create="2026-04-21T09:00:00-04:00")
        processed_fills = _make_processed_fills(
            prices=[10.50] * 5, shares=[1000.0] * 5,
            times=[f"2026-04-21T10:00:0{i}-04:00" for i in range(5)],
        )
        # Pd = 10.00, P0 = 10.00
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00", "10:00:10"],
            volumes=[5000.0] * 3,
            prices=[10.00, 10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=11.00)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        assert row["opportunity_cost"] == pytest.approx(0.0)
        assert row["wagner_is"] == pytest.approx(2500.0, abs=0.01)  # 0 + 5000*(10.5-10)

    def test_cost_stddev_p95_cvar(self) -> None:
        """风险维度：成本标准差 / P95 / CVaR 计算。"""
        raw_fills = _make_raw_fills()
        # 5 笔不同价格成交 → 计算 bps 分布
        prices = [10.0, 10.1, 10.2, 10.3, 10.4]
        shares = [1000.0] * 5
        processed_fills = _make_processed_fills(
            prices=prices, shares=shares,
            times=[f"2026-04-21T10:00:0{i}-04:00" for i in range(5)],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[10.0, 10.0],
        )
        daily_summary = _make_daily_summary(close=10.5)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        assert row["cost_stddev"] is not None and row["cost_stddev"] > 0
        assert row["cost_p95"] is not None
        assert row["cost_cvar"] is not None

    def test_order_duration_and_exec_rate(self) -> None:
        """订单历时与执行速率。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[10.0, 10.0], shares=[5000.0, 5000.0],
            times=["2026-04-21T10:00:00-04:00", "2026-04-21T10:30:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[10.0, 10.0],
        )
        daily_summary = _make_daily_summary(close=10.5)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # 10:00:00 -> 10:30:00 = 1800 秒
        assert row["order_duration_sec"] == pytest.approx(1800.0)
        # 10000 shares / 30 min = 333.33/min
        assert row["exec_rate_shares_per_min"] == pytest.approx(333.33, abs=0.1)

    def test_temp_impact_normal_recovery(self) -> None:
        """暂时冲击：执行结束后 5min 恢复价（全部窗口在数据范围内）。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T14:00:00-04:00"],
        )
        # 末笔成交 14:00:00，5min 恢复价 = 14:05:00 close；bars 延伸到 14:30 覆盖全部窗口
        raw_bdib = _make_bars(
            times=["13:59:50", "14:00:00", "14:05:00", "14:10:00", "14:30:00", "14:30:10"],
            volumes=[5000.0] * 6,
            prices=[100.0, 100.0, 100.5, 100.6, 100.7, 100.8],
        )
        daily_summary = _make_daily_summary(close=101.0)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # (100.5/100 - 1) * 1 * 10000 = 50 bps
        assert row["temp_impact_5min_bps"] == pytest.approx(50.0, abs=0.1)
        # 30min 恢复价 = 14:30:00 close = 100.7
        assert row["temp_impact_30min_bps"] == pytest.approx(70.0, abs=0.1)
        assert row["recovery_truncated"] == 0

    def test_temp_impact_truncated(self) -> None:
        """恢复窗口越界时标记 truncated 并用次日收盘价作跨日恢复价格。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T15:55:00-04:00"],
        )
        # 末笔成交 15:55:00，30min 后 = 16:25 > 当日最后 bar 16:00:00
        raw_bdib = _make_bars(
            times=["15:54:50", "15:55:00", "15:59:50", "16:00:00"],
            volumes=[5000.0] * 4,
            prices=[100.0, 100.0, 100.5, 100.7],
        )
        # 次日收盘 100.9：越界窗口（10min/30min）的跨日恢复价格
        daily_summary = _make_daily_summary(close=101.0, next_close=100.9)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # 5min 窗口：16:00:00 在当日范围内 → 当日 close=100.7 → 70 bps
        assert row["temp_impact_5min_bps"] == pytest.approx(70.0, abs=0.1)
        # 10min/30min 越界 → 次日收盘 100.9 → (100.9/100 - 1) * 10000 = 90 bps
        assert row["temp_impact_10min_bps"] == pytest.approx(90.0, abs=0.1)
        assert row["temp_impact_30min_bps"] == pytest.approx(90.0, abs=0.1)
        assert row["recovery_truncated"] == 1

    def test_temp_impact_truncated_no_next_close(self) -> None:
        """越界且无次日收盘数据时，该窗口暂时冲击保持 None，truncated=1。"""
        raw_fills = _make_raw_fills()
        processed_fills = _make_processed_fills(
            prices=[100.0], shares=[1000.0],
            times=["2026-04-21T15:55:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["15:54:50", "15:55:00", "15:59:50", "16:00:00"],
            volumes=[5000.0] * 4,
            prices=[100.0, 100.0, 100.5, 100.7],
        )
        # 无次日行：跨日恢复价格不可得
        daily_summary = _make_daily_summary(close=101.0)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        assert row["temp_impact_5min_bps"] == pytest.approx(70.0, abs=0.1)
        assert row["temp_impact_10min_bps"] is None
        assert row["temp_impact_30min_bps"] is None
        assert row["recovery_truncated"] == 1

    def test_perm_impact_next_day_close(self) -> None:
        """永久冲击：次日收盘价 vs 到达价（跨日）。"""
        raw_fills = _make_raw_fills(side="Buy")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[10.00, 10.10],
        )
        # 次日收盘 = 10.80，到达价 P0 = 10.00
        daily_summary = _make_daily_summary(close=10.50, next_close=10.80)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        row = result.iloc[0]
        # (10.80/10.00 - 1) * 1 * 10000 = 800 bps
        assert row["perm_impact_bps"] == pytest.approx(800.0, abs=0.1)

    def test_perm_impact_missing_next_day(self) -> None:
        """无次日收盘数据时 perm_impact 保持 None。"""
        raw_fills = _make_raw_fills(side="Buy")
        processed_fills = _make_processed_fills(
            prices=[10.50], shares=[1000.0],
            times=["2026-04-21T10:00:00-04:00"],
        )
        raw_bdib = _make_bars(
            times=["09:59:50", "10:00:00"],
            volumes=[5000.0] * 2,
            prices=[10.00, 10.10],
        )
        daily_summary = _make_daily_summary(close=10.50, next_close=None)

        result = self._compute_with_flags(raw_fills, processed_fills, raw_bdib, daily_summary)

        assert result.iloc[0]["perm_impact_bps"] is None


