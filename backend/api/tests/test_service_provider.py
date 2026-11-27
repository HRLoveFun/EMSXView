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


# ------------------------------------------------------------------
#  Circuit breaker 三态（CLOSED → OPEN → HALF_OPEN）
#  2026-11-27 事故回归：原实现只在进程启动清零，一次连接池耗尽即永久
#  锁在内存回退态，必须重启才恢复落盘。
# ------------------------------------------------------------------

class _FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _tripped_provider(threshold: int = 3, cooldown: float = 30.0):
    """构造一个已熔断的 provider（假时钟，便于推进冷却窗口）。"""
    prov = RepositoryProvider(enabled=True)
    prov.mark_db_ready(True)
    clock = _FakeClock()
    prov._clock = clock
    prov._max_write_errors = threshold
    prov._circuit_cooldown = cooldown
    for _ in range(threshold):
        prov._record_failure("persist_order", RuntimeError("pool exhausted"))
    return prov, clock


def test_success_resets_consecutive_failure_count():
    prov = RepositoryProvider(enabled=True)
    prov.mark_db_ready(True)
    prov._max_write_errors = 3

    prov._record_failure("persist_order", RuntimeError("once"))
    prov._record_failure("persist_route", RuntimeError("twice"))
    assert prov.write_error_count == 2
    assert prov.is_active, "未达阈值不应熔断"

    prov._record_success()
    assert prov.write_error_count == 0
    assert prov.circuit_state == "closed"


def test_circuit_opens_after_threshold():
    prov, _ = _tripped_provider(threshold=3)
    assert prov.circuit_state == "open"
    assert prov.circuit_open is True
    assert not prov.is_active
    assert not prov._allow_write()


def test_half_open_after_cooldown_allows_exactly_one_probe():
    prov, clock = _tripped_provider(threshold=3, cooldown=30.0)
    clock.now += 30.0

    assert prov.circuit_state == "half_open"
    # 调用方在 is_active 处的预检必须放行，否则探针永远到不了 provider
    assert prov.is_active
    assert prov._allow_write() is True
    assert prov._allow_write() is False, "half_open 只允许一个在途探针"


def test_half_open_probe_success_closes_circuit():
    prov, clock = _tripped_provider(threshold=3, cooldown=30.0)
    clock.now += 30.0
    assert prov._allow_write() is True

    prov._record_success()

    assert prov.circuit_state == "closed"
    assert prov.write_error_count == 0
    assert prov.is_active


def test_half_open_probe_failure_reopens_and_restarts_cooldown():
    prov, clock = _tripped_provider(threshold=3, cooldown=30.0)
    clock.now += 30.0
    assert prov._allow_write() is True

    prov._record_failure("persist_order", RuntimeError("still down"))

    assert prov.circuit_state == "open"
    assert prov._circuit_opened_at == clock.now, "探针失败应重新计时冷却窗口"


def test_open_window_is_not_extended_by_late_failures():
    """OPEN 期间（如已发放的写请求陆续超时）不得刷新打开时刻。"""
    prov, clock = _tripped_provider(threshold=3, cooldown=30.0)
    opened_at = prov._circuit_opened_at
    clock.now += 10.0

    prov._record_failure("persist_route", RuntimeError("late timeout"))

    assert prov._circuit_opened_at == opened_at
    assert prov.circuit_state == "open"


def test_mark_db_ready_resets_open_circuit():
    prov, _ = _tripped_provider(threshold=3)
    assert prov.circuit_state == "open"

    prov.mark_db_ready(True)

    assert prov.circuit_state == "closed"
    assert prov.write_error_count == 0
    assert prov.is_active
