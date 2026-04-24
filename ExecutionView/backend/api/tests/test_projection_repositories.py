from inspect import iscoroutinefunction
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from repositories.audit import AuditEventRepository
from repositories.orders import OrderProjectionRepository
from repositories.routes import RouteProjectionRepository


def test_orders_repository_has_expected_async_methods():
    assert iscoroutinefunction(OrderProjectionRepository.upsert)
    assert iscoroutinefunction(OrderProjectionRepository.get_by_sequence)
    assert iscoroutinefunction(OrderProjectionRepository.list_by_status)


def test_routes_repository_has_expected_async_methods():
    assert iscoroutinefunction(RouteProjectionRepository.upsert)
    assert iscoroutinefunction(RouteProjectionRepository.get_by_keys)
    assert iscoroutinefunction(RouteProjectionRepository.list_by_sequence)


def test_audit_repository_has_expected_async_methods():
    assert iscoroutinefunction(AuditEventRepository.create_event)
    assert iscoroutinefunction(AuditEventRepository.list_recent)
