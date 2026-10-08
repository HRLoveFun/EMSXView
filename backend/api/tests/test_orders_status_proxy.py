"""045 — orders_status 端点代理修复测试。

实测发现：facade 拆分重构后遗漏 _init_paint_done / _subscription_failed
代理，GET /api/orders/status 访问 svc._init_paint_done 抛 AttributeError
→ 500。锁死：facade 暴露这两个属性 + 端点返回 200。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")


def test_facade_exposes_status_attrs():
    """BloombergEMSXService 必须暴露 _init_paint_done / _subscription_failed。"""
    from services.bloomberg.adapter import BloombergEMSXService

    service = BloombergEMSXService()
    assert isinstance(service._init_paint_done, bool)
    assert isinstance(service._subscription_failed, bool)


def test_orders_status_endpoint_returns_200(monkeypatch):
    """端点级：status 端点在 mock 适配器下返回 200 与真实计数字段。"""
    import threading
    from unittest.mock import MagicMock

    monkeypatch.setenv("BYPASS_AUTH", "true")
    monkeypatch.setenv("JWT_SECRET", "testsecret")

    import importlib

    import deps
    importlib.reload(deps)
    from routers import orders_crud
    importlib.reload(orders_crud)

    bloomberg = MagicMock()
    bloomberg._orders = {"1001": object()}
    bloomberg._routes = {}
    bloomberg._init_paint_done = True
    bloomberg._subscription_failed = False
    bloomberg.connected = True

    app = FastAPI()
    app.state.bloomberg_service = bloomberg
    app.include_router(orders_crud.router)
    client = TestClient(app)

    resp = client.get("/api/orders/status")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["init_paint_done"] is True
    assert data["order_count"] == 1
    assert data["route_count"] == 0
    assert data["is_connected"] is True
