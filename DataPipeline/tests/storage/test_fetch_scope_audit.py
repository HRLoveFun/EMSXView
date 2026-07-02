"""Scope 锁定与 ErrorResponse 处理单元测试.

校验:
    1. fetch_fills / _fetch_fills_once / fetch_day / fetch_range_aggregated
       签名不含 team 参数（scope 已固定为 TradingSystem）
    2. _fetch_fills_once 收到 ErrorResponse 消息时抛出 EMSXRequestError
    3. _fetch_fills_once 收到 ErrorInfo 消息时抛出 EMSXRequestError
    4. _parse_fill_messages 解析异常时记录 logger.warning（不静默吞错）
    5. _build_request_error 正确提取 ErrorCode / ErrorMsg 字段
"""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock, patch

import pytest

from DataPipeline.acquisition.bloomberg_fill_fetcher import (
    BloombergFillFetcher,
    EMSXRequestError,
)
from DataPipeline.acquisition._constants import (
    ERROR_RESPONSE,
    ERROR_INFO,
    GET_FILLS_RESPONSE,
)


# ── 测试 1: 方法签名不含 team 参数 ─────────────────────────────────────────


@pytest.mark.parametrize("method_name", [
    "fetch_fills",
    "_fetch_fills_once",
])
def test_bloomberg_fetcher_methods_no_team_param(method_name: str):
    """BloombergFillFetcher 的 fetch 方法签名不应含 team 参数。"""
    method = getattr(BloombergFillFetcher, method_name)
    sig = inspect.signature(method)
    assert "team" not in sig.parameters, (
        f"{method_name} 不应含 team 参数（scope 已固定为 TradingSystem）"
    )


def test_fill_fetch_methods_no_team_param():
    """FillFetch 的 fetch 方法签名不应含 team 参数。"""
    from DataPipeline.ingestion.fill_fetch import FillFetch

    for method_name in ["fetch_day", "fetch_range", "fetch_range_aggregated"]:
        method = getattr(FillFetch, method_name)
        sig = inspect.signature(method)
        assert "team" not in sig.parameters, (
            f"{method_name} 不应含 team 参数（scope 已固定为 TradingSystem）"
        )


# ── 测试 2-3: ErrorResponse / ErrorInfo 触发 EMSXRequestError ──────────────


def _make_mock_msg(msg_type, error_code: str = "", error_msg: str = ""):
    """构造 mock blpapi message。"""
    msg = MagicMock()
    msg.messageType.return_value = msg_type

    def get_element(name):
        if name == "ErrorCode":
            if not error_code:
                raise KeyError(name)
            return error_code
        if name == "ErrorMsg":
            if not error_msg:
                raise KeyError(name)
            return error_msg
        raise KeyError(name)

    msg.getElementAsString.side_effect = get_element
    return msg


def _make_fetcher_with_mock_session():
    """构造已连接的 BloombergFillFetcher（mock session）。"""
    fetcher = BloombergFillFetcher()
    fetcher._connected = True
    fetcher._session = MagicMock()
    fetcher._session.getService.return_value.createRequest.return_value = MagicMock()
    return fetcher


def test_fetch_fills_once_raises_on_error_response():
    """ErrorResponse 消息应抛出 EMSXRequestError，而非静默返回空列表。"""
    fetcher = _make_fetcher_with_mock_session()

    # 构造事件序列：一个含 ErrorResponse 的 RESPONSE 事件
    error_msg = _make_mock_msg(ERROR_RESPONSE, "ERROR_PERMISSION",
                               "User not permissioned to view fills.")
    response_event = MagicMock()
    response_event.eventType.return_value = MagicMock()  # 任意值，下面 patch 覆盖

    with patch("blpapi.Event") as mock_event_cls, \
         patch.object(fetcher._session, "nextEvent") as mock_next_event:
        # 让 eventType() 返回 blpapi.Event.RESPONSE
        mock_event_cls.RESPONSE = MagicMock()
        mock_event_cls.PARTIAL_RESPONSE = MagicMock()
        mock_event_cls.TIMEOUT = MagicMock()
        response_event.eventType.return_value = mock_event_cls.RESPONSE
        response_event.__iter__ = lambda self, it=iter([error_msg]): it
        mock_next_event.return_value = response_event

        with pytest.raises(EMSXRequestError) as exc_info:
            fetcher._fetch_fills_once(
                __import__("datetime").datetime(2026, 6, 29),
                __import__("datetime").datetime(2026, 6, 30),
            )

    assert "ERROR_PERMISSION" in str(exc_info.value)
    assert "User not permissioned" in str(exc_info.value)


