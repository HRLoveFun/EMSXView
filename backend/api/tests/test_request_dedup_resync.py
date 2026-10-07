"""S7 (037) — 请求防重序号 + 结果未知语义 + 跳号重同步测试。

锁死行为（离线可测部分）：
- 交易请求携带单调递增 EMSX_REQUEST_SEQ（防故障期间重复请求）；
- restore_request_seq 重启恢复只升不降；
- 请求超时 504 结构化为结果未知（outcome=unknown + correlation）；
- API_SEQ_NUM 跳号触发缓存重同步回调（此前仅 warning 无动作）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import services.bloomberg.subscriptions as subs_mod
from services.bloomberg.request_handler import EMSXRequestHandler


# ---------------------------------------------------------------------------
# EMSX_REQUEST_SEQ 防重序号
# ---------------------------------------------------------------------------


def _handler() -> tuple[EMSXRequestHandler, MagicMock]:
    """构造可离线调用的 handler（连接/订阅引擎均为 mock）。"""
    conn = MagicMock()
    sub = MagicMock()
    settings = SimpleNamespace(BLOOMBERG_TIMEOUT=1000)
    return EMSXRequestHandler(conn, sub, settings), conn


def test_request_seq_monotonic():
    handler, _ = _handler()
    seqs = [handler._next_request_seq() for _ in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


def test_restore_request_seq_only_moves_forward():
    handler, _ = _handler()
    handler._next_request_seq()  # seq=1
    handler.restore_request_seq(100)
    assert handler.emsx_request_seq == 100
    assert handler._next_request_seq() == 101
    # 回退请求被拒绝：序号不得下降
    handler.restore_request_seq(5)
    assert handler.emsx_request_seq == 101


def test_route_order_carries_request_seq():
    """RouteEx 请求必须携带 EMSX_REQUEST_SEQ 防重序号。"""
    handler, conn = _handler()
    handler._subscription_engine.data_lock = threading.Lock()
    handler._subscription_engine.orders = {
        "1001": SimpleNamespace(
            status="WORKING", symbol="AAPL US Equity",
            trader="TRADER1", remainingQuantity=1000,
        ),
    }

    service = MagicMock()
    service.get_terminal_trader_name = MagicMock(return_value=None)

    fake_request_sets: dict = {}

    class FakeRequest:
        def set(self, name, value):
            fake_request_sets[name] = value

    conn.request_service = MagicMock()
    conn.request_service.createRequest = MagicMock(return_value=FakeRequest())

    from schemas import RouteOrderRequest
    req = RouteOrderRequest(
        orderId="1001", broker="CSFB", quantity=100,
        orderType="LIMIT", price=200.0, timeInForce="DAY",
    )

    # 绕开真实 blpapi 会话循环：注入异步发送
    handler._send_request_async = AsyncMock(return_value=[])

    result = asyncio.run(handler.route_order(req, service))
    assert result["success"] is True
    assert fake_request_sets.get("EMSX_REQUEST_SEQ") == 1
    # 第二次请求序号递增
    asyncio.run(handler.route_order(req, service))
    assert fake_request_sets.get("EMSX_REQUEST_SEQ") == 2


# ---------------------------------------------------------------------------
# 结果未知语义
# ---------------------------------------------------------------------------


def test_timeout_outcome_is_structured_unknown():
    """超时 504 detail 结构化：outcome=unknown + correlation 供核对。"""
    import blpapi

    handler, conn = _handler()
    conn.connected = True
    sess = MagicMock()

    # 模拟 nextEvent 永远 TIMEOUT（事件不可迭代也无妨——TIMEOUT 分支先抛出）
    class FakeTimeoutEvent:
        def eventType(self):
            return blpapi.Event.TIMEOUT

        def __iter__(self):
            return iter([])

    sess.nextEvent = MagicMock(return_value=FakeTimeoutEvent())
    conn.request_sessions = [sess]
    conn.request_locks = [threading.Lock()]
    conn.pool_index = 0

    fake_request = object()
    with pytest.raises(HTTPException) as exc_info:
        handler._send_request(fake_request)
    assert exc_info.value.status_code == 504
    detail = exc_info.value.detail
    assert detail["outcome"] == "unknown"
    assert detail["message"] == "Bloomberg request timed out"
    assert detail["correlation"]


# ---------------------------------------------------------------------------
# API_SEQ_NUM 跳号 → 重同步
# ---------------------------------------------------------------------------


def test_detect_seq_gap_boundaries():
    assert subs_mod.detect_seq_gap(3, 5) is True     # 跳号
    assert subs_mod.detect_seq_gap(3, 4) is False    # 相邻
    assert subs_mod.detect_seq_gap(3, 3) is False    # 重复
    assert subs_mod.detect_seq_gap(3, 2) is False    # 回退（乱序到达）


def _engine() -> subs_mod.EMSXSubscriptionEngine:
    return subs_mod.EMSXSubscriptionEngine(MagicMock(), MagicMock())


def test_gap_triggers_registered_resync_callback():
    engine = _engine()
    engine._last_order_api_seq_num = 3  # 基线：跳号检测需非零 last_seen
    calls: list[str] = []
    engine.register_resync_callback(calls.append)

    # 跳号：last=3, current=5
    engine._msg_safe_int = lambda msg, name, default=0: 5 if name == "API_SEQ_NUM" else 0
    engine._track_api_seq_num(object(), "order")

    assert calls == ["order"]
    assert engine._last_order_api_seq_num == 5


def test_gap_without_callback_logs_error(caplog):
    engine = _engine()
    engine._last_route_api_seq_num = 3
    engine._msg_safe_int = lambda msg, name, default=0: 5 if name == "API_SEQ_NUM" else 0

    with caplog.at_level(logging.ERROR, logger="main"):
        engine._track_api_seq_num(object(), "route")

    assert any("no resync callback" in r.message for r in caplog.records)
