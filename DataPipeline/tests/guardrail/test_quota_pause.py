"""额度暂停标记 tombstone 与各拉取入口短路测试（005-bloomberg-quota-pause）。

校验:
    1. set_quota_pause / is_quota_paused / clear_quota_pause / load_quota_pause 读写
    2. set_quota_pause 幂等（重复置位仅更新 last_seen_at / hit_count）
    3. clear_quota_pause 幂等（不存在返回 False）
    4. is_quota_paused=True 时 BDIB / 日频 / FX / regime index 入口短路
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from DataPipeline.common.quota_pause import (
    clear_quota_pause,
    is_quota_paused,
    load_quota_pause,
    set_quota_pause,
)


@pytest.fixture()
def pause_file(tmp_path):
    """返回临时 quota_pause 文件路径，并隔离模块级 _resolve_path。"""
    p = tmp_path / "quota_pause.json"
    return p


def _patch_resolve(monkeypatch, pause_file):
    monkeypatch.setattr(
        "DataPipeline.common.quota_pause._resolve_path",
        lambda path=None: pause_file,
    )


# ── 测试 1: 基本读写 ──────────────────────────────────────────────────────


def test_quota_pause_set_is_clear(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    assert is_quota_paused(pause_file) is False

    rec = set_quota_pause("fill_empty_response", detail="test")
    assert rec["quota_paused"] is True
    assert rec["reason"] == "fill_empty_response"
    assert is_quota_paused(pause_file) is True

    loaded = load_quota_pause(pause_file)
    assert loaded["quota_paused"] is True
    assert loaded["hit_count"] == 1

    assert clear_quota_pause(pause_file) is True
    assert is_quota_paused(pause_file) is False
    assert load_quota_pause(pause_file) is None


def test_quota_pause_idempotent_set(monkeypatch, pause_file):
    """重复置位幂等：hit_count 递增，first_seen_at 保留。"""
    _patch_resolve(monkeypatch, pause_file)
    set_quota_pause("fill_empty_response", file_path=pause_file)
    first = load_quota_pause(pause_file)["first_seen_at"]

    set_quota_pause("fill_empty_response", file_path=pause_file)
    rec = load_quota_pause(pause_file)
    assert rec["hit_count"] == 2
    assert rec["first_seen_at"] == first


def test_quota_pause_clear_missing(monkeypatch, pause_file):
    """clear 不存在文件返回 False（幂等）。"""
    _patch_resolve(monkeypatch, pause_file)
    assert clear_quota_pause(pause_file) is False


def test_quota_pause_corrupt_file_returns_none(monkeypatch, pause_file):
    """损坏的标记文件不应抛异常，is_quota_paused 返回 False。"""
    _patch_resolve(monkeypatch, pause_file)
    pause_file.write_text("{ not valid json", encoding="utf-8")
    assert is_quota_paused(pause_file) is False


# ── 测试 2: BDIB 入口短路 ──────────────────────────────────────────────────


def test_bdib_fetch_short_circuits_when_paused(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    from DataPipeline.acquisition.bdib_fetcher import fetch_bdib_for_ticker_date

    set_quota_pause("fill_empty_response", file_path=pause_file)
    try:
        with patch(
            "DataPipeline.acquisition.bdib_fetcher.is_quota_paused", return_value=True
        ):
            result = fetch_bdib_for_ticker_date("AAPL US Equity", "20260601")
        assert result is None
    finally:
        clear_quota_pause(pause_file)


# ── 测试 3: 日频 (S7) 入口短路 ─────────────────────────────────────────────


def test_daily_history_short_circuits_when_paused(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    from DataPipeline.processing.daily_metrics_calculator import CalculateDailyMetrics

    set_quota_pause("fill_empty_response", file_path=pause_file)
    try:
        calc = CalculateDailyMetrics.__new__(CalculateDailyMetrics)
        with patch(
            "DataPipeline.processing.daily_metrics_calculator.is_quota_paused",
            return_value=True,
        ):
            result = calc._fetch_daily_history(["AAPL US Equity"], "20260601")
        assert result.empty
    finally:
        clear_quota_pause(pause_file)


# ── 测试 4: FX 入口短路 ────────────────────────────────────────────────────


def test_fx_fetch_short_circuits_when_paused(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    from DataPipeline.acquisition.fx_fetcher import fetch_fx_rate_for_ccy

    set_quota_pause("fill_empty_response", file_path=pause_file)
    try:
        with patch(
            "DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=True
        ):
            result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260601")
        assert result == 1.0
    finally:
        clear_quota_pause(pause_file)


# ── 测试 5: regime index 入口短路 ──────────────────────────────────────────


def test_market_index_fetcher_short_circuits_when_paused(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    import datetime as dt

    from DataPipeline.analysis.regime.market_index_loader import _xbbg_fetcher

    set_quota_pause("fill_empty_response", file_path=pause_file)
    try:
        with patch(
            "DataPipeline.analysis.regime.market_index_loader.is_quota_paused",
            return_value=True,
        ):
            result = _xbbg_fetcher(
                "SPX Index", ["PX_LAST"],
                dt.date(2026, 6, 1), dt.date(2026, 6, 2),
            )
        assert isinstance(result, pd.DataFrame)
        assert result.empty
    finally:
        clear_quota_pause(pause_file)


# ── 测试 6: composite ticker 入口短路 ──────────────────────────────────────


def test_composite_ticker_short_circuits_when_paused(monkeypatch, pause_file):
    _patch_resolve(monkeypatch, pause_file)
    from DataPipeline.processing.fill_processor import _fetch_composite_tickers

    set_quota_pause("fill_empty_response", file_path=pause_file)
    try:
        with patch(
            "DataPipeline.processing.fill_processor.is_quota_paused", return_value=True
        ):
            result = _fetch_composite_tickers(["AAPL US Equity"])
        assert result == {}
    finally:
        clear_quota_pause(pause_file)
