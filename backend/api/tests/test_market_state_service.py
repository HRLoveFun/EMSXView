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

from platform_data.contracts import MarketBaseline, MarketStateThresholds  # noqa: E402
from services.bloomberg import enrichment as mde  # noqa: E402
from services import market_state_service as mss  # noqa: E402


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


def test_mktdata_fields_enabled_adds_six_fields():
    fields = mde.mktdata_fields(True)
    for field in ("BID", "ASK", "LAST_PRICE", "VOLUME", "HIGH", "LOW"):
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
