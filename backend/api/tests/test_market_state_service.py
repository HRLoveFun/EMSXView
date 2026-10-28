"""057 DL-15 — 盘中市场状态服务单测。

覆盖：订阅字段随开关变化、行情解析（缺失/NaN 跳过）、快照构建
（价差 bps、相对基线差值、版本化阈值告警）、基线查询失败降级。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    MARKET_STATE_SCHEMA_VERSION,
    MarketBaseline,
    MarketStateThresholds,
)
from services.bloomberg import enrichment as mde  # noqa: E402
from services import market_state_service as mss  # noqa: E402


def test_intraday_state_enabled_by_default():
    """D-6 定稿（2026-10-27）：未显式关闭时实时列默认开启。

    用子进程隔离读取：config 在导入时实例化 Settings 并校验 JWT_SECRET，
    避免影响本进程的全局 settings 与其它测试。
    """
    import os
    import subprocess

    if os.getenv("EMSXVIEW_INTRADAY_STATE_ENABLED") is not None:
        pytest.skip("env override present")
    env = {k: v for k, v in os.environ.items() if k != "EMSXVIEW_INTRADAY_STATE_ENABLED"}
    env.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings; print(settings.EMSXVIEW_INTRADAY_STATE_ENABLED)",
        ],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "True", result.stderr


class _FakeMsg:
    def __init__(self, fields: dict):
        self._fields = fields

    def hasElement(self, name: str) -> bool:
        return name in self._fields

    def getElementAsFloat(self, name: str) -> float:
        value = self._fields[name]
        if value is None:
            raise ValueError("no data")
        return float(value)

    def getElementAsInteger(self, name: str) -> int:
        value = self._fields[name]
        if value is None:
            raise ValueError("no data")
        return int(value)


def _baseline(ticker: str, spread_proxy_bps: float | None) -> MarketBaseline:
    return MarketBaseline(
        equ_ticker=ticker,
        as_of="20261024",
        log_volume_z=None,
        vol_percentile=None,
        intraday_vol_percentile=None,
        overnight_gap_sigma=None,
        auction_open_pct=None,
        auction_close_pct=None,
        adv5_adv60_ratio=None,
        spread_proxy_bps=spread_proxy_bps,
        n_days=60,
    )


# ── 订阅字段 ────────────────────────────────────────────────────────────────


def test_mktdata_fields_disabled_matches_existing():
    """开关关闭：字段与现状一致（不引入额度变化）。"""
    assert mde.mktdata_fields(False) == ["CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP", "PX_ROUND_LOT_SIZE"]


def test_mktdata_fields_enabled_adds_intraday_fields():
    fields = mde.mktdata_fields(True)
    for field in ("BID", "ASK", "LAST_PRICE", "VOLUME", "HIGH", "LOW", "PREV_CLOSE_VALUE_REALTIME"):
        assert field in fields
    assert fields[:4] == ["CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP", "PX_ROUND_LOT_SIZE"]


# ── 行情解析 ────────────────────────────────────────────────────────────────


def test_parse_intraday_quote_extracts_present_fields():
    quote = mde.parse_intraday_quote(_FakeMsg({"BID": 100.0, "ASK": 100.2, "VOLUME": 12345}))
    assert quote["BID"] == 100.0
    assert quote["ASK"] == 100.2
    assert quote["VOLUME"] == 12345
    assert "LAST_PRICE" not in quote


def test_parse_intraday_quote_skips_missing_and_nan():
    quote = mde.parse_intraday_quote(_FakeMsg({"BID": 100.0, "ASK": None, "HIGH": float("nan")}))
    assert quote == {"BID": 100.0}


def test_parse_intraday_quote_keeps_prev_close_for_fallback():
    """前收是实时涨跌幅的回落来源（本机终端不推送 CHG_PCT_1D）。"""
    quote = mde.parse_intraday_quote(
        _FakeMsg({"LAST_PRICE": 101.0, "PREV_CLOSE_VALUE_REALTIME": 100.0})
    )
    assert quote == {"LAST_PRICE": 101.0, "PREV_CLOSE_VALUE_REALTIME": 100.0}


# ── 快照构建 ────────────────────────────────────────────────────────────────


def _fake_bloomberg(quotes: dict):
    return SimpleNamespace(_intraday_quotes=quotes)


@pytest.mark.asyncio
async def test_snapshot_empty_without_quotes():
    snapshot = mss.build_market_state_snapshot(_fake_bloomberg({}))
    assert snapshot.enabled is True
    assert snapshot.tickers == ()
    assert snapshot.thresholds.version == MarketStateThresholds().version


@pytest.mark.asyncio
async def test_snapshot_computes_spread_and_flags_vs_baseline():
    quotes = {
        "AAPL US Equity": {"BID": 100.0, "ASK": 100.5, "LAST_PRICE": 100.2, "VOLUME": 1_000},
        "TSLA US Equity": {"BID": 200.0, "ASK": 200.01, "LAST_PRICE": 200.0},
    }
    baselines = {
        "AAPL US Equity": _baseline("AAPL US Equity", spread_proxy_bps=3.0),
        "TSLA US Equity": _baseline("TSLA US Equity", spread_proxy_bps=6.0),
    }
    snapshot = mss.build_market_state_snapshot(
        _fake_bloomberg(quotes), baseline_lookup=lambda tickers: baselines
    )

    by_ticker = {state.equ_ticker: state for state in snapshot.tickers}
    aapl = by_ticker["AAPL US Equity"]
    # AAPL: (100.5-100)/100.25*10000 ≈ 49.88 bps，相对基线 3.0 → +46.88 → 告警
    assert aapl.spread_bps == pytest.approx(49.88, abs=0.05)
    assert aapl.spread_vs_baseline_bps == pytest.approx(46.88, abs=0.05)
    assert [flag.code for flag in aapl.flags] == ["SPREAD_VS_BASELINE_WIDE"]
    assert "thresholds-v1" in aapl.flags[0].evidence

    tsla = by_ticker["TSLA US Equity"]
    # TSLA: 0.5 bps，相对基线 6.0 → -5.5（收紧，不告警）
    assert tsla.spread_vs_baseline_bps == pytest.approx(-5.5, abs=0.05)
    assert tsla.flags == ()


@pytest.mark.asyncio
async def test_snapshot_without_baseline_lookup_skips_comparison():
    quotes = {"AAPL US Equity": {"BID": 100.0, "ASK": 100.5}}
    snapshot = mss.build_market_state_snapshot(_fake_bloomberg(quotes))
    state = snapshot.tickers[0]
    assert state.spread_bps == pytest.approx(49.88, abs=0.05)
    assert state.spread_vs_baseline_bps is None
    assert state.flags == ()


@pytest.mark.asyncio
async def test_baseline_lookup_failure_degrades():
    """基线查询失败 → 降级为无基线比较（不抛错、不填 0）。"""

    def _boom(_tickers):
        raise RuntimeError("db down")

    quotes = {"AAPL US Equity": {"BID": 100.0, "ASK": 100.5}}
    snapshot = mss.build_market_state_snapshot(_fake_bloomberg(quotes), baseline_lookup=_boom)
    assert snapshot.tickers[0].spread_vs_baseline_bps is None


@pytest.mark.asyncio
async def test_intraday_state_enabled_follows_settings(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", False)
    assert mss.intraday_state_enabled() is False
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", True)
    assert mss.intraday_state_enabled() is True


# ── v2 实时涨跌幅 ───────────────────────────────────────────────────────────


def _fake_bloomberg_v2(quotes: dict, changes=None):
    """带报价与涨跌幅缓存的最小替身（与门面暴露的属性同名）。"""
    return SimpleNamespace(intraday_quotes=quotes, price_changes=changes or {})


@pytest.mark.asyncio
async def test_snapshot_prefers_pushed_chg_pct():
    quotes = {"AAPL US Equity": {"BID": 100.0, "ASK": 100.5, "LAST_PRICE": 100.2}}
    snapshot = mss.build_market_state_snapshot(
        _fake_bloomberg_v2(quotes, changes={"AAPL US Equity": 1.234567})
    )
    assert snapshot.schema_version == MARKET_STATE_SCHEMA_VERSION
    assert snapshot.tickers[0].pct_change_1d == 1.23


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_prev_close_when_chg_pct_missing():
    """本机终端 CHG_PCT_1D 不推送：用 LAST_PRICE ÷ PREV_CLOSE_VALUE_REALTIME 回落。"""
    quotes = {
        "AAPL US Equity": {
            "BID": 101.0,
            "ASK": 101.2,
            "LAST_PRICE": 101.0,
            "PREV_CLOSE_VALUE_REALTIME": 100.0,
        }
    }
    state = mss.build_market_state_snapshot(_fake_bloomberg_v2(quotes)).tickers[0]
    assert state.pct_change_1d == 1.0


@pytest.mark.asyncio
async def test_snapshot_pct_change_none_without_quotes_or_prev_close():
    """无行情 / 前收缺失或非正数时字段为 None（不猜 0）。"""
    quotes = {"AAPL US Equity": {"BID": 100.0, "ASK": 100.5}}
    assert mss.build_market_state_snapshot(_fake_bloomberg_v2(quotes)).tickers[0].pct_change_1d is None

    zero_prev = {
        "AAPL US Equity": {"LAST_PRICE": 100.0, "PREV_CLOSE_VALUE_REALTIME": 0.0},
    }
    assert mss.build_market_state_snapshot(_fake_bloomberg_v2(zero_prev)).tickers[0].pct_change_1d is None

    nan_change = {"AAPL US Equity": {"LAST_PRICE": 100.0}}
    state = mss.build_market_state_snapshot(
        _fake_bloomberg_v2(nan_change, changes={"AAPL US Equity": float("nan")})
    ).tickers[0]
    assert state.pct_change_1d is None


@pytest.mark.asyncio
async def test_snapshot_filters_by_whitelist_and_skips_unknown():
    quotes = {
        "AAPL US Equity": {"BID": 100.0, "ASK": 100.5},
        "MSFT US Equity": {"BID": 400.0, "ASK": 400.4},
    }
    snapshot = mss.build_market_state_snapshot(
        _fake_bloomberg_v2(quotes), tickers=["MSFT US Equity", "NOPE US Equity"]
    )
    assert [state.equ_ticker for state in snapshot.tickers] == ["MSFT US Equity"]


# ── 门面暴露（生产链路打通：market_state_service 读得到订阅缓存） ────────────


def test_facade_exposes_realtime_caches():
    """门面必须代理 enrichment 的四个实时缓存。

    缺少该代理时 `build_market_state_snapshot` 的 getattr 恒为 None，
    `/api/market-state/*` 在生产环境永远返回空 tickers（前端实时列为空）。
    """
    from services.bloomberg_adapter import BloombergEMSXService

    service = BloombergEMSXService()
    service._enrich._intraday_quotes["AAPL US Equity"] = {"BID": 100.0, "ASK": 100.5}
    service._enrich._price_changes["AAPL US Equity"] = 1.23

    assert service.intraday_quotes == {"AAPL US Equity": {"BID": 100.0, "ASK": 100.5}}
    assert service._intraday_quotes == service.intraday_quotes
    assert service.price_changes == {"AAPL US Equity": 1.23}
    assert service._price_changes == service.price_changes

    snapshot = mss.build_market_state_snapshot(service)
    assert [state.equ_ticker for state in snapshot.tickers] == ["AAPL US Equity"]
    assert snapshot.tickers[0].pct_change_1d == 1.23
