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
    """构造 raw_bdib bars DataFrame。"""
    return pd.DataFrame({
        "equ_ticker": ["AAPL US Equity"] * len(times),
        "order_as_of_date": ["20260421"] * len(times),
        "mkt_timestamp": times,
        "volume": volumes,
        "value": [v * p for v, p in zip(volumes, prices)],
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
        """构造临时 SQLite raw_bdib 文件。"""
        db_path = tmp_path / "raw_bdib.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE raw_bdib ("
            "equ_ticker TEXT, order_as_of_date TEXT, mkt_timestamp TEXT, "
            "volume REAL, value REAL)"
        )
        if data:
            rows = [
                (row["equ_ticker"], date_str, row["mkt_timestamp"], row["volume"], row["value"])
                for row in data
            ]
            conn.executemany("INSERT INTO raw_bdib VALUES (?, ?, ?, ?, ?)", rows)
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
        assert list(df.columns) == ["equ_ticker", "order_as_of_date", "mkt_timestamp", "volume", "value"]


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


