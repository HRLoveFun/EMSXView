"""A04（M2）— CostView 桥接鉴权测试。

锁死：14 个端点无 token → 401；写方法（pin）viewer → 403；GET viewer 可读；
Runner 触发端点要求 admin。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from deps import verify_token  # noqa: E402
from routers import costview as bridge  # noqa: E402


def _client(*, identity: dict | None = None, unauthorized: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(bridge.router)
    if unauthorized:
        def _raise() -> dict:
            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[verify_token] = _raise
    elif identity is not None:
        app.dependency_overrides[verify_token] = lambda: identity
    return TestClient(app)


def _bridge_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in bridge.router.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/tca/runner"):
            continue
        if not (path.startswith("/api/tca") or path.startswith("/api/costview")):
            continue
        for method in sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}):
            routes.append((method, path))
    return routes


def test_bridge_requires_token_on_all_endpoints():
    """14 个端点缺 token 一律 401（A04 验收）。"""
    routes = _bridge_routes()
    assert len(routes) == 14, routes
    client = _client(unauthorized=True)
    for method, path in routes:
        url = path.replace("{order_id}", "1")
        response = client.request(method, url, json={})
        assert response.status_code == 401, (method, path, response.status_code)


def test_pin_requires_trade_role():
    """viewer 写 pin → 403（桥接写方法要求 trade）。"""
    client = _client(identity={"sub": "v1", "role": "viewer"})
    response = client.post("/api/tca/recommendations/pin", json={})
    assert response.status_code == 403


def test_read_endpoint_allowed_for_viewer():
    """viewer 读端点不被鉴权层拦截。"""
    client = _client(identity={"sub": "v1", "role": "viewer"})
    response = client.get("/api/tca/capabilities")
    assert response.status_code not in (401, 403)


def test_runner_run_requires_admin(monkeypatch):
    """触发 ETL 要求 admin；trader/viewer 403。"""
    async def _fake_runner(method: str, path: str):
        return 200, {"ok": True}, None

    monkeypatch.setattr(bridge, "_request_runner", _fake_runner)

    trader = _client(identity={"sub": "t1", "role": "trader"})
    assert trader.post("/api/tca/runner/run").status_code == 403

    admin = _client(identity={"sub": "a1", "role": "admin"})
    assert admin.post("/api/tca/runner/run").status_code == 200
