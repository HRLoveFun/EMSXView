"""Unit tests for the pre-trade compliance service."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import compliance_service


def make_order(**kwargs):
    """Build a SimpleNamespace masquerading as an Order for compliance checks."""
    defaults = dict(
        currency="USD",
        exchange="US",
        fxRate=1.0,
        lastPrice=10.0,
        roundLotSize=None,
        amount=100,
        orderType="LMT",
        limitPrice=10.0,
        stopPrice=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# USD notional rules
# ---------------------------------------------------------------------------

def test_notional_below_min_blocks():
    order = make_order(currency="USD", fxRate=1.0)
    # 10 * 100 = 1,000 USD, below 10,000 threshold
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=10.0, stop_price=None, order_type="LMT",
    )
    codes = [v.code for v in violations]
    assert "NOTIONAL_TOO_SMALL" in codes


def test_notional_just_at_min_passes():
    order = make_order(currency="USD", fxRate=1.0)
    # 100 * 100 = 10,000 USD == threshold (not "<")
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=100.0, stop_price=None, order_type="LMT",
    )
    assert all(v.code != "NOTIONAL_TOO_SMALL" for v in violations)
    assert all(v.code != "NOTIONAL_TOO_LARGE" for v in violations)


def test_notional_just_below_min_blocks():
    order = make_order(currency="USD", fxRate=1.0)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=99.99, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "NOTIONAL_TOO_SMALL" for v in violations)


def test_notional_at_max_passes():
    order = make_order(currency="USD", fxRate=1.0)
    # 49,000,000 == max threshold (not ">")
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=490_000.0, stop_price=None, order_type="LMT",
    )
    assert all(v.code != "NOTIONAL_TOO_LARGE" for v in violations)


def test_notional_above_max_blocks():
    order = make_order(currency="USD", fxRate=1.0)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=490_000.01, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "NOTIONAL_TOO_LARGE" for v in violations)


def test_market_order_uses_last_price_fallback():
    order = make_order(currency="USD", fxRate=1.0, lastPrice=200.0)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=None, stop_price=None, order_type="MKT",
    )
    # 200 * 100 = 20,000 — within bounds
    assert violations == []


def test_market_order_without_last_price_blocks():
    order = make_order(currency="USD", fxRate=1.0, lastPrice=None)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=None, stop_price=None, order_type="MKT",
    )
    assert any(v.code == "NOTIONAL_UNKNOWN" for v in violations)


def test_market_order_falls_back_to_arrival_price():
    """When lastPrice is missing, broaden fallback chain to arrivalPrice / vwap / avgPrice / price."""
    order = make_order(
        currency="USD", fxRate=1.0,
        lastPrice=None, mktVwap=None, dayAvgPrice=None,
        arrivalPrice=200.0,
    )
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=None, stop_price=None, order_type="MKT",
    )
    # 200 * 100 = 20,000 — within bounds; should NOT be NOTIONAL_UNKNOWN
    assert all(v.code != "NOTIONAL_UNKNOWN" for v in violations)


def test_market_order_falls_back_to_parent_price():
    """Resting LIMIT parent with no tape — `price` is the last viable fallback."""
    order = make_order(
        currency="USD", fxRate=1.0,
        lastPrice=None, mktVwap=None, dayAvgPrice=None,
        arrivalPrice=None, avgPrice=None, price=150.0,
    )
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=None, stop_price=None, order_type="MKT",
    )
    assert all(v.code != "NOTIONAL_UNKNOWN" for v in violations)


def test_non_usd_with_fx_rate_converts():
    # JPY 1500 * 100 = 150,000 JPY * 0.0067 = ~1005 USD -> below min
    order = make_order(currency="JPY", exchange="JP", fxRate=0.0067)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=1500.0, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "NOTIONAL_TOO_SMALL" for v in violations)


def test_non_usd_without_fx_rate_blocks_unknown():
    order = make_order(currency="EUR", exchange="GR", fxRate=None)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=100.0, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "NOTIONAL_UNKNOWN" for v in violations)


# ---------------------------------------------------------------------------
# JP odd-lot rule
# ---------------------------------------------------------------------------

def test_jp_qty_99_blocks_odd_lot():
    # JPY 1000 * 99 * 0.0067 ~ 663 USD (also notional small) — assert odd lot still raised
    order = make_order(currency="JPY", exchange="JP", fxRate=0.0067, lastPrice=1000.0)
    violations = compliance_service.check_route(
        order, route_qty=99, limit_price=1000.0, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "JP_ODD_LOT" for v in violations)


def test_jp_qty_100_passes_odd_lot():
    order = make_order(currency="JPY", exchange="JP", fxRate=0.01, lastPrice=20000.0)
    violations = compliance_service.check_route(
        order, route_qty=100, limit_price=20000.0, stop_price=None, order_type="LMT",
    )
    # 20000 * 100 * 0.01 = 20,000 USD -> within bounds; not odd-lot
    assert all(v.code != "JP_ODD_LOT" for v in violations)


def test_jp_custom_round_lot_10_blocks_qty_15():
    order = make_order(
        currency="JPY", exchange="JP", fxRate=0.01, lastPrice=20000.0,
        roundLotSize=10,
    )
    violations = compliance_service.check_route(
        order, route_qty=15, limit_price=20000.0, stop_price=None, order_type="LMT",
    )
    assert any(v.code == "JP_ODD_LOT" for v in violations)


def test_non_jp_qty_99_passes_odd_lot():
    order = make_order(currency="USD", exchange="US", fxRate=1.0)
    violations = compliance_service.check_route(
        order, route_qty=99, limit_price=200.0, stop_price=None, order_type="LMT",
    )
    assert all(v.code != "JP_ODD_LOT" for v in violations)


# ---------------------------------------------------------------------------
# check_modify
# ---------------------------------------------------------------------------

def test_modify_uses_cached_amount_when_qty_omitted():
    cached = SimpleNamespace(amount=50, orderType="LMT", limitPrice=10.0, stopPrice=None,
                             currency="USD", exchange="US", lastPrice=10.0)
    parent = make_order(currency="USD", fxRate=1.0)
    # 50 * 10 = 500 USD < 10K -> blocked
    violations = compliance_service.check_modify(
        cached, parent,
        new_qty=None, new_limit_price=None, new_stop_price=None, new_order_type=None,
    )
    assert any(v.code == "NOTIONAL_TOO_SMALL" for v in violations)


def test_modify_overrides_use_new_values():
    cached = SimpleNamespace(amount=50, orderType="LMT", limitPrice=10.0, stopPrice=None,
                             currency="USD", exchange="US", lastPrice=10.0)
    parent = make_order(currency="USD", fxRate=1.0)
    # New qty 100 * new price 200 = 20,000 USD -> passes
    violations = compliance_service.check_modify(
        cached, parent,
        new_qty=100, new_limit_price=200.0, new_stop_price=None, new_order_type="LMT",
    )
    assert violations == []