def test_fetch_fills_once_raises_on_error_info():
    """ErrorInfo 消息同样应抛出 EMSXRequestError。"""
    fetcher = _make_fetcher_with_mock_session()

    error_msg = _make_mock_msg(ERROR_INFO, "ERROR_GENERIC", "Some error info.")
    response_event = MagicMock()

    with patch("blpapi.Event") as mock_event_cls, \
         patch.object(fetcher._session, "nextEvent") as mock_next_event:
        mock_event_cls.RESPONSE = MagicMock()
        mock_event_cls.PARTIAL_RESPONSE = MagicMock()
        mock_event_cls.TIMEOUT = MagicMock()
        response_event.eventType.return_value = mock_event_cls.RESPONSE
        response_event.__iter__ = lambda self, it=iter([error_msg]): it
        mock_next_event.return_value = response_event

        with pytest.raises(EMSXRequestError) as exc_info:
            fetcher._fetch_fills_once(
                __import__("datetime").datetime(2026, 6, 29),
                __import__("datetime").datetime(2026, 6, 30),
            )

    assert "ERROR_GENERIC" in str(exc_info.value)


# ── 测试 4: _parse_fill_messages 解析异常记录 warning ───────────────────────


def test_parse_fill_messages_exception_logs_warning(caplog):
    """_parse_fill_messages 解析异常时应记录 logger.warning，而非静默 pass。"""
    from DataPipeline.acquisition.bloomberg_fill_fetcher import _parse_fill_messages

    # 构造一个会在 getElement("Fills") 时抛异常的 mock msg
    bad_msg = MagicMock()
    bad_msg.getElement.side_effect = RuntimeError("mock parse failure")

    with caplog.at_level(logging.WARNING, logger="DataPipeline.acquisition.bloomberg_fill_fetcher"):
        # _parse_fill_messages 内部抛异常，由调用处 except 捕获并 warning
        # 此处直接验证调用处行为：构造 PARTIAL_RESPONSE 事件含坏消息
        fetcher = _make_fetcher_with_mock_session()
        good_msg = MagicMock()
        good_msg.messageType.return_value = GET_FILLS_RESPONSE
        good_msg.getElement.side_effect = RuntimeError("bad fills element")

        response_event = MagicMock()
        with patch("blpapi.Event") as mock_event_cls, \
             patch.object(fetcher._session, "nextEvent") as mock_next_event:
            mock_event_cls.RESPONSE = MagicMock()
            mock_event_cls.PARTIAL_RESPONSE = MagicMock()
            mock_event_cls.TIMEOUT = MagicMock()
            response_event.eventType.return_value = mock_event_cls.RESPONSE
            response_event.__iter__ = lambda self, it=iter([good_msg]): it
            mock_next_event.return_value = response_event

            # 不会抛异常，但应记录 warning；返回空 fills（解析失败）
            fills = fetcher._fetch_fills_once(
                __import__("datetime").datetime(2026, 6, 29),
                __import__("datetime").datetime(2026, 6, 30),
            )

    assert fills == []
    assert any("解析 fill 消息失败" in r.message for r in caplog.records), (
        "解析异常应记录 warning 日志，而非静默 pass"
    )


# ── 测试 5: _build_request_error 提取字段 ───────────────────────────────────


def test_build_request_error_extracts_fields():
    """_build_request_error 应从 ErrorResponse 消息提取 ErrorCode 和 ErrorMsg。"""
    msg = _make_mock_msg(ERROR_RESPONSE, "ERROR_PERMISSION", "Permission denied.")
    err = BloombergFillFetcher._build_request_error(msg)

    assert isinstance(err, EMSXRequestError)
    assert "ERROR_PERMISSION" in str(err)
    assert "Permission denied." in str(err)


def test_build_request_error_handles_missing_fields():
    """字段缺失时 _build_request_error 不应抛异常，返回含空值的 EMSXRequestError。"""
    msg = _make_mock_msg(ERROR_RESPONSE, "", "")
    err = BloombergFillFetcher._build_request_error(msg)

    assert isinstance(err, EMSXRequestError)
    # 不抛异常即可
    assert "Bloomberg API error" in str(err)
