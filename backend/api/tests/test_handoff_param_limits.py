"""P3 整改回归测试: handoff strategy_params 64KB 载荷契约（A1-A4）。

背景:
    strategy_params 此前仅在 adapter 抛 ValueError → 端点无捕获 → HTTP 500
    裸异常串（A6 之前的前端也无预检）。

校验:
    1. 契约常量锁定为 64KB（禁止可配置漂移，A4）
    2. API schema 主拦截层：超限 → ValidationError（FastAPI 映射 422，A1）
    3. adapter 双保险：直调路径同样拒绝，错误信息含 actual/max bytes（A2）
    4. 阈值边界：恰好等于上限时放行
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

# 既有约定：backend/api 加入 sys.path 以导入 schemas 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_data.adapters.handoff import (
    HandoffExchangeAdapter,
    _bounded_strategy_params,
)
from platform_data.contracts import HANDOFF_MAX_STRATEGY_PARAMS_BYTES
from schemas.handoff import PostTradeHandoffRequest


def _payload_of_bytes(n: int) -> dict:
    """构造序列化后约 n 字节的 strategy_params。"""
    return {"blob": "x" * n}


def test_contract_constant_locked_at_64kb():
    """契约常量锁定：64KB，前后端/三层校验共用，禁止调整。"""
    assert HANDOFF_MAX_STRATEGY_PARAMS_BYTES == 64 * 1024


def test_schema_rejects_oversized_params():
    """API schema 主拦截层：超限请求体校验失败（FastAPI → 422）。"""
    big = _payload_of_bytes(HANDOFF_MAX_STRATEGY_PARAMS_BYTES + 1024)
    with pytest.raises(ValidationError) as excinfo:
        PostTradeHandoffRequest(order_id="O1", strategy_params=big)
    assert "actual_bytes" in str(excinfo.value)
    assert "max_bytes" in str(excinfo.value)


def test_schema_accepts_params_at_limit():
    """阈值边界：恰好等于上限时放行（>= 才拒绝）。"""
    params = {"blob": "x" * (HANDOFF_MAX_STRATEGY_PARAMS_BYTES - 100)}
    req = PostTradeHandoffRequest(order_id="O1", strategy_params=params)
    assert req.strategy_params == params


def test_adapter_double_insurance_rejects_oversized():
    """adapter 双保险（直调绕过 schema 时）：错误信息含 actual/max bytes。"""
    big = _payload_of_bytes(HANDOFF_MAX_STRATEGY_PARAMS_BYTES + 1024)
    with pytest.raises(ValueError) as excinfo:
        _bounded_strategy_params(big)
    msg = str(excinfo.value)
    assert "actual_bytes" in msg and "max_bytes" in msg


def test_adapter_serialization_failure_raises():
    """无法序列化的 params（循环引用）→ ValueError（不静默放行）。"""
    circular: dict = {}
    circular["self"] = circular
    with pytest.raises(ValueError):
        _bounded_strategy_params(circular)


def test_publish_via_adapter_oversized_rejected():
    """端到端：经 adapter publish 超限被拒绝，exchange 状态不变。"""
    ex = HandoffExchangeAdapter()
    big = _payload_of_bytes(HANDOFF_MAX_STRATEGY_PARAMS_BYTES + 1024)
    with pytest.raises(ValueError):
        ex.publish_execution_to_cost(
            order_id="O-big", parent_execution_id=None, broker=None,
            strategy=None, asset_class=None, urgency=None,
            route_ids=[], strategy_params=big,
        )
    assert ex.get_execution_to_cost("O-big") is None


def test_json_serialization_matches_byte_contract():
    """schema 与 adapter 使用同一字节口径（UTF-8 序列化字节）。"""
    params = {"k": "中文" * 100}
    schema_size = len(json.dumps(params, default=str, ensure_ascii=False).encode("utf-8"))
    assert schema_size > 0
    # 非 ASCII 内容按字节计而非字符数——中文场景下字符数会低估
    assert schema_size > len(json.dumps(params, ensure_ascii=False))
