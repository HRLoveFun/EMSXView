"""Shared FastAPI dependencies for routers.

Provides ``verify_token``, ``audit_log``, and FastAPI ``Depends()``-based
service injection for routers.

Services are stored in ``app.state`` and injected via::

    from deps import get_bloomberg_service, get_broker_storage_service
    async def my_route(bloomberg = Depends(get_bloomberg_service)): ...
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import user_has_permission
from config import settings
from service_provider import RepositoryProvider
from services.auth_service import authenticate as _authenticate

logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Verify JWT token for API authentication — delegates to auth_service."""
    token = credentials.credentials if credentials else None
    return _authenticate(token)


def require_permission(*required: str):
    """动作级授权依赖工厂 (S11/041)。

    用法：``user: dict = Depends(require_permission("trade"))``。
    在 verify_token 认证之上检查角色权限矩阵（auth.ROLE_PERMISSIONS），
    未知角色 fail-closed（无任何写权限）。
    """
    def checker(user: dict = Depends(verify_token)) -> dict:
        for action in required:
            if not user_has_permission(user, action):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Action '{action}' not permitted for role "
                        f"'{user.get('role', '')}'"
                    ),
                )
        return user
    return checker


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

# Injected by init_services()
_repo_provider: Optional[RepositoryProvider] = None


def init_services(bloomberg_service, broker_storage, repo_provider) -> None:
    """Wire the audit RepositoryProvider singleton.

    Called once from main.py after construction. Bloomberg/Broker storage
    services are now injected via app.state + Depends(); this function only
    handles the audit persistence provider for backward compatibility.
    """
    global _repo_provider
    _repo_provider = repo_provider


def get_repo_provider() -> Optional[RepositoryProvider]:
    """访问 RepositoryProvider 单例 (S8/038)。

    建议持久化等非 Depends 注入路径使用——模块级内存缓存（route_plans）
    无法走 FastAPI Depends，须直接读取 provider。
    """
    return _repo_provider


def audit_log(
    action: str,
    user: str,
    details: dict,
    result: str = "PENDING",
    correlation_id: Optional[str] = None,
) -> None:
    """记录交易操作审计事件（操作发起时调用）— with optional DB persistence.

    两阶段审计 (S6/036)：本函数只记录「有人发起操作」，result 固定为
    PENDING（此前硬编码 "ok"，操作尚未执行就宣称成功——审计语义说谎）。
    操作完成后由 ``audit_result`` 按 correlation_id 回填真实结果
    （ok / fail / unknown，unknown 用于请求超时等结果未知场景）。
    """
    if settings.ENABLE_AUDIT_LOG:
        logger.info(f"AUDIT: {action} | User: {user} | Details: {json.dumps(details)}")
    if _repo_provider and _repo_provider.is_active:
        asyncio.ensure_future(
            _repo_provider.persist_audit_event(
                action=action,
                actor=user,
                endpoint=action,
                result=result,
                correlation_id=correlation_id,
                payload_summary=json.dumps(details)[:500] if details else None,
            )
        )


def audit_result(correlation_id: str, result: str) -> None:
    """回填审计事件的真实结果 (S6/036) — ok / fail / unknown。

    与 audit_log 的 correlation_id 关联；未持久化（无 provider / 未激活）
    时静默跳过——与 audit_log 的降级语义一致。
    """
    if _repo_provider and _repo_provider.is_active:
        asyncio.ensure_future(
            _repo_provider.update_audit_result(
                correlation_id=correlation_id,
                result=result,
            )
        )


# ---------------------------------------------------------------------------
# FastAPI Depends() based service injection (canonical accessors).
# ---------------------------------------------------------------------------


def get_bloomberg_service(request: Request):
    """FastAPI Depends() accessor — resolves BloombergEMSXService from app.state."""
    return request.app.state.bloomberg_service


def get_broker_storage_service(request: Request):
    """FastAPI Depends() accessor — resolves BrokerAlgorithmStorageService from app.state."""
    return request.app.state.broker_storage
