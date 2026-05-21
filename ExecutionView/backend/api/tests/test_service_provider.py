"""Tests for the RepositoryProvider service layer (P1-S1-04)."""

import asyncio
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from service_provider import RepositoryProvider


# ------------------------------------------------------------------
#  Unit tests — no real DB required
# ------------------------------------------------------------------

def test_provider_disabled_by_default():
    """When DB libs are present but enabled=False, is_active is False."""
    prov = RepositoryProvider(enabled=False)
    prov.mark_db_ready(True)
    assert not prov.is_active


def test_provider_enabled_but_db_not_ready():
    """Provider enabled but DB not yet probed → not active."""
    prov = RepositoryProvider(enabled=True)
    assert not prov.is_active


def test_provider_active_when_enabled_and_ready():
    """Provider should be active when both enabled and DB ready."""
    prov = RepositoryProvider(enabled=True)
    prov.mark_db_ready(True)
    assert prov.is_active


def test_circuit_breaker_trips_after_max_errors():
    """After N write errors the provider circuit-breaks."""
    prov = RepositoryProvider(enabled=True)
    prov.mark_db_ready(True)
    prov._write_errors = prov._max_write_errors
    assert not prov.is_active


def test_mark_db_ready_resets_errors():
    prov = RepositoryProvider(enabled=True)
    prov._write_errors = 5
    prov.mark_db_ready(True)
    assert prov._write_errors == 0
    assert prov.is_active


# ------------------------------------------------------------------
#  Async fallback tests (using asyncio.run — no pytest-asyncio needed)
# ------------------------------------------------------------------

def test_persist_order_noop_when_inactive():
    prov = RepositoryProvider(enabled=False)
    result = asyncio.run(prov.persist_order(
        sequence=1, order_id="1", status="NEW", trader="t1", payload={}
    ))
    assert result is False


def test_persist_route_noop_when_inactive():
    prov = RepositoryProvider(enabled=False)
    result = asyncio.run(prov.persist_route(
        sequence=1, route_id=1, status="SENT", broker="B", payload={}
    ))
    assert result is False


def test_persist_audit_event_noop_when_inactive():
    prov = RepositoryProvider(enabled=False)
    result = asyncio.run(prov.persist_audit_event(
        action="TEST", actor="user", endpoint="/test", result="ok"
    ))
    assert result is False


def test_load_orders_returns_empty_when_inactive():
    prov = RepositoryProvider(enabled=False)
    assert asyncio.run(prov.load_orders()) == []



def test_load_routes_returns_empty_when_inactive():
    prov = RepositoryProvider(enabled=False)
    assert asyncio.run(prov.load_routes()) == []


def test_load_audit_events_returns_empty_when_inactive():
    prov = RepositoryProvider(enabled=False)
    assert asyncio.run(prov.load_audit_events()) == []


# ------------------------------------------------------------------
#  Inmemory fallback checkpoint — read path falls back gracefully
# ------------------------------------------------------------------

def test_inmemory_fallback_remains_available():
    """Verify that when provider is disabled, callers get empty lists
    (which means the in-memory cache stays the sole data source)."""
    prov = RepositoryProvider(enabled=False)
    prov.mark_db_ready(False)
    orders = asyncio.run(prov.load_orders())
    routes = asyncio.run(prov.load_routes())
    assert orders == []
    assert routes == []
