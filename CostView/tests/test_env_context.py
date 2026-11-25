"""026 阶段二：执行环境变量精确化（真实分层与三级降级链）回归测试。

覆盖 plan §4.5 的检验项：真值抽验 / 双形态时间戳 / 分桶边界 /
真实路径不引用成本量（消除循环论证）/ 三维度独立降级 / 可得率披露。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from CostView.src.monitoring import env_context, report_spec
from CostView.src.monitoring.env_context import (
    RouteEnvContext,
    build_route_env_context,
    env_coverage,
)
from CostView.src.tca_utils import (
    aggregate_cohorts,
    cohort_key_and_label,
    time_bucket_detail,
)
from data_access.storage.connection import ConnectionManager


def _route(**overrides: Any) -> SimpleNamespace:
    """最小路由替身：分桶函数只按属性访问，不依赖具体类型。"""
    base: dict[str, Any] = {
        "OrderId": "O1", "RouteId": "R1", "order_as_of_date": "20260418",
        "Broker": "BROKERA", "algo": "VWAP", "equ_ticker": "AAPL US Equity",
        "Exchange": "US", "RouteShares": None,
        "par_rate": None, "pnl_vwap": None, "fill": None,
        # aggregate_cohorts 的聚合路径还会读取以下列（真实类型上恒存在）
        "par_rate_continuous": None, "pnl_vwap_continuous": None, "RPM": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def env_dbs(tmp_path: Path) -> ConnectionManager:
    """构造 fill_bdib（时序）+ raw_bdib（daily summary）双库。

    ``fill_bdib`` 用真实数据的形态（``HH:MM:SS`` 纯时间）；``bdib_daily_summary``
    只覆盖 AAPL —— 用于验证「维度独立降级」。
    """
    fill_path = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(fill_path))
    conn.execute(
        "CREATE TABLE fill_bdib (OrderId TEXT, RouteId TEXT, "
        "order_as_of_date TEXT, mkt_timestamp TEXT)"
    )
    conn.executemany(
        "INSERT INTO fill_bdib VALUES (?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "11:20:20"),
            ("O1", "R1", "20260418", "09:35:00"),
            ("O2", "R1", "20260418", "14:45:10"),
        ],
    )
    conn.commit()
    conn.close()

    raw_path = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(raw_path))
    conn.execute(
        "CREATE TABLE bdib_daily_summary (equ_ticker TEXT, trade_date TEXT, "
        "adv_20d REAL, daily_volatility REAL)"
    )
    conn.executemany(
        "INSERT INTO bdib_daily_summary VALUES (?, ?, ?, ?)",
        [
            # 028：夹具值改为真实的**年化百分比**量级（26.075 是实测中位数；
            # 旧值 2.0 会被归一化判为「年化小数」→ ×100，那正是 028 要修的错配）
            ("AAPL US Equity", "20260418", 1000000.0, 30.0),
            # 028：一行**年化小数**写法（上游 202603/202604 区间的形态），供归一化用例
            ("ORCL US Equity", "20260418", 2000000.0, 0.8),
        ],
    )
    conn.commit()
    conn.close()

    # 211（DL-19）：时段控制变量改取 processed_fills.route_as_of_time（决策时点），
    # 不再取 fill_bdib 的首笔成交时刻。这里两者故意不同，便于断言取的是后者。
    proc_path = tmp_path / "processed_fills.db"
    conn = sqlite3.connect(str(proc_path))
    conn.execute(
        "CREATE TABLE processed_fills (OrderId TEXT, RouteId TEXT, "
        "order_as_of_date TEXT, route_as_of_time TEXT)"
    )
    conn.executemany(
        "INSERT INTO processed_fills VALUES (?, ?, ?, ?)",
        [
            ("O1", "R1", "20260418", "10:05:00"),
            ("O1", "R1", "20260418", "10:06:00"),
            ("O2", "R1", "20260418", "14:40:00"),
        ],
    )
    conn.commit()
    conn.close()

    return ConnectionManager(path_overrides={
        "fill_bdib": fill_path,
        "raw_bdib": raw_path,
        "processed_fills": proc_path,
    })


class TestNormalizeStartTime:
    """Q2-1 结论的回归护栏：真实数据是纯时间，但测试夹具形态也必须兼容。"""

    def test_pure_time_unchanged(self) -> None:
        assert env_context.normalize_start_time("11:20:20") == "11:20:20"

    def test_full_timestamp_takes_tail(self) -> None:
        """夹具形态 ``YYYYMMDD HH:MM:SS`` → 取末 8 位（否则 bucket 会取到年份前两位）。"""
        assert env_context.normalize_start_time("20260418 10:10:00") == "10:10:00"

    def test_empty_and_none(self) -> None:
        assert env_context.normalize_start_time("") is None
        assert env_context.normalize_start_time(None) is None


class TestVolatilityScaleSuspicion:
    """028b：疑似小数量纲**只检测不修改**。

    上游已确认权威定义（直取 Bloomberg `VOLATILITY_30D`，百分比单位）并回填修复
    36,372 行 + 加批次级守卫；本侧复核后 `<3` 仅剩 112 行，且经核对为**真实低波动标的**。
    继续 ×100 会把它们误放大 100 倍，故改为只登记不修改。
    """

    def test_decimal_value_is_flagged(self) -> None:
        assert env_context.volatility_scale_suspect(0.8) is True
        assert env_context.volatility_scale_suspect(2.0) is True

    def test_normal_value_is_not_flagged(self) -> None:
        assert env_context.volatility_scale_suspect(26.075) is False
        assert env_context.volatility_scale_suspect(80.0) is False

    def test_real_low_volatility_is_flagged_not_corrected(self) -> None:
        """真实低波动标的（实测 `K US Equity` 1.16 / `ITRK LN Equity` 1.43）会被登记。

        这是 028b 的核心取舍：**宁可多登记也不误改** —— 上游修复后这些是真实值。
        """
        assert env_context.volatility_scale_suspect(1.16) is True
        assert env_context.volatility_scale_suspect(1.43) is True

    def test_none_and_non_finite(self) -> None:
        assert env_context.volatility_scale_suspect(None) is False
        assert env_context.volatility_scale_suspect(float("nan")) is False

    def test_scale_constants_match_spec(self) -> None:
        from CostView.src.monitoring import report_spec

        assert env_context.VOLATILITY_SCALE_CUT == (
            report_spec.REPORT_SPEC["volatility_scale_cut"]
        )
        assert env_context.VOLATILITY_UNIT == report_spec.REPORT_SPEC["volatility_unit"]

    def test_suspect_flag_disclosed_without_modifying_value(
        self, env_dbs: ConnectionManager,
    ) -> None:
        """登记数可见，且 `daily_volatility` **原值保持不变**（0.8 不会被放大为 80）。"""
        routes = [
            _route(OrderId="O1", RouteId="R1", RouteShares=5000.0),                     # AAPL 30.0
            _route(OrderId="O2", RouteId="R1", RouteShares=5000.0,
                   equ_ticker="ORCL US Equity"),                                # ORCL 0.8
        ]
        env_by_route = build_route_env_context(env_dbs, routes, "20260418", "20260418")

        aapl = env_by_route[("O1", "R1", "20260418")]
        orcl = env_by_route[("O2", "R1", "20260418")]

        assert aapl.daily_volatility == pytest.approx(30.0)
        assert aapl.volatility_scale_suspect is False
        assert orcl.daily_volatility == pytest.approx(0.8)      # 原值，未放大
        assert orcl.volatility_scale_suspect is True

        coverage = env_coverage(routes, env_by_route)
        assert coverage["volatility_scale_suspect"] == 1


class TestRealEnvCohorts:
    """真实环境字段优先 —— 三级降级链的 L1 与 L3 两侧。"""

    def test_time_of_day_uses_session_relative_bucket(self) -> None:
        """211：决策时点时刻 → DL-03 会话相对桶（US：open_30m/midday/close_30m）。"""
        route = _route()
        assert cohort_key_and_label(
            route, "time_of_day", RouteEnvContext(start_time="09:45:00"),
        )[0] == "open_30m"
        assert cohort_key_and_label(
            route, "time_of_day", RouteEnvContext(start_time="12:30:00"),
        )[0] == "midday"
        assert cohort_key_and_label(
            route, "time_of_day", RouteEnvContext(start_time="15:45:00"),
        )[0] == "close_30m"

    def test_time_of_day_falls_back_to_unknown(self) -> None:
        """无 start_time 时 unknown（不臆造桶、不回退首笔成交时刻）。"""
        route = _route()
        assert cohort_key_and_label(route, "time_of_day") == ("unknown", "Unknown")
        assert cohort_key_and_label(
            route, "time_of_day", RouteEnvContext(),
        ) == ("unknown", "Unknown")

    def test_time_of_day_boundaries(self) -> None:
        """US 会话桶边界（S9 口径）：09:59 open_30m / 10:00 morning / 12:00 midday /
        14:00 afternoon / 15:30 close_30m。"""
        route = _route()
        cases = [
            ("09:59:00", "open_30m"), ("10:00:00", "morning"),
            ("11:59:00", "morning"), ("12:00:00", "midday"),
            ("14:29:00", "afternoon"), ("15:29:00", "afternoon"),
            ("15:30:00", "close_30m"),
        ]
        for start_time, expected in cases:
            assert cohort_key_and_label(
                route, "time_of_day", RouteEnvContext(start_time=start_time),
            )[0] == expected

    def test_time_of_day_lunch_break_for_jp(self) -> None:
        route = _route(Exchange="JP")
        assert cohort_key_and_label(
            route, "time_of_day", RouteEnvContext(start_time="11:45:00"),
        )[0] == "lunch_break"

    def test_missing_adv20_is_unknown_not_par_rate_proxy(self) -> None:
        """211：par_rate（成交/ADV，后验）兜底已删除；缺失即 unknown。"""
        route = _route(par_rate=0.20)
        assert cohort_key_and_label(route, "liquidity_adv20")[0] == "unknown"
        assert cohort_key_and_label(
            route, "liquidity_adv20", RouteEnvContext(adv20_ratio=0.002),
        )[0] == "low"

    def test_missing_volatility_is_unknown_not_pnl_proxy(self) -> None:
        """211：|pnl_vwap|（被解释变量）兜底已删除；缺失即 unknown。"""
        route = _route(pnl_vwap=-50.0)
        assert cohort_key_and_label(route, "volatility")[0] == "unknown"
        assert cohort_key_and_label(
            route, "volatility", RouteEnvContext(daily_volatility=0.8),
        )[0] == "calm"

    def test_time_bucket_source_is_explicit(self) -> None:
        """211：S9 五桶 / session-relative 三段 / unknown 三种来源可辨。"""
        assert time_bucket_detail(
            _route(Exchange="US"), RouteEnvContext(start_time="10:00:00"),
        )[2] == "s9"
        assert time_bucket_detail(
            _route(Exchange="KS"), RouteEnvContext(start_time="10:00:00"),
        )[2] == "session-relative"
        assert time_bucket_detail(
            _route(Exchange="ZZ"), RouteEnvContext(start_time="10:00:00"),
        )[2] == "unknown"

    def test_non_env_cohort_ignores_env(self) -> None:
        """非环境 cohort 不受 env 影响。"""
        route = _route(Broker="B1", algo="A1")
        env = RouteEnvContext(start_time="09:15:00", adv20_ratio=0.9)
        assert cohort_key_and_label(route, "broker", env) == ("B1", "B1")
        assert cohort_key_and_label(route, "strategy", env) == ("A1", "A1")
        assert cohort_key_and_label(route, "broker_strategy", env)[0] == "B1|A1"
        assert cohort_key_and_label(route, "asset_class", env)[0] == "equity"


class TestBuildRouteEnvContext:
    """取数与应用层 join（真值抽验）。"""

    def test_joins_route_as_of_time_and_daily_env(self, env_dbs: ConnectionManager) -> None:
        """211：时段取 route_as_of_time（10:05），不取首笔成交时刻（09:35）。"""
        routes = [
            _route(OrderId="O1", RouteId="R1", RouteShares=5000.0),
            _route(OrderId="O2", RouteId="R1", RouteShares=None),
        ]
        result = build_route_env_context(env_dbs, routes, "20260418", "20260418")

        first = result[("O1", "R1", "20260418")]
        assert first.start_time == "10:05:00"          # 决策时点，不是首笔成交
        assert first.adv20_ratio == pytest.approx(0.005)
        assert first.daily_volatility == 30.0
        assert first.volatility_scale_suspect is False     # 正常年化百分比不登记

        second = result[("O2", "R1", "20260418")]
        assert second.start_time == "14:40:00"
        assert second.adv20_ratio is None               # RouteShares 缺失 → 不可计算，不兜底

    def test_unknown_ticker_degrades_per_dimension(
        self, env_dbs: ConnectionManager,
    ) -> None:
        """维度独立降级：缺 daily summary 不影响时段维度。"""
        routes = [_route(equ_ticker="MSFT US Equity", RouteShares=1000.0)]
        env = build_route_env_context(
            env_dbs, routes, "20260418", "20260418",
        )[("O1", "R1", "20260418")]

        assert env.adv20_ratio is None
        assert env.daily_volatility is None
        assert env.start_time == "10:05:00"

    def test_missing_sources_return_empty(self, tmp_path: Path) -> None:
        """两来源库缺失 → 空映射（整体降级，不抛错）。"""
        mgr = ConnectionManager(path_overrides={
            "fill_bdib": tmp_path / "absent_fill.db",
            "raw_bdib": tmp_path / "absent_raw.db",
            "processed_fills": tmp_path / "absent_proc.db",
        })
        # 每条路由仍有条目，但三维度均为 None —— 不可得是**可见事实**，不是「缺条目」
        env = build_route_env_context(
            mgr, [_route()], "20260418", "20260418",
        )[("O1", "R1", "20260418")]
        assert env.start_time is None
        assert env.adv20_ratio is None
        assert env.daily_volatility is None


class TestRouteColumnsPreferred:
    """CCP-20261112：路由行两列优先，旧 schema / NULL 回退 daily join。"""

    def test_route_columns_override_daily_join(
        self, env_dbs: ConnectionManager,
    ) -> None:
        route = _route(
            OrderId="O1", RouteId="R1", RouteShares=5000.0,
            # 故意与 bdib_daily_summary 的 1,000,000 / 30.0 不同
            adv_20d=2_000_000.0, daily_volatility=12.0,
        )
        env = build_route_env_context(
            env_dbs, [route], "20260418", "20260418",
        )[("O1", "R1", "20260418")]

        assert env.adv20_ratio == pytest.approx(5000.0 / 2_000_000.0)
        assert env.daily_volatility == pytest.approx(12.0)

    def test_adv20_ratio_uses_route_shares_not_fill(
        self, env_dbs: ConnectionManager,
    ) -> None:
        """211：规模用 RouteShares（1% → mid），不能用 fill（10% → high）。"""
        route = _route(RouteShares=100.0, fill=1000.0, adv_20d=10000.0)
        env = build_route_env_context(
            env_dbs, [route], "20260418", "20260418",
        )[("O1", "R1", "20260418")]

        assert env.adv20_ratio == pytest.approx(0.01)
        assert cohort_key_and_label(route, "liquidity_adv20", env)[0] == "mid"

    def test_null_columns_fall_back_to_daily_join(
        self, env_dbs: ConnectionManager,
    ) -> None:
        route = _route(
            OrderId="O1", RouteId="R1", RouteShares=5000.0,
            adv_20d=None, daily_volatility=None,
        )
        env = build_route_env_context(
            env_dbs, [route], "20260418", "20260418",
        )[("O1", "R1", "20260418")]

        assert env.adv20_ratio == pytest.approx(5000.0 / 1_000_000.0)
        assert env.daily_volatility == pytest.approx(30.0)

    def test_partial_null_falls_back_per_dimension(
        self, env_dbs: ConnectionManager,
    ) -> None:
        route = _route(
            OrderId="O1", RouteId="R1", RouteShares=5000.0,
            adv_20d=2_000_000.0, daily_volatility=None,
        )
        env = build_route_env_context(
            env_dbs, [route], "20260418", "20260418",
        )[("O1", "R1", "20260418")]

        assert env.adv20_ratio == pytest.approx(5000.0 / 2_000_000.0)
        assert env.daily_volatility == pytest.approx(30.0)


class TestAggregateCohortsWithEnv:
    """聚合层接线：真实 env 改变分层结果，可得率可披露。"""

    def test_env_split_changes_cohorts(self, env_dbs: ConnectionManager) -> None:
        routes = [
            _route(OrderId="O1", RouteId="R1", RouteShares=5000.0,
                   pnl_vwap=-1.0, par_rate=0.01),
        ]
        env_by_route = build_route_env_context(
            env_dbs, routes, "20260418", "20260418",
        )

        real = aggregate_cohorts(routes, "time_of_day", 1, env_by_route)
        proxy = aggregate_cohorts(routes, "time_of_day", 1)

        assert [c.cohort_label for c in real] == ["Morning"]
        assert [c.cohort_label for c in proxy] == ["Unknown"]

    def test_env_coverage_disclosed(self, env_dbs: ConnectionManager) -> None:
        routes = [
            _route(OrderId="O1", RouteId="R1", RouteShares=5000.0),
            _route(OrderId="O2", RouteId="R1",
                   equ_ticker="MSFT US Equity", RouteShares=1000.0),
        ]
        env_by_route = build_route_env_context(
            env_dbs, routes, "20260418", "20260418",
        )
        coverage = env_coverage(routes, env_by_route)

        assert coverage["total_routes"] == 2
        # 两条路由都有 route_as_of_time（processed_fills 覆盖）
        assert coverage["usable"]["time_of_day"] == 2
        assert coverage["time_bucket_source"]["s9"] == 2
        # 仅 AAPL 有 daily summary，MSFT 无 adv_20d
        assert coverage["usable"]["liquidity_adv20"] == 1
        assert coverage["usable"]["volatility"] == 1
        assert coverage["unknown"]["liquidity_adv20"] == 1
        assert coverage["pct"]["liquidity_adv20"] == 50.0


class TestEnvSpecBinding:
    """口径声明与实现绑定（防「声明-实现」漂移，对齐既有 report_spec 护栏模式）。"""

    def test_spec_covers_all_env_dimensions(self) -> None:
        spec = report_spec.REPORT_SPEC
        assert set(spec["env_cohort_sources"]) == set(env_context.ENV_DIMENSIONS)
        assert set(spec["env_cohort_fallbacks"]) == set(env_context.ENV_DIMENSIONS)

    def test_declared_fallbacks_match_implementation(self) -> None:
        """声明的降级口径与实现行为一致（time_of_day 降级为 unknown 桶）。"""
        fallbacks = report_spec.REPORT_SPEC["env_cohort_fallbacks"]
        route = _route(pnl_vwap=-50.0, par_rate=0.20)

        assert fallbacks["time_of_day"] == "unknown"
        assert cohort_key_and_label(route, "time_of_day")[0] == fallbacks["time_of_day"]
        # 211：两条后验兜底已删除 —— 缺失一律 unknown
        assert cohort_key_and_label(route, "liquidity_adv20")[0] == "unknown"
        assert cohort_key_and_label(route, "volatility")[0] == "unknown"
        assert "scorecard" in report_spec.REPORT_SPEC["env_coverage_disclosure"]


class TestIntentFamilyCohort:
    """212（DL-19）：意图 × 算法族分组；意图可选，不做反推。"""

    def test_unknown_intent_groups_by_family(self) -> None:
        route = _route(Broker="EQ-BARCLAY", algo="VWAP")
        assert cohort_key_and_label(route, "intent_family") == ("UNKNOWN|vwap", "VWAP")

    def test_optional_intent_used_without_inference(self) -> None:
        route = _route(
            Broker="EQ-BARCLAY", algo="VWAP",
            intent="MIX", intent_source="emsx-export",
        )
        assert cohort_key_and_label(route, "intent_family") == ("MIX|vwap", "MIX | VWAP")

    def test_mix_splits_by_family(self) -> None:
        vwap = _route(algo="VWAP", intent="MIX", intent_source="emsx-export")
        close = _route(algo="MOC", intent="MIX", intent_source="emsx-export")
        assert cohort_key_and_label(vwap, "intent_family")[0] == "MIX|vwap"
        assert cohort_key_and_label(close, "intent_family")[0] == "MIX|auction_close"

    def test_special_single(self) -> None:
        route = _route(algo="VWAP", intent="SPECIAL", intent_source="emsx-export")
        assert cohort_key_and_label(route, "intent_family")[0] == "SPECIAL|vwap"

    def test_default_scorecard_cohort_and_payload(self) -> None:
        from platform_data.contracts import ScorecardFilters

        assert ScorecardFilters().cohort == "intent_family"
        routes = [
            _route(
                intent="VWAP", intent_source="emsx-export",
                RouteShares=100.0, pnl_vwap=-1.0, par_rate=0.01,
            )
        ]
        cohorts = aggregate_cohorts(routes, "intent_family", 1)
        assert cohorts[0].intent_source == "emsx-export"
        assert cohorts[0].algo_family == "vwap"
