"""Regression tests for Bloomberg refdata request handling."""

import services.bloomberg_adapter as bloomberg_adapter

from schemas import OrderStatus
from services.bloomberg_adapter import BloombergEMSXService


def test_order_status_enum_accepts_sent():
    assert OrderStatus("SENT") == OrderStatus.SENT


def test_refdata_response_completion_only_clears_matching_pending_flags():
    service = BloombergEMSXService()
    service._fx_refdata_pending = True
    service._crncy_refdata_pending = True
    service._round_lot_refdata_pending = True

    service._mark_refdata_response_complete({"__crncy_refdata__"})

    assert service._fx_refdata_pending is True
    assert service._crncy_refdata_pending is False
    assert service._round_lot_refdata_pending is True


def test_refdata_response_completion_clears_fx_when_matching():
    service = BloombergEMSXService()
    service._fx_refdata_pending = True
    service._crncy_refdata_pending = True

    service._mark_refdata_response_complete({"__fx_refdata__", "__crncy_refdata__"})

    assert service._fx_refdata_pending is False
    assert service._crncy_refdata_pending is False


def test_scaled_fx_discrepancy_logs_info_once(monkeypatch):
    service = BloombergEMSXService()
    info_messages: list[str] = []
    warning_messages: list[str] = []

    monkeypatch.setattr(bloomberg_adapter.logger, "info", lambda message: info_messages.append(message))
    monkeypatch.setattr(bloomberg_adapter.logger, "warning", lambda message: warning_messages.append(message))

    service._log_fx_rate_discrepancy("KRW", 0.066210, 0.000662)
    service._log_fx_rate_discrepancy("KRW", 0.066300, 0.000663)

    assert len(info_messages) == 1
    assert "scaled by 100x" in info_messages[0]
    assert warning_messages == []


def test_unscaled_fx_discrepancy_remains_warning(monkeypatch):
    service = BloombergEMSXService()
    warning_messages: list[str] = []

    monkeypatch.setattr(bloomberg_adapter.logger, "warning", lambda message: warning_messages.append(message))

    service._log_fx_rate_discrepancy("EUR", 0.88, 0.80)

    assert len(warning_messages) == 1
    assert "FX EUR" in warning_messages[0]