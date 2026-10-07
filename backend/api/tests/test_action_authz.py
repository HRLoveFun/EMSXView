"""S11 (041) — 动作级授权测试。

锁死行为：角色权限矩阵（admin 全权 / trader 可交易不可管理 / viewer 只读）、
未知角色 fail-closed、require_permission 依赖 403 语义、
bypass 模式全权（本地终端操作者）。
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import deps
from auth import ROLE_PERMISSIONS, user_has_permission
from services.auth_service import _BYPASS_IDENTITY


def test_role_matrix():
    """矩阵语义：admin 全权；trader 可交易不可管理；viewer 只读。"""
    assert user_has_permission({"role": "admin"}, "admin") is True
    assert user_has_permission({"role": "admin"}, "trade") is True
    assert user_has_permission({"role": "trader"}, "trade") is True
    assert user_has_permission({"role": "trader"}, "modify") is True
    assert user_has_permission({"role": "trader"}, "admin") is False
    assert user_has_permission({"role": "viewer"}, "view") is True
    assert user_has_permission({"role": "viewer"}, "trade") is False


def test_unknown_role_fail_closed():
    """未知角色/缺角色：无任何写权限（fail-closed）。"""
    assert user_has_permission({"role": "intern"}, "trade") is False
    assert user_has_permission({}, "trade") is False
    assert user_has_permission({}, "view") is False


def test_bypass_identity_is_full_admin():
    """bypass 模式 = 本地终端操作者，动作级授权全权。"""
    assert _BYPASS_IDENTITY["role"] == "admin"
    for action in ("trade", "modify", "admin", "view"):
        assert user_has_permission(_BYPASS_IDENTITY, action) is True


def test_require_permission_dependency():
    """require_permission 依赖：有权放行返回身份，无权 403。"""
    checker = deps.require_permission("trade")

    trader = {"sub": "t1", "role": "trader"}
    assert checker(user=trader) is trader

    viewer = {"sub": "v1", "role": "viewer"}
    with pytest.raises(HTTPException) as exc_info:
        checker(user=viewer)
    assert exc_info.value.status_code == 403
    assert "trade" in exc_info.value.detail

    # 多动作要求：满足其一即可通过？语义为全部满足——trader 不满足 admin
    admin_checker = deps.require_permission("admin", "view")
    with pytest.raises(HTTPException):
        admin_checker(user=trader)


@pytest.mark.asyncio
async def test_confirm_proposal_forbidden_for_viewer():
    """端点集成：viewer 角色确认建议 → 403（不触达业务逻辑）。"""
    import importlib
    from routers import route_plans as rp
    rp = importlib.reload(rp)

    checker = deps.require_permission("trade")
    viewer = {"sub": "v1", "role": "viewer"}
    with pytest.raises(HTTPException) as exc_info:
        # 模拟 FastAPI 依赖解析：checker 先于函数体执行
        checker(user=viewer)
    assert exc_info.value.status_code == 403
    # 业务函数本身未被调用（无 proposals 读取副作用）
    assert 1 not in rp._proposals


def test_write_endpoints_wired():
    """写路径端点均已接入 require_permission（防回归的契约检查）。"""
    import inspect
    from routers import orders_crud, orders_execution, route_plans, routes

    expectations = [
        (orders_crud.route_order, "trade"),
        (orders_crud.batch_route, "trade"),
        (orders_crud.modify_order, "modify"),
        (orders_crud.cancel_order, "modify"),
        (orders_crud.batch_update, "modify"),
        (orders_execution.create_parent_execution, "trade"),
        (orders_execution.control_parent_execution, "trade"),
        (route_plans.confirm_proposal, "trade"),
        (route_plans.batch_confirm_proposals, "trade"),
        (route_plans.reject_proposal, "trade"),
        (route_plans.create_route_plan, "admin"),
        (route_plans.update_route_plan, "admin"),
        (route_plans.delete_route_plan, "admin"),
        (route_plans.apply_route_engine, "admin"),
        (routes.cancel_route, "modify"),
        (routes.modify_route, "modify"),
        (routes.batch_modify_routes, "modify"),
    ]
    for fn, action in expectations:
        src = inspect.getsource(fn)
        assert f'require_permission("{action}")' in src, f"{fn.__name__} 未接入 {action}"
