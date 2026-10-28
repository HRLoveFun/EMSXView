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


def test_bypass_auth_allows_missing_token(monkeypatch):
    """BYPASS_AUTH=true 时本地开发免 token（与 core backend 同语义）。"""
    monkeypatch.setattr(config, "BYPASS_AUTH", True)
    monkeypatch.setattr(config, "JWT_SECRET", "")
    response = _client().post(
        "/api/marketview/handoff/execution",
        json={"pool_id": "all", "trade_date": "2026-10-26", "limit": 10},
    )
    assert response.status_code != 401


def test_bypass_identity_matches_core(monkeypatch):
    """bypass 身份与 core backend `_BYPASS_IDENTITY` 一致。"""
    import asyncio

    import auth

    monkeypatch.setattr(config, "BYPASS_AUTH", True)
    user = asyncio.run(auth.require_token(None))
    assert user == {
        "sub": "bloomberg_local",
        "name": "Bloomberg Terminal User",
        "role": "admin",
    }


def test_bypass_auth_defaults_to_false():
    """默认 fail-closed：测试环境固定关闭 bypass（见 conftest），与生产默认一致。"""
    assert config.BYPASS_AUTH is False
