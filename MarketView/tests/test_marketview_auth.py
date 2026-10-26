"""A04（M2）— MarketView 绑定地址与 handoff 鉴权测试。"""

from __future__ import annotations

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from routers import marketview


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(marketview.router)
    return TestClient(app)


def test_default_host_loopback(monkeypatch):
    """默认只监听回环地址（需要对外时显式设置 MARKETVIEW_HOST）。"""
    monkeypatch.delenv("MARKETVIEW_HOST", raising=False)
    import importlib

    reloaded = importlib.reload(config)
    try:
        assert reloaded.HOST == "127.0.0.1"
    finally:
        importlib.reload(config)


def test_handoff_post_requires_token(monkeypatch):
    """无 token → 401（A04 验收）。"""
    monkeypatch.setattr(config, "JWT_SECRET", "testsecret")
    response = _client().post(
        "/api/marketview/handoff/execution",
        json={"pool_id": "all", "trade_date": "2026-10-26", "limit": 10},
    )
    assert response.status_code == 401


def test_handoff_post_rejects_invalid_token(monkeypatch):
    """无效 token → 401。"""
    monkeypatch.setattr(config, "JWT_SECRET", "testsecret")
    response = _client().post(
        "/api/marketview/handoff/execution",
        json={"pool_id": "all", "trade_date": "2026-10-26", "limit": 10},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_handoff_post_accepts_valid_token(monkeypatch):
    """有效 token 通过鉴权（请求随后由业务校验/适配器处理）。"""
    monkeypatch.setattr(config, "JWT_SECRET", "testsecret")
    token = jwt.encode({"sub": "u1", "role": "trader"}, "testsecret", algorithm="HS256")
    response = _client().post(
        "/api/marketview/handoff/execution",
        json={"pool_id": "all", "trade_date": "2026-10-26", "limit": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 鉴权已过；无行情数据时业务层返回 4xx/5xx 均可，但绝不应是 401
    assert response.status_code != 401
