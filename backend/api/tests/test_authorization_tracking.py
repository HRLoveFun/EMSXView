"""S12 (042) — PM 授权剩余量计算与 API 测试。

锁死行为：剩余授权 = target − 执行占用（父单承诺量，含计划中切片）；
symbol+side 精确匹配、portfolio 空则不限；订单投影缺失的父单排除并告警；
check_authorization 三态（not_covered / exceeded / ok）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from services.authorization_service import check_authorization, compute_remaining


def _intent(id=1, symbol="AAPL US Equity", side="BUY", portfolio=None, target=600_000):
    return {
        "id": id, "symbol": symbol, "side": side, "portfolio": portfolio,
        "target_quantity": target, "status": "ACTIVE",
        "note": None, "updated_at": "",
    }


def _parent(parent_id=1, order_id="1001", target=300_000, filled=100_000):
    return SimpleNamespace(
        id=parent_id, order_id=order_id, target_quantity=target,
        filled_quantity=filled, status="ACTIVE",
    )


def _payloads() -> dict:
    return {
        "1001": {"id": "1001", "symbol": "AAPL US Equity", "side": "BUY", "portfolio": "TECH"},
    }


def test_compute_remaining_basic():
    """剩余 = target − 父单承诺量（含计划中切片，非仅已成交）。"""
    views = compute_remaining(
        [_intent(target=600_000)],
        [_parent(target=300_000, filled=100_000)],
        _payloads(),
    )
    v = views[0]
    assert v["committedQuantity"] == 300_000
    assert v["filledQuantity"] == 100_000
    assert v["remainingQuantity"] == 300_000


def test_portfolio_unlimited_intent_merges_all_portfolios():
    """intent portfolio 为空：合并同 symbol+side 的所有组合占用。"""
    payloads = {
        "1001": {"id": "1001", "symbol": "AAPL US Equity", "side": "BUY", "portfolio": "TECH"},
        "1002": {"id": "1002", "symbol": "AAPL US Equity", "side": "BUY", "portfolio": "HEALTH"},
    }
    parents = [_parent(1, "1001", target=200_000), _parent(2, "1002", target=150_000)]
    views = compute_remaining([_intent(portfolio=None, target=600_000)], parents, payloads)
    assert views[0]["committedQuantity"] == 350_000
    assert views[0]["remainingQuantity"] == 250_000


def test_side_mismatch_not_committed():
    """side 不匹配（BUY 授权 vs SELL 父单）：不计占用。"""
    payloads = {"1001": {"id": "1001", "symbol": "AAPL US Equity", "side": "SELL", "portfolio": "TECH"}}
    views = compute_remaining([_intent(side="BUY")], [_parent()], payloads)
    assert views[0]["committedQuantity"] == 0


def test_missing_order_payload_excluded():
    """订单投影缺失的父单：排除出占用（告警可见）。"""
    views = compute_remaining([_intent()], [_parent(order_id="9999")], _payloads())
    assert views[0]["committedQuantity"] == 0


def test_check_authorization_three_outcomes():
    """三态：not_covered / exceeded / ok。"""
    intents = [_intent(target=600_000)]
    parents = [_parent(target=550_000, filled=100_000)]

    # not_covered：无匹配授权（symbol 不同）
    r = check_authorization(intents, parents, _payloads(),
                            symbol="MSFT US Equity", side="BUY", portfolio="TECH",
                            additional_qty=100)
    assert r["outcome"] == "not_covered"

    # exceeded：剩余 50,000 < 请求 60,000
    r = check_authorization(intents, parents, _payloads(),
                            symbol="AAPL US Equity", side="BUY", portfolio="TECH",
                            additional_qty=60_000)
    assert r["outcome"] == "exceeded"
    assert r["remainingQuantity"] == 50_000

    # ok：请求 40,000 ≤ 剩余 50,000
    r = check_authorization(intents, parents, _payloads(),
                            symbol="AAPL US Equity", side="BUY", portfolio="TECH",
                            additional_qty=40_000)
    assert r["outcome"] == "ok"


def test_authorization_endpoints(monkeypatch):
    """端点集成：admin 创建 + 查询剩余量（provider 不可用时显式降级）。"""
    import importlib
    import deps
    importlib.reload(deps)
    from routers import authorizations as authz
    authz = importlib.reload(authz)

    # provider 不可用：创建显式失败（不静默），查询空列表
    monkeypatch.setattr(deps, "get_repo_provider", lambda: None)
    app = FastAPI()
    app.include_router(authz.router)
    client = TestClient(app)

    resp = client.post("/api/authorizations", json={
        "symbol": "AAPL US Equity", "side": "BUY", "targetQuantity": 600_000,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "unavailable" in body["error"]

    resp = client.get("/api/authorizations")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
